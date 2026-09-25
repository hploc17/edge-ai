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
      } else if (msg.type === "heartbeat") {
        const edgeId = msg.edge_id;
        const status = msg.status || "online";
        setNodesGeoJSON((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            features: prev.features.map((f) => {
              if (f.properties.edge_id === edgeId) {
                return {
                  ...f,
                  properties: {
                    ...f.properties,
                    status: status,
                    last_seen: msg.last_seen
                  }
                };
              }
              return f;
            })
          };
        });
        setNodesList((prev) =>
          prev.map((n) => (n.edge_id === edgeId ? { ...n, status, last_seen: msg.last_seen } : n))
        );
      } else if (msg.type === "node_registered") {
        const rawNode = msg.node || {};
        const edgeId = msg.edge_id || rawNode.edge_id;
        const lat = Number(rawNode.latitude ?? rawNode.geo?.lat ?? 20.998412);
        const lng = Number(rawNode.longitude ?? rawNode.geo?.lng ?? 105.795123);
        const nodeName = rawNode.name || rawNode.device_name || `Camera AI (${edgeId})`;

        // Update or append to nodes list
        setNodesList((prev) => {
          const idx = prev.findIndex((n) => n.edge_id === edgeId);
          const fullNode: NodeDetail = {
            edge_id: edgeId,
            name: nodeName,
            camera_id: rawNode.camera_id || "camera-01",
            segment_id: rawNode.segment_id || "segment-001",
            road_name: rawNode.road_name || "Đường Nguyễn Trãi",
            latitude: lat,
            longitude: lng,
            altitude_m: rawNode.altitude_m || 12.5,
            camera_heading: rawNode.camera_heading || 45.0,
            camera_fov: rawNode.camera_fov || 65.0,
            status: "online",
            traffic_status: rawNode.traffic_status || "FREE",
            congestion_score: rawNode.congestion_score || 0,
            avg_speed_kmh: rawNode.avg_speed_kmh || 0,
            current_vehicle_count: rawNode.current_vehicle_count || 0,
            stopped_vehicle_count: rawNode.stopped_vehicle_count || 0,
            density_veh_per_km_lane: rawNode.density_veh_per_km_lane || 0,
            counts_by_class: rawNode.counts_by_class || { motorcycle: 0, car: 0, bus: 0, truck: 0 },
            last_seen: rawNode.last_seen || rawNode.timestamp || new Date().toISOString(),
            ...rawNode
          };
          if (idx >= 0) {
            const updated = [...prev];
            updated[idx] = { ...updated[idx], ...fullNode };
            return updated;
          }
          return [...prev, fullNode];
        });

        // Update or append to map GeoJSON points
        setNodesGeoJSON((prev) => {
          if (!prev) return prev;
          const exists = prev.features.some((f) => f.properties.edge_id === edgeId);
          if (exists) {
            return {
              ...prev,
              features: prev.features.map((f) =>
                f.properties.edge_id === edgeId
                  ? {
                      ...f,
                      properties: {
                        ...f.properties,
                        status: "online",
                        last_seen: rawNode.last_seen || rawNode.timestamp,
                        name: nodeName
                      }
                    }
                  : f
              )
            };
          }
          // Dynamically create GeoJSON Feature for the newly connected Jetson node
          const newFeature = {
            type: "Feature" as const,
            geometry: {
              type: "Point" as const,
              coordinates: [lng, lat]
            },
            properties: {
              edge_id: edgeId,
              name: nodeName,
              camera_id: rawNode.camera_id || "camera-01",
              segment_id: rawNode.segment_id || "segment-001",
              road_name: rawNode.road_name || "Đường Nguyễn Trãi",
              heading: Number(rawNode.camera_heading || 45.0),
              fov: Number(rawNode.camera_fov || 65.0),
              status: "online",
              traffic_status: "FREE",
              congestion_score: 0,
              avg_speed_kmh: 0,
              vehicle_count: 0,
              marker_color: "#10B981",
              last_seen: rawNode.last_seen || rawNode.timestamp
            }
          };
          return {
            ...prev,
            features: [...prev.features, newFeature]
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
