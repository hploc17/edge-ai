import React, { useState, useEffect, useCallback, useRef } from "react";
import { WebGISMap } from "../components/Map/WebGISMap";
import { Navbar } from "../components/Navbar";
import { LayerControl } from "../components/Map/LayerControl";
import { NodeDashboardDrawer } from "../components/Dashboard/NodeDashboardDrawer";
import { DeviceHealthModal } from "../components/Dashboard/DeviceHealthModal";
import { CongestionHistoryModal } from "../components/History/CongestionHistoryModal";
import { NodeManagementPanel } from "../components/Fleet/NodeManagementPanel";
import { AddNodeModal } from "../components/Fleet/AddNodeModal";
import { RemoteControlModal } from "../components/Fleet/RemoteControlModal";
import { CameraViewModal } from "../components/Camera/CameraViewModal";
import { PendingNodeApprovalModal } from "../components/Fleet/PendingNodeApprovalModal";
import type { GeoJSONFeatureCollection, NodeDetail, SummaryKPIs, HistoryRecord } from "../types/gis";
import { api } from "../services/api";
import { wsService } from "../services/websocket";
import { useAuth } from "../context/AuthContext";

export const WebGISDashboard: React.FC = () => {
  const { isStaff } = useAuth();

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
    speedLabels: true,
    trafficHeatmap: true
  });

  // Selected Node Drawer state
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeDetail, setSelectedNodeDetail] = useState<NodeDetail | null>(null);
  const [selectNodeTrigger, setSelectNodeTrigger] = useState<number>(0);

  // Modals state
  const [isHealthOpen, setIsHealthOpen] = useState(false);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [historySegmentId, setHistorySegmentId] = useState("segment-001");
  const [isFleetOpen, setIsFleetOpen] = useState(false);
  const [isAddNodeOpen, setIsAddNodeOpen] = useState(false);
  const [remoteNode, setRemoteNode] = useState<NodeDetail | null>(null);
  const [isRemoteMinimized, setIsRemoteMinimized] = useState(false);
  const [cameraModalNode, setCameraModalNode] = useState<NodeDetail | null>(null);

  // Pending Node Approval & Hardware MAC setup
  const [pendingCount, setPendingCount] = useState(0);
  const [isPendingApprovalOpen, setIsPendingApprovalOpen] = useState(false);
  const [editingNodeForApproval, setEditingNodeForApproval] = useState<NodeDetail | null>(null);
  const [initialEdgeIdForApproval, setInitialEdgeIdForApproval] = useState<string | null>(null);
  const [pickingForPendingNode, setPickingForPendingNode] = useState<string | null>(null);

  // Coordinate Picking on Map
  const [isPickingLocation, setIsPickingLocation] = useState(false);
  const [pickedCoords, setPickedCoords] = useState<{ lng: number; lat: number } | null>(null);

  // Map lưu trữ ánh xạ edge_id -> segment_id không làm đơ re-render (Fix F1)
  const edgeSegmentMapRef = useRef<Record<string, string>>({});

  // Initial Data Load (Persistent State - Mục 5)
  const fetchAllData = useCallback(async () => {
    try {
      const [nodesGeo, segmentsGeo, allNodes, kpiData, liveStates] = await Promise.all([
        api.getNodesGeoJSON(),
        api.getSegmentsGeoJSON(),
        api.getAllNodes(),
        api.getSummaryKPIs(),
        api.getNodesLiveStates().catch(() => ({} as Record<string, any>))
      ]);

      // Gộp snapshot live states gần nhất để khôi phục ngay lập tức số liệu kẹt xe & phần cứng
      const mergedNodes = allNodes.map((n) => {
        const live = liveStates && liveStates[n.edge_id];
        if (live) {
          return {
            ...n,
            congestion_score: live.congestion_score ?? n.congestion_score,
            traffic_status: live.traffic_status ?? n.traffic_status,
            avg_speed_kmh: live.avg_speed_kmh ?? n.avg_speed_kmh,
            current_vehicle_count: live.current_vehicle_count ?? n.current_vehicle_count,
            stopped_vehicle_count: live.stopped_vehicle_count ?? n.stopped_vehicle_count,
            density_veh_per_km_lane: live.density_veh_per_km_lane ?? n.density_veh_per_km_lane,
            counts_by_class: live.counts_by_class ?? n.counts_by_class,
            latest_health: live.latest_health ?? n.latest_health,
            status: live.status ?? n.status,
            last_seen: live.last_seen ?? n.last_seen,
          };
        }
        return n;
      });

      // Lưu ánh xạ edge_id -> segment_id chính xác (Fix F1)
      mergedNodes.forEach((n) => {
        if (n.edge_id && n.segment_id) {
          edgeSegmentMapRef.current[n.edge_id] = n.segment_id;
        }
      });

      setNodesGeoJSON(nodesGeo);
      setSegmentsGeoJSON(segmentsGeo);
      setNodesList(mergedNodes);
      setKpis(kpiData);

      // Mặc định tự động chọn node đầu tiên để mở Drawer và căn giữa tâm màn hình
      if (mergedNodes && mergedNodes.length > 0) {
        setSelectedNodeId((prevId) => {
          if (!prevId) {
            const firstNode = mergedNodes[0];
            setSelectedNodeDetail(firstNode);
            setSelectNodeTrigger(Date.now());
            return firstNode.edge_id;
          }
          return prevId;
        });
      }
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

    // Tự động đồng bộ lại toàn bộ dữ liệu GIS khi WebSocket kết nối lại sau sự cố mất mạng (Fix D4)
    const unbindReconnect = wsService.onReconnect(() => {
      console.log("[WebGIS] WebSocket reconnected, re-syncing full network data...");
      fetchAllData();
    });

    const unsubscribe = wsService.subscribe((msg) => {
      if (msg.type === "telemetry") {
        const t = msg.data;
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
                    status: "online",
                    marker_color: color
                  }
                };
              }
              return f;
            })
          };
        });

        // Xác định chính xác segment_id của node gửi telemetry, loại bỏ hoàn toàn ID gán cứng (Fix F1)
        const targetSegmentId = msg.data?.segment_id || edgeSegmentMapRef.current[msg.edge_id];
        if (targetSegmentId) {
          edgeSegmentMapRef.current[msg.edge_id] = targetSegmentId;
        }

        setSegmentsGeoJSON((prev) => {
          if (!prev || !targetSegmentId) return prev;
          const score = t.congestion_score ?? 0;
          const color = score >= 65 ? "#EF4444" : score >= 35 ? "#F59E0B" : "#10B981";
          return {
            ...prev,
            features: prev.features.map((f) => {
              if (f.properties.segment_id === targetSegmentId) {
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

        setSelectedNodeDetail((prev) => {
          if (!prev || prev.edge_id !== msg.edge_id) return prev;
          // Đồng bộ edge_metrics vào nhánh hardware để Drawer không bị chớp nháy (Mục 1)
          const em = t.edge_metrics || {};
          const prevHw = prev.latest_health?.hardware || ({} as any);
          const hasEm = em && (em.cpu_percent !== undefined || em.cpu_usage_pct !== undefined || em.temperature_c !== undefined);
          const updatedHealth = hasEm ? {
            ...prev.latest_health,
            hardware: {
              ...prevHw,
              cpu_usage_pct: em.cpu_percent ?? em.cpu_usage_pct ?? prevHw.cpu_usage_pct,
              gpu_usage_pct: em.gpu_percent ?? em.gpu_usage_pct ?? prevHw.gpu_usage_pct,
              ram_usage_pct: em.ram_percent ?? em.ram_usage_pct ?? prevHw.ram_usage_pct,
              temperature_c: em.temperature_c ?? prevHw.temperature_c,
              fps: em.fps ?? prevHw.fps,
            }
          } : prev.latest_health;

          return {
            ...prev,
            congestion_score: t.congestion_score,
            traffic_status: t.traffic_status,
            avg_speed_kmh: t.avg_speed_kmh,
            vehicle_count: t.current_vehicle_count,
            stopped_vehicle_count: t.stopped_vehicle_count,
            density_veh_per_km_lane: t.density_veh_per_km_lane,
            counts_by_class: t.counts_by_class,
            latest_health: updatedHealth
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
      } else if (msg.type === "device_pending") {
        setPendingCount(msg.pending_count ?? 1);
        if (msg.require_setup && isStaff) {
          setEditingNodeForApproval(null);
          setInitialEdgeIdForApproval(msg.edge_id || null);
          setIsPendingApprovalOpen(true);
        }
      } else if (msg.type === "node_deleted") {
        const deletedId = msg.edge_id;
        setNodesGeoJSON((prev) => {
          if (!prev) return prev;
          return { ...prev, features: prev.features.filter(f => f.properties.edge_id !== deletedId) };
        });
        setNodesList((prev) => prev.filter(n => n.edge_id !== deletedId));
        if (selectedNodeId === deletedId) {
          setSelectedNodeId(null);
          setSelectedNodeDetail(null);
        }
      } else if (msg.type === "node_registered" || msg.type === "NODE_ADDED") {
        const rawNode = msg.node || {};
        const edgeId = msg.edge_id || rawNode.edge_id;
        if (edgeId && rawNode.segment_id) {
          edgeSegmentMapRef.current[edgeId] = rawNode.segment_id;
        }
        const lat = Number(rawNode.latitude ?? rawNode.geo?.lat ?? 20.998412);
        const lng = Number(rawNode.longitude ?? rawNode.geo?.lng ?? 105.795123);
        const nodeName = rawNode.name || rawNode.device_name || `Camera AI (${edgeId})`;

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
      } else if (msg.type === "snapshot_updated") {
        const edgeId = msg.edge_id;
        const snapshotUrl = msg.snapshot_url;

        setNodesList((prev) =>
          prev.map((n) =>
            n.edge_id === edgeId
              ? { ...n, snapshot_url: snapshotUrl, last_seen: new Date().toISOString() }
              : n
          )
        );

        setSelectedNodeDetail((prev) => {
          if (!prev || prev.edge_id !== edgeId) return prev;
          return { ...prev, snapshot_url: snapshotUrl, last_seen: new Date().toISOString() };
        });

        setCameraModalNode((prev) => {
          if (!prev || prev.edge_id !== edgeId) return prev;
          return { ...prev, snapshot_url: snapshotUrl, last_seen: new Date().toISOString() };
        });

        setNodesGeoJSON((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            features: prev.features.map((f) =>
              f.properties.edge_id === edgeId
                ? {
                    ...f,
                    properties: {
                      ...f.properties,
                      snapshot_url: snapshotUrl,
                      last_seen: new Date().toISOString()
                    }
                  }
                : f
            )
          };
        });
      } else if (msg.type === "segment_update" || msg.type === "segment_updated") {
        // Cập nhật hoặc tạo mới LineString segment ngay khi backend phát (Fix F2)
        const segData = (msg as any).segment || (msg as any).data;
        const segId = (msg as any).segment_id || segData?.segment_id;
        if (segId) {
          setSegmentsGeoJSON((prev) => {
            if (!prev) return prev;
            const exists = prev.features.some((f) => f.properties.segment_id === segId);
            if (exists) {
              return {
                ...prev,
                features: prev.features.map((f) => {
                  if (f.properties.segment_id === segId) {
                    return {
                      ...f,
                      properties: {
                        ...f.properties,
                        ...segData,
                        traffic_color: segData?.traffic_color || f.properties.traffic_color,
                        congestion_score: segData?.congestion_score ?? f.properties.congestion_score,
                        traffic_status: segData?.traffic_status || f.properties.traffic_status,
                      }
                    };
                  }
                  return f;
                })
              };
            }
            const coords = segData?.osm_coordinates || segData?.coordinates;
            if (coords && Array.isArray(coords) && coords.length >= 2) {
              const newFeature = {
                type: "Feature" as const,
                geometry: {
                  type: "LineString" as const,
                  coordinates: coords
                },
                properties: {
                  segment_id: segId,
                  road_name: segData?.name || segData?.road_name || `Đoạn ${segId}`,
                  lane_count: segData?.lane_count || 2,
                  road_length_m: segData?.road_length_m || 100.0,
                  road_width_m: segData?.road_width_m || 7.0,
                  speed_limit_kmh: segData?.speed_limit_kmh || 60.0,
                  traffic_status: segData?.traffic_status || "FREE",
                  congestion_score: segData?.congestion_score || 0,
                  traffic_color: segData?.traffic_color || "#10B981",
                  avg_speed_kmh: segData?.avg_speed_kmh || 0,
                  vehicle_count: segData?.vehicle_count || 0,
                  ...segData
                }
              };
              return {
                ...prev,
                features: [...prev.features, newFeature]
              };
            }
            return prev;
          });
        }
      } else if (msg.type === "node_mismatch_warning") {
        // Cập nhật cảnh báo sai lệch mã định danh thiết bị tức thời lên UI (Fix F2)
        const edgeId = (msg as any).edge_id;
        setNodesGeoJSON((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            features: prev.features.map((f) =>
              f.properties.edge_id === edgeId
                ? {
                    ...f,
                    properties: {
                      ...f.properties,
                      id_mismatch: true,
                      actual_hardware_id: (msg as any).actual_hardware_id,
                      mismatch_message: (msg as any).message
                    }
                  }
                : f
            )
          };
        });
        setNodesList((prev) =>
          prev.map((n) =>
            n.edge_id === edgeId
              ? {
                  ...n,
                  id_mismatch: true,
                  actual_hardware_id: (msg as any).actual_hardware_id,
                  mismatch_message: (msg as any).message
                }
              : n
          )
        );
        setSelectedNodeDetail((prev) => {
          if (!prev || prev.edge_id !== edgeId) return prev;
          return {
            ...prev,
            id_mismatch: true,
            actual_hardware_id: (msg as any).actual_hardware_id,
            mismatch_message: (msg as any).message
          };
        });
      } else if (msg.type === "spatial_drift_warning") {
        // Cập nhật cảnh báo dịch chuyển phần cứng GPS tức thời lên UI (Fix F2)
        const edgeId = (msg as any).edge_id;
        const driftData = {
          drift_m: (msg as any).drift_m,
          reported_coords: (msg as any).reported_coords,
          saved_coords: (msg as any).saved_coords
        };
        setNodesGeoJSON((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            features: prev.features.map((f) =>
              f.properties.edge_id === edgeId
                ? {
                    ...f,
                    properties: {
                      ...f.properties,
                      spatial_drift: driftData
                    }
                  }
                : f
            )
          };
        });
        setNodesList((prev) =>
          prev.map((n) =>
            n.edge_id === edgeId
              ? {
                  ...n,
                  spatial_drift: driftData
                }
              : n
          )
        );
        setSelectedNodeDetail((prev) => {
          if (!prev || prev.edge_id !== edgeId) return prev;
          return {
            ...prev,
            spatial_drift: driftData
          };
        });
      }
    });

    return () => {
      unbindReconnect();
      unsubscribe();
    };
  }, [isStaff]);

  // Handle Node Click
  const handleSelectNode = async (edgeId: string) => {
    setSelectedNodeId(edgeId);
    setSelectNodeTrigger(Date.now());
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
    if (pickingForPendingNode) {
      setIsPendingApprovalOpen(true);
    } else {
      setIsAddNodeOpen(true);
    }
  };

  return (
    <div className="relative w-screen h-screen overflow-hidden bg-slate-100 font-sans select-none text-slate-800">
      {/* Top Floating Navbar */}
      <Navbar
        kpis={kpis}
        pendingCount={pendingCount}
        onOpenHistory={() => {
          setHistorySegmentId("segment-001");
          setIsHistoryOpen(true);
        }}
        onOpenFleet={() => setIsFleetOpen(true)}
        onOpenAddNode={() => setIsAddNodeOpen(true)}
        onOpenPendingApproval={() => setIsPendingApprovalOpen(true)}
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
            className="ml-2 px-2 py-0.5 bg-slate-900/60 rounded hover:bg-slate-900 text-slate-200 cursor-pointer"
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
        selectNodeTrigger={selectNodeTrigger}
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
        onOpenCamera={() => setCameraModalNode(selectedNodeDetail)}
      />

      {/* Camera Live View & On-Demand Snapshot Modal (CÔNG KHAI) */}
      <CameraViewModal
        isOpen={!!cameraModalNode}
        onClose={() => setCameraModalNode(null)}
        node={cameraModalNode}
      />

      {/* Remote Control & ROI Setup Modal (STAFF ONLY) */}
      {remoteNode && isStaff && (
        <RemoteControlModal
          edgeId={remoteNode.edge_id}
          nodeName={remoteNode.name}
          isMinimized={isRemoteMinimized}
          onMinimize={() => setIsRemoteMinimized(true)}
          onRestore={() => setIsRemoteMinimized(false)}
          onClose={() => {
            setRemoteNode(null);
            setIsRemoteMinimized(false);
          }}
        />
      )}

      {/* Device Health Diagnostics Modal (STAFF ONLY) */}
      {isHealthOpen && selectedNodeDetail && isStaff && (
        <DeviceHealthModal
          edgeId={selectedNodeDetail.edge_id}
          nodeName={selectedNodeDetail.name}
          initialHealth={selectedNodeDetail.latest_health}
          onClose={() => setIsHealthOpen(false)}
        />
      )}

      {/* Congestion History & Playback Modal (CÔNG KHAI) */}
      {isHistoryOpen && (
        <CongestionHistoryModal
          initialSegmentId={historySegmentId}
          onClose={() => setIsHistoryOpen(false)}
          onPlaybackUpdate={handlePlaybackUpdate}
        />
      )}

      {/* Node Fleet Management Sidebar (STAFF ONLY) */}
      {isFleetOpen && isStaff && (
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
          onOpenCamera={(node) => setCameraModalNode(node)}
          onOpenRemote={(node) => setRemoteNode(node)}
          onEditNode={(node) => {
            setEditingNodeForApproval(node);
            setInitialEdgeIdForApproval(node.edge_id);
            setIsPendingApprovalOpen(true);
          }}
        />
      )}

      {/* Add Node Modal (STAFF ONLY) */}
      {isAddNodeOpen && isStaff && (
        <AddNodeModal
          onClose={() => setIsAddNodeOpen(false)}
          onNodeAdded={fetchAllData}
          pickedCoords={pickedCoords}
          onEnablePickMode={() => {
            setIsAddNodeOpen(false);
            setPickingForPendingNode(null);
            setIsPickingLocation(true);
          }}
        />
      )}

      {/* Pending Node Approval & Hardware MAC Setup Modal (STAFF ONLY) */}
      {isPendingApprovalOpen && isStaff && (
        <PendingNodeApprovalModal
          onClose={() => {
            setIsPendingApprovalOpen(false);
            setPickingForPendingNode(null);
            setPickedCoords(null);
            setEditingNodeForApproval(null);
            setInitialEdgeIdForApproval(null);
          }}
          onEnablePickMode={(edgeId) => {
            setPickingForPendingNode(edgeId);
            setIsPendingApprovalOpen(false);
            setIsPickingLocation(true);
          }}
          pickedCoords={pickingForPendingNode && pickedCoords
            ? { lat: pickedCoords.lat, lng: pickedCoords.lng }
            : null
          }
          onNodeApproved={() => {
            fetchAllData();
            setPendingCount(prev => Math.max(0, prev - 1));
            setEditingNodeForApproval(null);
            setInitialEdgeIdForApproval(null);
          }}
          editingNode={editingNodeForApproval}
          initialSelectedEdgeId={initialEdgeIdForApproval}
        />
      )}
    </div>
  );
};
