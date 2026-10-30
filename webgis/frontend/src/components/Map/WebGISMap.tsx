import React, { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import type { GeoJSONFeatureCollection } from "../../types/gis";

maplibregl.setWorkerUrl(maplibreWorkerUrl);

interface WebGISMapProps {
  nodesGeoJSON: GeoJSONFeatureCollection<any, any> | null;
  segmentsGeoJSON: GeoJSONFeatureCollection<any, any> | null;
  selectedNodeId: string | null;
  selectNodeTrigger?: number;
  onSelectNode: (edgeId: string) => void;
  basemap: string;
  layersConfig: {
    nodes: boolean;
    segments: boolean;
    fovCones: boolean;
    speedLabels: boolean;
    trafficHeatmap?: boolean;
  };
  isPickingLocation?: boolean;
  onLocationPicked?: (lng: number, lat: number) => void;
}

// 100% Reliable, Zero-Token Light & Google Maps Styles
const BASEMAP_STYLES: Record<string, any> = {
  google: {
    version: 8,
    sources: {
      "google-roadmap": {
        type: "raster",
        tiles: [
          "https://mt0.google.com/vt/lyrs=m&hl=vi&x={x}&y={y}&z={z}",
          "https://mt1.google.com/vt/lyrs=m&hl=vi&x={x}&y={y}&z={z}",
          "https://mt2.google.com/vt/lyrs=m&hl=vi&x={x}&y={y}&z={z}",
          "https://mt3.google.com/vt/lyrs=m&hl=vi&x={x}&y={y}&z={z}"
        ],
        tileSize: 256,
        attribution: "© Google Maps"
      }
    },
    layers: [
      {
        id: "google-roadmap-layer",
        type: "raster",
        source: "google-roadmap",
        minzoom: 0,
        maxzoom: 22
      }
    ]
  },
  google_satellite: {
    version: 8,
    sources: {
      "google-satellite": {
        type: "raster",
        tiles: [
          "https://mt0.google.com/vt/lyrs=y&hl=vi&x={x}&y={y}&z={z}",
          "https://mt1.google.com/vt/lyrs=y&hl=vi&x={x}&y={y}&z={z}",
          "https://mt2.google.com/vt/lyrs=y&hl=vi&x={x}&y={y}&z={z}",
          "https://mt3.google.com/vt/lyrs=y&hl=vi&x={x}&y={y}&z={z}"
        ],
        tileSize: 256,
        attribution: "© Google Maps Vệ tinh"
      }
    },
    layers: [
      {
        id: "google-satellite-layer",
        type: "raster",
        source: "google-satellite",
        minzoom: 0,
        maxzoom: 22
      }
    ]
  },
  light: {
    version: 8,
    sources: {
      "carto-voyager": {
        type: "raster",
        tiles: [
          "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
          "https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
          "https://c.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png"
        ],
        tileSize: 256,
        attribution: "© CARTO, © OpenStreetMap"
      }
    },
    layers: [
      {
        id: "carto-voyager-layer",
        type: "raster",
        source: "carto-voyager",
        minzoom: 0,
        maxzoom: 19
      }
    ]
  },
  streets: {
    version: 8,
    sources: {
      "osm-streets": {
        type: "raster",
        tiles: [
          "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
          "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
          "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png"
        ],
        tileSize: 256,
        attribution: "© OpenStreetMap contributors"
      }
    },
    layers: [
      {
        id: "osm-streets-layer",
        type: "raster",
        source: "osm-streets",
        minzoom: 0,
        maxzoom: 19
      }
    ]
  },
  satellite: {
    version: 8,
    sources: {
      "esri-satellite": {
        type: "raster",
        tiles: [
          "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ],
        tileSize: 256,
        attribution: "Esri World Imagery"
      }
    },
    layers: [
      {
        id: "esri-satellite-layer",
        type: "raster",
        source: "esri-satellite",
        minzoom: 0,
        maxzoom: 19
      }
    ]
  }
};

// Căn node camera nằm CHÍNH GIỮA tâm màn hình theo yêu cầu
const getCameraPadding = () => {
  return { top: 0, right: 0, bottom: 0, left: 0 };
};

export const WebGISMap: React.FC<WebGISMapProps> = ({
  nodesGeoJSON,
  segmentsGeoJSON,
  selectedNodeId,
  selectNodeTrigger,
  onSelectNode,
  basemap = "google",
  layersConfig,
  isPickingLocation = false,
  onLocationPicked
}) => {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);

  // Quản lý Marker bền vững (In-place Lifecycle) chống giật nháy khi telemetry cập nhật
  interface MarkerEntry {
    marker: maplibregl.Marker;
    element: HTMLDivElement;
    ring: HTMLDivElement;
    core: HTMLDivElement;
    badge?: HTMLDivElement;
    cone?: HTMLDivElement;
    coords: [number, number];
    edgeId: string;
  }
  const markersMapRef = useRef<Map<string, MarkerEntry>>(new Map());

  // Quản lý Hover On-Demand Live Video Stream
  const hoverTimerRef = useRef<number | null>(null);
  const hoverPopupRef = useRef<maplibregl.Popup | null>(null);
  const currentHoverEdgeIdRef = useRef<string | null>(null);

  const closeHoverStream = () => {
    if (hoverTimerRef.current !== null) {
      window.clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
    currentHoverEdgeIdRef.current = null;
    if (hoverPopupRef.current) {
      hoverPopupRef.current.remove();
      hoverPopupRef.current = null;
    }
  };

  const activePopupRef = useRef<maplibregl.Popup | null>(null);
  const segmentsGeoJSONRef = useRef(segmentsGeoJSON);
  segmentsGeoJSONRef.current = segmentsGeoJSON;
  const nodesGeoJSONRef = useRef(nodesGeoJSON);
  nodesGeoJSONRef.current = nodesGeoJSON;
  const isPickingLocationRef = useRef(isPickingLocation);
  isPickingLocationRef.current = isPickingLocation;
  // Use a ref for layersConfig to avoid stale closure in addTrafficLayers
  const layersConfigRef = useRef(layersConfig);
  layersConfigRef.current = layersConfig;

  // Bề rộng mặt đường thực tế phủ trọn 100% lòng đường trên nền bản đồ và co giãn theo zoom
  const getRoadWidth = (multiplier: number = 1.0) => [
    "interpolate", ["exponential", 1.5], ["zoom"],
    13, ["*", ["coalesce", ["get", "road_width_m"], 10], 0.45 * multiplier],
    14, ["*", ["coalesce", ["get", "road_width_m"], 10], 0.75 * multiplier],
    15, ["*", ["coalesce", ["get", "road_width_m"], 10], 1.25 * multiplier],
    16, ["*", ["coalesce", ["get", "road_width_m"], 10], 2.10 * multiplier],
    17, ["*", ["coalesce", ["get", "road_width_m"], 10], 3.40 * multiplier],
    18, ["*", ["coalesce", ["get", "road_width_m"], 10], 5.20 * multiplier],
    19, ["*", ["coalesce", ["get", "road_width_m"], 10], 7.50 * multiplier],
    20, ["*", ["coalesce", ["get", "road_width_m"], 10], 10.5 * multiplier]
  ];

  // addTrafficLayersStructure: Tạo source + layer 1 lần duy nhất (không phụ thuộc data)
  const addTrafficLayersStructure = (map: maplibregl.Map) => {
    const cfg = layersConfigRef.current;
    const segVis = cfg.segments ? "visible" : "none";
    const heatVis = cfg.segments && (cfg.trafficHeatmap ?? true) ? "visible" : "none";

    try {
      if (!map.getSource("traffic-segments")) {
        map.addSource("traffic-segments", {
          type: "geojson",
          data: segmentsGeoJSONRef.current || { type: "FeatureCollection", features: [] }
        });
      }
    } catch (err) {
      console.error("[Traffic] Error creating source:", err);
    }

    // 1. Tầng Hào quang Nhiệt Tỏa Rộng (Diffuse Thermal Halo)
    try {
      if (!map.getLayer("traffic-heat-halo")) {
        map.addLayer({
          id: "traffic-heat-halo",
          type: "line",
          source: "traffic-segments",
          layout: { "line-join": "round", "line-cap": "round", "visibility": heatVis },
          paint: {
            // MapLibre requires ["rgba", r, g, b, a] in interpolate expressions
            "line-color": [
              "interpolate", ["linear"], ["coalesce", ["get", "congestion_score"], 0],
              0,   ["rgba", 16, 185, 129, 0],
              25,  ["rgba", 16, 185, 129, 0],
              40,  ["rgba", 245, 158, 11, 0.45],
              65,  ["rgba", 239, 68, 68, 0.8],
              85,  ["rgba", 220, 38, 38, 0.95],
              100, ["rgba", 127, 29, 29, 1.0]
            ],
            "line-width": getRoadWidth(2.4) as any,
            "line-blur": 10,
            "line-opacity": [
              "interpolate", ["linear"], ["coalesce", ["get", "congestion_score"], 0],
              0,   0.0,
              25,  0.0,
              40,  0.5,
              65,  0.85,
              85,  0.95,
              100, 1.0
            ]
          }
        });
      }
    } catch (err) {
      console.error("[Traffic] Error adding traffic-heat-halo:", err);
    }

    // 2. Tầng Nhiệt Cận Viền (Thermal Radiation Aura)
    try {
      if (!map.getLayer("traffic-heat-aura")) {
        map.addLayer({
          id: "traffic-heat-aura",
          type: "line",
          source: "traffic-segments",
          layout: { "line-join": "round", "line-cap": "round", "visibility": heatVis },
          paint: {
            "line-color": [
              "interpolate", ["linear"], ["coalesce", ["get", "congestion_score"], 0],
              0,   ["rgba", 16, 185, 129, 0],
              30,  ["rgba", 245, 158, 11, 0.35],
              55,  ["rgba", 249, 115, 22, 0.75],
              75,  ["rgba", 239, 68, 68, 0.92],
              100, ["rgba", 185, 28, 28, 1.0]
            ],
            "line-width": getRoadWidth(1.45) as any,
            "line-blur": 4,
            "line-opacity": [
              "interpolate", ["linear"], ["coalesce", ["get", "congestion_score"], 0],
              0,   0.0,
              25,  0.0,
              40,  0.55,
              70,  0.9,
              100, 1.0
            ]
          }
        });
      }
    } catch (err) {
      console.error("[Traffic] Error adding traffic-heat-aura:", err);
    }

    // 3. Viền Casing định hình mép đường
    try {
      if (!map.getLayer("traffic-segments-casing")) {
        map.addLayer({
          id: "traffic-segments-casing",
          type: "line",
          source: "traffic-segments",
          layout: { "line-join": "round", "line-cap": "round", "visibility": segVis },
          paint: {
            "line-color": [
              "case",
              [">=", ["coalesce", ["get", "congestion_score"], 0], 65],
              ["to-color", "#ffe4e6"],
              ["to-color", "#ffffff"]
            ],
            "line-width": getRoadWidth(1.08) as any,
            "line-opacity": 0.95
          }
        });
      }
    } catch (err) {
      console.error("[Traffic] Error adding traffic-segments-casing:", err);
    }

    // 4. Lõi Nhiệt Đặc Phủ Trọn Lòng Đường (Full Road Width Thermal Core)
    try {
      if (!map.getLayer("traffic-segments-core")) {
        map.addLayer({
          id: "traffic-segments-core",
          type: "line",
          source: "traffic-segments",
          layout: { "line-join": "round", "line-cap": "round", "visibility": segVis },
          paint: {
            "line-color": [
              "interpolate", ["linear"], ["coalesce", ["get", "congestion_score"], 0],
              0,   ["to-color", "#10b981"],
              25,  ["to-color", "#22c55e"],
              45,  ["to-color", "#eab308"],
              60,  ["to-color", "#f97316"],
              75,  ["to-color", "#ef4444"],
              90,  ["to-color", "#dc2626"],
              100, ["to-color", "#7f1d1d"]
            ],
            "line-width": getRoadWidth(0.96) as any,
            "line-opacity": 0.95
          }
        });
      }
    } catch (err) {
      console.error("[Traffic] Error adding traffic-segments-core:", err);
    }

    // 5. Vạch Phân Làn / Dẫn Hướng Trung Tâm (Inner Flow Dashes)
    try {
      if (!map.getLayer("traffic-segments-dash")) {
        map.addLayer({
          id: "traffic-segments-dash",
          type: "line",
          source: "traffic-segments",
          layout: { "line-join": "round", "line-cap": "round", "visibility": segVis },
          paint: {
            "line-color": "#ffffff",
            "line-width": 2,
            "line-opacity": 0.9,
            "line-dasharray": ["literal", [2, 4]] as any
          }
        });
      }
    } catch (err) {
      console.error("[Traffic] Error adding traffic-segments-dash:", err);
    }
  };

  // updateTrafficData: Chỉ cập nhật dữ liệu GeoJSON vào source đã có (không tạo lại layer)
  const updateTrafficData = (map: maplibregl.Map) => {
    const geoData = segmentsGeoJSONRef.current || { type: "FeatureCollection", features: [] };
    const existingSource = map.getSource("traffic-segments") as maplibregl.GeoJSONSource;
    const featureCount = (geoData as any).features?.length ?? 0;
    console.log(`[Traffic] updateTrafficData: features=${featureCount}, source_exists=${!!existingSource}`);
    if (featureCount > 0) {
      const firstProps = (geoData as any).features[0]?.properties;
      console.log(`[Traffic] First segment: congestion_score=${firstProps?.congestion_score}, road_width_m=${firstProps?.road_width_m}`);
      console.log(`[Traffic] First coords:`, (geoData as any).features[0]?.geometry?.coordinates?.[0]);
    }
    if (existingSource) {
      existingSource.setData(geoData as any);
      console.log(`[Traffic] setData() called on existing source`);
    } else {
      // Source chưa tồn tại (vd: sau khi đổi basemap) -> tạo lại toàn bộ
      console.log(`[Traffic] Source missing -> calling addTrafficLayersStructure`);
      addTrafficLayersStructure(map);
    }
  };

  // addTrafficLayers: Wrapper để tương thích với code cũ
  const addTrafficLayers = (map: maplibregl.Map) => {
    addTrafficLayersStructure(map);
    updateTrafficData(map);
  };

  // Initialize Map
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;

    // Tính tâm bản đồ mặc định từ dữ liệu nodes (nếu có), fallback về Hà Nội
    const initialNodes = nodesGeoJSONRef.current;
    let defaultCenter: [number, number] = [105.792350, 21.000650]; // Hà Nội fallback
    let defaultZoom = 13;
    if (initialNodes && initialNodes.features && initialNodes.features.length > 0) {
      const firstCoords = initialNodes.features[0]?.geometry?.coordinates as [number, number];
      if (firstCoords && firstCoords.length === 2) {
        defaultCenter = firstCoords;
        defaultZoom = 16.8;
      }
    }

    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: BASEMAP_STYLES[basemap] || BASEMAP_STYLES.google,
      center: defaultCenter,
      zoom: defaultZoom,
      pitch: 0,
      bearing: 0,
      attributionControl: false
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

    map.on("load", () => {
      console.log(`[Traffic] map 'load' fired. segmentsGeoJSONRef has ${segmentsGeoJSONRef.current?.features?.length ?? 0} features`);
      addTrafficLayers(map);
      // Verify layers were added
      const layers = ["traffic-heat-halo", "traffic-heat-aura", "traffic-segments-casing", "traffic-segments-core", "traffic-segments-dash"];
      layers.forEach(id => console.log(`[Traffic] Layer '${id}' exists:`, !!map.getLayer(id)));
      console.log(`[Traffic] Source 'traffic-segments' exists:`, !!map.getSource("traffic-segments"));
      const map_center = map.getCenter();
      console.log(`[Traffic] Map center: lng=${map_center.lng.toFixed(4)}, lat=${map_center.lat.toFixed(4)}, zoom=${map.getZoom().toFixed(1)}`);

      map.on("mouseenter", "traffic-segments-core", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "traffic-segments-core", () => {
        if (!isPickingLocation) map.getCanvas().style.cursor = "";
      });

        // Interactive Popup on Road Segment Click
        map.on("click", "traffic-segments-core", (e) => {
          if (isPickingLocationRef.current || !e.features || !e.features[0]) return;
          const p = e.features[0].properties as any;
          const statusText = p.traffic_status === "CONGESTED" ? "ÙN TẮC" : (p.traffic_status === "SLOW" ? "ĐÔNG XE" : (p.traffic_status === "STALE" ? "MẤT DỮ LIỆU" : "THÔNG THOÁNG"));
          const badgeColor = p.traffic_status === "STALE" ? "#64748b" : (p.traffic_color || "#10b981");
          
          // Close existing popup if any
          if (activePopupRef.current) {
            activePopupRef.current.remove();
            activePopupRef.current = null;
          }

          const popup = new maplibregl.Popup({ closeButton: true, closeOnClick: true, className: "road-popup" })
            .setLngLat(e.lngLat)
            .setHTML(`
              <div style="font-family: Inter, sans-serif; padding: 6px 4px; color: #1e293b; min-width: 230px;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px;">
                  <strong style="font-size: 13px; color: #0f172a;">${p.road_name}</strong>
                  <span style="font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 6px; background: ${badgeColor}25; color: ${badgeColor};">
                    ${statusText}
                  </span>
                </div>
                <div style="font-size: 11px; line-height: 1.6; color: #334155; background: #f8fafc; padding: 8px; border-radius: 8px; border: 1px solid #e2e8f0;">
                  <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
                    <span style="color: #64748b;">🔥 Độ nhiệt kẹt xe:</span>
                    <b style="color: ${p.congestion_score >= 60 ? '#ef4444' : p.congestion_score >= 35 ? '#f59e0b' : '#10b981'}; font-family: monospace;">${p.congestion_score || 0} / 100</b>
                  </div>
                  <div style="width: 100%; height: 5px; background: #e2e8f0; border-radius: 999px; overflow: hidden; margin-bottom: 6px;">
                    <div style="height: 100%; width: ${Math.min(100, Math.max(5, p.congestion_score || 0))}%; background: ${p.congestion_score >= 60 ? 'linear-gradient(90deg, #f97316, #ef4444)' : p.congestion_score >= 35 ? '#f59e0b' : '#10b981'}; border-radius: 999px;"></div>
                  </div>
                  <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
                    <span style="color: #64748b;">📏 Chiều dài vùng nhiệt:</span>
                    <b style="color: #059669; font-family: monospace;">${p.road_length_m || 200} m</b>
                  </div>
                  <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
                    <span style="color: #64748b;">📐 Chiều rộng (Full đường):</span>
                    <b style="color: #2563eb; font-family: monospace;">${p.road_width_m || 16.0} m</b>
                  </div>
                  <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
                    <span style="color: #64748b;">🛣️ Quy mô mặt cắt:</span>
                    <b>${p.lane_count || 4} làn xe</b>
                  </div>
                  <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
                    <span style="color: #64748b;">⚡ Vận tốc trung bình:</span>
                    <b>${p.avg_speed_kmh} km/h</b>
                  </div>
                  <div style="display: flex; justify-content: space-between;">
                    <span style="color: #64748b;">🚗 Lượng xe hiện tại:</span>
                    <b>${p.vehicle_count} xe</b>
                  </div>
                </div>
              </div>
            `)
            .addTo(map);

          activePopupRef.current = popup;
          popup.on("close", () => {
            if (activePopupRef.current === popup) {
              activePopupRef.current = null;
            }
          });
        });

      map.on("movestart", closeHoverStream);
      map.on("zoomstart", closeHoverStream);
    });

    mapRef.current = map;

    return () => {
      closeHoverStream();
      markersMapRef.current.forEach((entry) => entry.marker.remove());
      markersMapRef.current.clear();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Handle Basemap Switch (Chỉ chạy khi user chủ động đổi basemap, KHÔNG chạy đè khi khởi tạo)
  const prevBasemapRef = useRef(basemap);
  useEffect(() => {
    if (!mapRef.current) return;
    if (prevBasemapRef.current === basemap) return;
    prevBasemapRef.current = basemap;

    const map = mapRef.current;
    const newStyle = BASEMAP_STYLES[basemap] || BASEMAP_STYLES.google;

    map.setStyle(newStyle);

    map.once("style.load", () => {
      addTrafficLayers(map);
    });
  }, [basemap]);

  // Update segments layer data dynamically when telemetry changes
  useEffect(() => {
    if (!mapRef.current) return;
    const map = mapRef.current;
    if (map.isStyleLoaded()) {
      // addTrafficLayers sẽ: nếu source đã có → setData; nếu chưa có → tạo source + layers + setData
      addTrafficLayers(map);
      console.log(`[Traffic] segmentsGeoJSON changed → addTrafficLayers called, isStyleLoaded=true`);
    } else {
      console.log(`[Traffic] segmentsGeoJSON changed → waiting for map load...`);
      map.once("style.load", () => {
        console.log(`[Traffic] map style.load fired from segmentsGeoJSON effect`);
        addTrafficLayers(map);
      });
    }
  }, [segmentsGeoJSON]);

  // Lần đầu tiên có dữ liệu segments (sau khi API trả về), bay tới vị trí segment
  // để tránh trường hợp map khởi động tại Hà Nội nhưng data lại ở TP.HCM
  const hasFlownToDataRef = useRef(false);
  useEffect(() => {
    if (!mapRef.current || !segmentsGeoJSON || hasFlownToDataRef.current) return;
    if (!segmentsGeoJSON.features || segmentsGeoJSON.features.length === 0) return;

    const firstFeature = segmentsGeoJSON.features[0];
    if (!firstFeature?.geometry?.coordinates || firstFeature.geometry.coordinates.length === 0) return;

    // Lấy điểm giữa của LineString segment đầu tiên để làm tâm bay
    const coords = firstFeature.geometry.coordinates as [number, number][];
    const midIdx = Math.floor(coords.length / 2);
    const centerCoord = coords[midIdx] || coords[0];

    hasFlownToDataRef.current = true; // Chỉ bay 1 lần

    // Chỉ bay nếu map đang ở xa (> 0.5 độ) so với segment
    const currentCenter = mapRef.current.getCenter();
    const distLng = Math.abs(currentCenter.lng - centerCoord[0]);
    const distLat = Math.abs(currentCenter.lat - centerCoord[1]);
    if (distLng > 0.5 || distLat > 0.5) {
      mapRef.current.flyTo({
        center: centerCoord,
        zoom: 16.5,
        duration: 1500,
        essential: true
      });
    }
  }, [segmentsGeoJSON]);

  // Toggle Segments & Heatmap visibility
  useEffect(() => {
    if (!mapRef.current) return;
    const map = mapRef.current;
    const segVis = layersConfig.segments ? "visible" : "none";
    const heatVis = layersConfig.segments && (layersConfig.trafficHeatmap ?? true) ? "visible" : "none";

    if (map.getLayer("traffic-heat-halo")) map.setLayoutProperty("traffic-heat-halo", "visibility", heatVis);
    if (map.getLayer("traffic-heat-aura")) map.setLayoutProperty("traffic-heat-aura", "visibility", heatVis);
    if (map.getLayer("traffic-segments-casing")) map.setLayoutProperty("traffic-segments-casing", "visibility", segVis);
    if (map.getLayer("traffic-segments-core")) map.setLayoutProperty("traffic-segments-core", "visibility", segVis);
    if (map.getLayer("traffic-segments-dash")) map.setLayoutProperty("traffic-segments-dash", "visibility", segVis);
  }, [layersConfig.segments, layersConfig.trafficHeatmap]);

  // Smoothly Fly and Center Selected Node on Map with Camera Padding (Anti-Jitter)
  // IMPORTANT: nodesGeoJSON is intentionally accessed via nodesGeoJSONRef.current to avoid
  // re-triggering flyTo every few seconds on WebSocket telemetry updates!
  useEffect(() => {
    if (!mapRef.current) return;
    const map = mapRef.current;

    // Close hover stream when selectedNodeId changes
    closeHoverStream();

    // When drawer closes (selectedNodeId becomes null), smoothly ease padding back to zero
    if (!selectedNodeId) {
      map.easeTo({
        padding: getCameraPadding(),
        duration: 400
      });
      return;
    }

    // Automatically close any open road segment popups so they don't cover the node
    if (activePopupRef.current) {
      activePopupRef.current.remove();
      activePopupRef.current = null;
    }

    const geoData = nodesGeoJSON || nodesGeoJSONRef.current;
    if (!geoData || !geoData.features || geoData.features.length === 0) return;

    const feature = geoData.features.find((f) => f.properties.edge_id === selectedNodeId);
    if (!feature || !feature.geometry || !feature.geometry.coordinates) return;

    const coords = feature.geometry.coordinates as [number, number];
    const currentZoom = map.getZoom();
    const targetZoom = Math.max(currentZoom, 17.2);

    map.flyTo({
      center: coords,
      zoom: targetZoom,
      padding: getCameraPadding(),
      duration: 1000,
      essential: true
    });
  }, [selectedNodeId, selectNodeTrigger, nodesGeoJSON?.features?.length]);

  // Render & Update In-Place Pulsing Dot Markers for Nodes (Anti-Flicker & Persistent Hover)
  useEffect(() => {
    if (!mapRef.current) return;
    const map = mapRef.current;

    if (!layersConfig.nodes || !nodesGeoJSON) {
      markersMapRef.current.forEach((entry) => entry.marker.remove());
      markersMapRef.current.clear();
      closeHoverStream();
      return;
    }

    const currentEdgeIds = new Set<string>();

    nodesGeoJSON.features.forEach((feature) => {
      const coords = feature.geometry.coordinates as [number, number];
      const props = feature.properties;
      const edgeId = props.edge_id;
      currentEdgeIds.add(edgeId);

      const isSelected = selectedNodeId === edgeId;
      const existingEntry = markersMapRef.current.get(edgeId);

      if (existingEntry) {
        // ── 1. CẬP NHẬT TẠI CHỖ (IN-PLACE) TRÊN DOM ELEMENT CÓ SẴN ──
        if (existingEntry.coords[0] !== coords[0] || existingEntry.coords[1] !== coords[1]) {
          existingEntry.marker.setLngLat(coords);
          existingEntry.coords = coords;
        }

        existingEntry.element.className = isSelected ? "pulsing-marker selected-node-marker" : "pulsing-marker";
        existingEntry.element.style.zIndex = isSelected ? "50" : "10";
        existingEntry.element.style.setProperty("--marker-glow-color", props.marker_color);

        const isAiRunning = Boolean(props.pipeline_running || (props.vehicle_count !== undefined && props.vehicle_count > 0));
        existingEntry.element.dataset.aiRunning = isAiRunning ? "true" : "false";

        existingEntry.ring.style.backgroundColor = props.marker_color;
        existingEntry.core.style.backgroundColor = props.marker_color;

        if (isSelected) {
          existingEntry.core.style.boxShadow = `0 0 0 3px rgba(255, 255, 255, 0.9), 0 0 24px 8px ${props.marker_color}`;
          existingEntry.core.style.transform = "scale(1.55)";
        } else {
          existingEntry.core.style.boxShadow = "";
          existingEntry.core.style.transform = "";
        }

        // Cập nhật Floating Name Badge
        if (isSelected) {
          if (!existingEntry.badge) {
            const badge = document.createElement("div");
            badge.className = "node-floating-badge";
            badge.innerHTML = `
              <span class="node-badge-dot" style="background-color: ${props.marker_color};"></span>
              <span class="node-badge-text">${props.name || props.edge_id}</span>
            `;
            existingEntry.element.appendChild(badge);
            existingEntry.badge = badge;
          } else {
            const dot = existingEntry.badge.querySelector(".node-badge-dot") as HTMLElement;
            if (dot) dot.style.backgroundColor = props.marker_color;
            const text = existingEntry.badge.querySelector(".node-badge-text") as HTMLElement;
            if (text) text.textContent = props.name || props.edge_id;
          }
        } else if (existingEntry.badge) {
          existingEntry.badge.remove();
          existingEntry.badge = undefined;
        }

        // Cập nhật Camera FOV Cone
        if (layersConfig.fovCones && props.heading !== undefined) {
          if (!existingEntry.cone) {
            const cone = document.createElement("div");
            cone.className = "camera-fov-cone";
            cone.style.transform = `rotate(${props.heading}deg)`;
            cone.innerHTML = `
              <svg viewBox="0 0 100 100" width="68" height="68">
                <polygon points="50,10 85,90 15,90" fill="${props.marker_color}" opacity="0.35" />
                <line x1="50" y1="50" x2="50" y2="10" stroke="${props.marker_color}" stroke-width="3" stroke-dasharray="3,3" />
              </svg>
            `;
            existingEntry.element.appendChild(cone);
            existingEntry.cone = cone;
          } else {
            existingEntry.cone.style.transform = `rotate(${props.heading}deg)`;
            const poly = existingEntry.cone.querySelector("polygon");
            if (poly) poly.setAttribute("fill", props.marker_color);
            const line = existingEntry.cone.querySelector("line");
            if (line) line.setAttribute("stroke", props.marker_color);
          }
        } else if (existingEntry.cone) {
          existingEntry.cone.remove();
          existingEntry.cone = undefined;
        }

      } else {
        // ── 2. TẠO MỚI MARKER ENTRY NẾU CHƯA CÓ TRONG MAP ──
        const el = document.createElement("div");
        el.className = isSelected ? "pulsing-marker selected-node-marker" : "pulsing-marker";
        el.style.zIndex = isSelected ? "50" : "10";
        el.style.setProperty("--marker-glow-color", props.marker_color);

        const ring = document.createElement("div");
        ring.className = "pulsing-marker-ring";
        ring.style.backgroundColor = props.marker_color;

        const core = document.createElement("div");
        core.className = "pulsing-marker-core";
        core.style.backgroundColor = props.marker_color;
        if (isSelected) {
          core.style.boxShadow = `0 0 0 3px rgba(255, 255, 255, 0.9), 0 0 24px 8px ${props.marker_color}`;
          core.style.transform = "scale(1.55)";
        }

        el.appendChild(ring);
        el.appendChild(core);

        let badge: HTMLDivElement | undefined;
        if (isSelected) {
          badge = document.createElement("div");
          badge.className = "node-floating-badge";
          badge.innerHTML = `
            <span class="node-badge-dot" style="background-color: ${props.marker_color};"></span>
            <span class="node-badge-text">${props.name || props.edge_id}</span>
          `;
          el.appendChild(badge);
        }

        let cone: HTMLDivElement | undefined;
        if (layersConfig.fovCones && props.heading !== undefined) {
          cone = document.createElement("div");
          cone.className = "camera-fov-cone";
          cone.style.transform = `rotate(${props.heading}deg)`;
          cone.innerHTML = `
            <svg viewBox="0 0 100 100" width="68" height="68">
              <polygon points="50,10 85,90 15,90" fill="${props.marker_color}" opacity="0.35" />
              <line x1="50" y1="50" x2="50" y2="10" stroke="${props.marker_color}" stroke-width="3" stroke-dasharray="3,3" />
            </svg>
          `;
          el.appendChild(cone);
        }

        const isAiRunning = Boolean(props.pipeline_running || (props.vehicle_count !== undefined && props.vehicle_count > 0));
        el.dataset.aiRunning = isAiRunning ? "true" : "false";

        // Click handler: Mở drawer
        el.addEventListener("click", (e) => {
          if (isPickingLocationRef.current) return;
          e.stopPropagation();
          closeHoverStream();
          onSelectNode(edgeId);
        });

        // Hover Stream Handler: mouseenter (debounce 150ms)
        el.addEventListener("mouseenter", () => {
          if (isPickingLocationRef.current) return;

          if (hoverTimerRef.current !== null) {
            window.clearTimeout(hoverTimerRef.current);
          }

          hoverTimerRef.current = window.setTimeout(() => {
            if (!mapRef.current) return;
            closeHoverStream();

            currentHoverEdgeIdRef.current = edgeId;
            const isRunning = el.dataset.aiRunning === "true";

            const popupContainer = document.createElement("div");
            popupContainer.className = "camera-live-box";

            if (isRunning) {
              // Host MediaMTX: suy ra từ domain hiện tại của trình duyệt hoặc IP mạng LAN
              const streamHost = window.location.hostname || "localhost";
              const webrtcUrl = `http://${streamHost}:8889/live/${edgeId}/`;

              popupContainer.innerHTML = `
                <div class="camera-live-header">
                  <div class="camera-live-title">
                    <span class="camera-live-dot"></span>
                    <span>LIVE CAMERA CSI (AI DETECTION)</span>
                  </div>
                  <span class="camera-live-edge">${props.name || edgeId}</span>
                </div>
                <div class="camera-live-media" id="live-stream-media-${edgeId}">
                  <iframe
                    src="${webrtcUrl}"
                    allow="autoplay; fullscreen"
                    style="width: 100%; height: 100%; border: 0; pointer-events: none;"
                    title="Camera Live Stream"
                  ></iframe>
                </div>
                <div class="camera-live-footer">
                  <span>MediaMTX WebRTC (Tức thì 0ms)</span>
                  <span>Rời chuột để tắt</span>
                </div>
              `;
            } else {
              popupContainer.innerHTML = `
                <div class="camera-live-header" style="background: #1e293b;">
                  <div class="camera-live-title" style="color: #cbd5e1;">
                    <span class="camera-live-dot" style="background-color: #f59e0b; box-shadow: 0 0 8px #f59e0b;"></span>
                    <span>CAMERA ĐANG CHỜ</span>
                  </div>
                  <span class="camera-live-edge">${props.name || edgeId}</span>
                </div>
                <div class="camera-live-media" style="display: flex; flex-direction: column; align-items: center; justify-content: center; background: #0f172a; padding: 24px 16px; text-align: center; color: #94a3b8; min-height: 180px;">
                  <div style="width: 44px; height: 44px; border-radius: 50%; background: rgba(245, 158, 11, 0.15); display: flex; align-items: center; justify-content: center; margin-bottom: 10px; color: #f59e0b; font-size: 22px;">
                    📷
                  </div>
                  <div style="font-weight: 700; font-size: 13px; color: #f1f5f9; margin-bottom: 4px;">
                    Hiện tại camera chưa bật
                  </div>
                  <div style="font-size: 11px; line-height: 1.4; color: #94a3b8; max-width: 260px;">
                    Nhấp vào camera để mở Bảng điều khiển và kích hoạt AI Pipeline
                  </div>
                </div>
                <div class="camera-live-footer" style="background: #1e293b; border-top: 1px solid #334155;">
                  <span style="color: #f59e0b; font-weight: 600;">● Chế độ chờ (Standby)</span>
                  <span>Rời chuột để tắt</span>
                </div>
              `;
            }

            const popup = new maplibregl.Popup({
              closeButton: false,
              closeOnClick: false,
              className: "camera-live-popup-wrapper",
              offset: 20,
              maxWidth: "460px"
            })
              .setLngLat(coords)
              .setDOMContent(popupContainer)
              .addTo(mapRef.current);

            hoverPopupRef.current = popup;
          }, 150);
        });

        // Hover Stream Handler: mouseleave tắt popup
        el.addEventListener("mouseleave", () => {
          if (hoverTimerRef.current !== null) {
            window.clearTimeout(hoverTimerRef.current);
            hoverTimerRef.current = null;
          }
          if (currentHoverEdgeIdRef.current === edgeId) {
            closeHoverStream();
          }
        });

        const marker = new maplibregl.Marker({ element: el, anchor: "center" })
          .setLngLat(coords)
          .addTo(map);

        markersMapRef.current.set(edgeId, {
          marker,
          element: el,
          ring,
          core,
          badge,
          cone,
          coords,
          edgeId
        });
      }
    });

    // Thu dọn các marker của node không còn tồn tại
    markersMapRef.current.forEach((entry, edgeId) => {
      if (!currentEdgeIds.has(edgeId)) {
        entry.marker.remove();
        markersMapRef.current.delete(edgeId);
        if (currentHoverEdgeIdRef.current === edgeId) {
          closeHoverStream();
        }
      }
    });
  }, [nodesGeoJSON, selectedNodeId, layersConfig.nodes, layersConfig.fovCones]);

  // Handle map click for picking coordinates
  useEffect(() => {
    if (!mapRef.current) return;
    const map = mapRef.current;

    const handleMapClick = (e: maplibregl.MapMouseEvent) => {
      if (isPickingLocation && onLocationPicked) {
        onLocationPicked(e.lngLat.lng, e.lngLat.lat);
      }
    };

    map.on("click", handleMapClick);
    map.getCanvas().style.cursor = isPickingLocation ? "crosshair" : "";

    return () => {
      map.off("click", handleMapClick);
    };
  }, [isPickingLocation, onLocationPicked]);

  return <div ref={mapContainer} className="w-full h-screen relative bg-slate-100 outline-none" />;
};
