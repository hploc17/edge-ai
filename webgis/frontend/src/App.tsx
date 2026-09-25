import React, { useState, useEffect, useCallback } from "react";
import { WebGISMap } from "./components/Map/WebGISMap";
import { Navbar } from "./components/Navbar";
import { LayerControl } from "./components/Map/LayerControl";
import { NodeDashboardDrawer } from "./components/Dashboard/NodeDashboardDrawer";
import { DeviceHealthModal } from "./components/Dashboard/DeviceHealthModal";
import { CongestionHistoryModal } from "./components/History/CongestionHistoryModal";
import { NodeManagementPanel } from "./components/Fleet/NodeManagementPanel";
import { AddNodeModal } from "./components/Fleet/AddNodeModal";
import { RemoteControlModal } from "./components/Fleet/RemoteControlModal";
import type { GeoJSONFeatureCollection, NodeDetail, SummaryKPIs, HistoryRecord } from "./types/gis";
import { api } from "./services/api";
import { wsService } from "./services/websocket";

export const App: React.FC = () => {
  // Map layers data
  const [nodesGeoJSON, setNodesGeoJSON] = useState<GeoJSONFeatureCollection<any, any> | null>(null);
  const [segmentsGeoJSON, setSegmentsGeoJSON] = useState<GeoJSONFeatureCollection<any, any> | null>(null);
  const [nodesList, setNodesList] = useState<NodeDetail[]>([]);
  const [kpis, setKpis] = useState<SummaryKPIs | null>(null);

  // Basemap & Layer visibility
  const [basemap, setBasemap] = useState<string>("google");
  const [layersConfig, setLayersConfig] = useState({
    nodes: true,
    segments: true,
    fovCones: true,
    speedLabels: true
  });

  // Selected Node Drawer state
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeDetail, setSelectedNodeDetail] = useState<NodeDetail | null>(null);

  // Modals state
  const [isHealthOpen, setIsHealthOpen] = useState(false);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [historySegmentId, setHistorySegmentId] = useState("segment-001");
  const [isFleetOpen, setIsFleetOpen] = useState(false);
  const [isAddNodeOpen, setIsAddNodeOpen] = useState(false);
  const [remoteNode, setRemoteNode] = useState<NodeDetail | null>(null);


  // Coordinate Picking on Map
  const [isPickingLocation, setIsPickingLocation] = useState(false);
  const [pickedCoords, setPickedCoords] = useState<{ lng: number; lat: number } | null>(null);

  // Initial Data Load
  const fetchAllData = useCallback(async () => {
    try {
      const [nodesGeo, segmentsGeo, allNodes, kpiData] = await Promise.all([
        api.getNodesGeoJSON(),
        api.getSegmentsGeoJSON(),
        api.getAllNodes(),
        api.getSummaryKPIs()
      ]);
      setNodesGeoJSON(nodesGeo);
      setSegmentsGeoJSON(segmentsGeo);
      setNodesList(allNodes);
      setKpis(kpiData);
    } catch (err) {
      console.error("Initial load error:", err);
    }
  }, []);

  useEffect(() => {
    fetchAllData();
  }, [fetchAllData]);

  // Real-time WebSocket connection
  useEffect(() => {
    wsService.connect();

    const unsubscribe = wsService.subscribe((msg) => {
      if (msg.type === "telemetry") {
        const t = msg.data;
        // Update nodes GeoJSON marker color & properties
        setNodesGeoJSON((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            features: prev.features.map((f) => {
              if (f.properties.edge_id === msg.edge_id) {
                const score = t.congestion_score;
                const color = score >= 65 ? "#EF4444" : score >= 35 ? "#F59E0B" : "#10B981";
                return {
                  ...f,
                  properties: {
                    ...f.properties,
                    congestion_score: score,
                    traffic_status: t.traffic_status,
                    avg_speed_kmh: t.avg_speed_kmh,
                    vehicle_count: t.current_vehicle_count,
                    marker_color: color
                  }
                };
              }
              return f;
            })
          };
        });

        // Update segments GeoJSON corridor colors
        setSegmentsGeoJSON((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            features: prev.features.map((f) => {
              // Find matching node
              if (f.properties.segment_id === "segment-001" && msg.edge_id === "edge-01") {
                const score = t.congestion_score;
                const color = score >= 65 ? "#EF4444" : score >= 35 ? "#F59E0B" : "#10B981";
                return {
                  ...f,
                  properties: {
                    ...f.properties,
                    congestion_score: score,
                    traffic_status: t.traffic_status,
                    traffic_color: color,
                    avg_speed_kmh: t.avg_speed_kmh,
                    vehicle_count: t.current_vehicle_count
                  }
                };
              }
              return f;
            })
          };
        });

        // Update selected node detail if open
        setSelectedNodeDetail((prev) => {
          if (!prev || prev.edge_id !== msg.edge_id) return prev;
          return {
            ...prev,
            congestion_score: t.congestion_score,
            traffic_status: t.traffic_status,
            avg_speed_kmh: t.avg_speed_kmh,
            vehicle_count: t.current_vehicle_count,
            stopped_vehicle_count: t.stopped_vehicle_count,
            density_veh_per_km_lane: t.density_veh_per_km_lane,
            counts_by_class: t.counts_by_class
          };
        });
      } else if (msg.type === "device_health") {
        setSelectedNodeDetail((prev) => {
          if (!prev || prev.edge_id !== msg.edge_id) return prev;
          return {
            ...prev,
            latest_health: msg.health
          };
        });
      }
    });

    return () => {
      unsubscribe();
    };
  }, []);

  // Handle Node Click
  const handleSelectNode = async (edgeId: string) => {
    setSelectedNodeId(edgeId);
    try {
      const detail = await api.getNodeDetail(edgeId);
      setSelectedNodeDetail(detail);
    } catch (e) {
      console.error("Failed to load node detail:", e);
    }
  };

  const handleToggleLayer = (layerName: string) => {
    setLayersConfig((prev) => ({
      ...prev,
      [layerName]: !prev[layerName as keyof typeof prev]
    }));
  };

  // Time Playback from History Modal: Updates segment color on live map
  const handlePlaybackUpdate = (record: HistoryRecord) => {
    setSegmentsGeoJSON((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        features: prev.features.map((f) => {
          if (f.properties.segment_id === record.segment_id) {
            return {
              ...f,
              properties: {
                ...f.properties,
                congestion_score: record.congestion_score,
                traffic_status: record.traffic_status,
                traffic_color: record.traffic_color,
                avg_speed_kmh: record.avg_speed_kmh
              }
            };
          }
          return f;
        })
      };
    });
  };

  const handleLocationPicked = (lng: number, lat: number) => {
    setPickedCoords({ lng, lat });
    setIsPickingLocation(false);
    setIsAddNodeOpen(true);
  };

  return (
    <div className="relative w-screen h-screen overflow-hidden bg-slate-100 font-sans select-none text-slate-800">
      {/* Top Floating Navbar */}
      <Navbar
        kpis={kpis}
        onOpenHistory={() => {
          setHistorySegmentId("segment-001");
          setIsHistoryOpen(true);
        }}
        onOpenFleet={() => setIsFleetOpen(true)}
        onOpenAddNode={() => setIsAddNodeOpen(true)}
      />

      {/* Layer Control Menu */}
      <LayerControl
        currentBasemap={basemap}
        onSelectBasemap={setBasemap}
        layers={layersConfig}
        onToggleLayer={handleToggleLayer}
      />

      {/* Interactive Map Picking Banner */}
      {isPickingLocation && (
        <div className="absolute top-20 left-1/2 -translate-x-1/2 z-30 px-5 py-2.5 rounded-full bg-blue-600 text-white font-bold text-xs shadow-2xl flex items-center gap-2 animate-bounce border border-blue-400">
          <span>🎯 Nhấp chuột vào vị trí bất kỳ trên bản đồ để đặt trạm Camera!</span>
          <button
            onClick={() => {
              setIsPickingLocation(false);
              setIsAddNodeOpen(true);
            }}
            className="ml-2 px-2 py-0.5 bg-slate-900/60 rounded hover:bg-slate-900 text-slate-200"
          >
            Hủy
          </button>
        </div>
      )}

      {/* Core Map */}
      <WebGISMap
        nodesGeoJSON={nodesGeoJSON}
        segmentsGeoJSON={segmentsGeoJSON}
        selectedNodeId={selectedNodeId}
        onSelectNode={handleSelectNode}
        basemap={basemap}
        layersConfig={layersConfig}
        isPickingLocation={isPickingLocation}
        onLocationPicked={handleLocationPicked}
      />

      {/* Side Drawer Dashboard when Node is clicked */}
      <NodeDashboardDrawer
        node={selectedNodeDetail}
        onClose={() => {
          setSelectedNodeId(null);
          setSelectedNodeDetail(null);
        }}
        onOpenHealth={() => setIsHealthOpen(true)}
        onOpenHistoryForSegment={(segId) => {
          setHistorySegmentId(segId);
          setIsHistoryOpen(true);
        }}
        onOpenRemote={() => setRemoteNode(selectedNodeDetail)}
      />

      {/* Remote Control & ROI Setup Modal (khi mở từ Drawer hoặc Map) */}
      {remoteNode && (
        <RemoteControlModal
          edgeId={remoteNode.edge_id}
          nodeName={remoteNode.name}
          onClose={() => setRemoteNode(null)}
        />
      )}


      {/* Device Health Diagnostics Modal (Gói 2) */}
      {isHealthOpen && selectedNodeDetail && (
        <DeviceHealthModal
          edgeId={selectedNodeDetail.edge_id}
          nodeName={selectedNodeDetail.name}
          initialHealth={selectedNodeDetail.latest_health}
          onClose={() => setIsHealthOpen(false)}
        />
      )}

      {/* Congestion History & Playback Modal */}
      {isHistoryOpen && (
        <CongestionHistoryModal
          initialSegmentId={historySegmentId}
          onClose={() => setIsHistoryOpen(false)}
          onPlaybackUpdate={handlePlaybackUpdate}
        />
      )}

      {/* Node Fleet Management Sidebar */}
      {isFleetOpen && (
        <NodeManagementPanel
          nodes={nodesList}
          onClose={() => setIsFleetOpen(false)}
          onSelectNode={(edgeId) => {
            handleSelectNode(edgeId);
            setIsFleetOpen(false);
          }}
          onOpenAddNode={() => {
            setIsFleetOpen(false);
            setIsAddNodeOpen(true);
          }}
          onRefreshNodes={fetchAllData}
        />
      )}

      {/* Add Node Modal */}
      {isAddNodeOpen && (
        <AddNodeModal
          onClose={() => setIsAddNodeOpen(false)}
          onNodeAdded={fetchAllData}
          pickedCoords={pickedCoords}
          onEnablePickMode={() => {
            setIsAddNodeOpen(false);
            setIsPickingLocation(true);
          }}
        />
      )}
    </div>
  );
};

export default App;
