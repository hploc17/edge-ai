import React, { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONFeatureCollection } from "../../types/gis";

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

// Calculate optical viewport padding to center node avoiding UI panels (Drawer & Navbar)
const getCameraPadding = (isDrawerOpen: boolean = true) => {
  if (!isDrawerOpen) {
    return { top: 0, right: 0, bottom: 0, left: 0 };
  }
  const isMobile = typeof window !== "undefined" && window.innerWidth < 640;
  if (isMobile) {
    return { top: 80, right: 20, bottom: 380, left: 20 };
  }
  return {
    top: 80,    // Top Navbar height (64px) + safe buffer
    right: 420, // Drawer width (384px) + margin (12px) + safe breathing space (24px)
    bottom: 40,
    left: 40
  };
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
  const markersRef = useRef<maplibregl.Marker[]>([]);
  const activePopupRef = useRef<maplibregl.Popup | null>(null);
  const segmentsGeoJSONRef = useRef(segmentsGeoJSON);
  segmentsGeoJSONRef.current = segmentsGeoJSON;
  const nodesGeoJSONRef = useRef(nodesGeoJSON);
  nodesGeoJSONRef.current = nodesGeoJSON;
  const isPickingLocationRef = useRef(isPickingLocation);
  isPickingLocationRef.current = isPickingLocation;

  const addTrafficLayers = (map: maplibregl.Map) => {
    const geoData = segmentsGeoJSONRef.current || segmentsGeoJSON || { type: "FeatureCollection", features: [] };
    const existingSource = map.getSource("traffic-segments") as maplibregl.GeoJSONSource;

    if (!existingSource) {
      map.addSource("traffic-segments", {
        type: "geojson",
        data: geoData
      });
    } else {
      existingSource.setData(geoData);
    }

    // Precise Real-World Meter-to-Pixel scaling formula at Hanoi's latitude (21.0 deg N)
    // 1 meter = 2^zoom / 146146 screen pixels
    // width_px = road_width_m * (2^zoom / 146146) * multiplier
    const meterToPixel = (multiplier: number = 1.0) => [
      "interpolate", ["exponential", 2], ["zoom"],
      13, ["*", ["coalesce", ["get", "road_width_m"], 22], (8192 / 146146) * multiplier],
      14, ["*", ["coalesce", ["get", "road_width_m"], 22], (16384 / 146146) * multiplier],
      15, ["*", ["coalesce", ["get", "road_width_m"], 22], (32768 / 146146) * multiplier],
      16, ["*", ["coalesce", ["get", "road_width_m"], 22], (65536 / 146146) * multiplier],
      17, ["*", ["coalesce", ["get", "road_width_m"], 22], (131072 / 146146) * multiplier],
      18, ["*", ["coalesce", ["get", "road_width_m"], 22], (262144 / 146146) * multiplier],
      19, ["*", ["coalesce", ["get", "road_width_m"], 22], (524288 / 146146) * multiplier],
      20, ["*", ["coalesce", ["get", "road_width_m"], 22], (1048576 / 146146) * multiplier]
    ];

    // 1. Soft subtle ambient glow (khống chế không cho lấn ra ngoài vỉa hè)
    if (!map.getLayer("traffic-segments-glow")) {
      map.addLayer({
        id: "traffic-segments-glow",
        type: "line",
        source: "traffic-segments",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": ["get", "traffic_color"],
          "line-width": meterToPixel(1.12) as any,
          "line-opacity": 0.35,
          "line-blur": 2
        }
      });
    }

    // 2. High-contrast White Casing (Viền trắng ôm sát mép đường)
    if (!map.getLayer("traffic-segments-casing")) {
      map.addLayer({
        id: "traffic-segments-casing",
        type: "line",
        source: "traffic-segments",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": "#ffffff",
          "line-width": meterToPixel(1.04) as any,
          "line-opacity": 0.95
        }
      });
    }

    // 3. Solid Traffic Heat Core (Vừa khít 100% trong lòng đường 1 chiều xe chạy)
    if (!map.getLayer("traffic-segments-core")) {
      map.addLayer({
        id: "traffic-segments-core",
        type: "line",
        source: "traffic-segments",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": ["get", "traffic_color"],
          "line-width": meterToPixel(0.96) as any,
          "line-opacity": 0.92
        }
      });
    }

    // 4. Inner Flow Dashes (Vạch dẫn hướng phân làn trung tâm)
    if (!map.getLayer("traffic-segments-dash")) {
      map.addLayer({
        id: "traffic-segments-dash",
        type: "line",
        source: "traffic-segments",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": "#ffffff",
          "line-width": 2,
          "line-opacity": 0.9,
          "line-dasharray": [2, 4]
        }
      });
    }
  };

  // Initialize Map
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: BASEMAP_STYLES[basemap] || BASEMAP_STYLES.google,
      center: [105.792350, 21.000650], // Tòa nhà HH2 Bắc Hà, Đường Tố Hữu, Hà Nội
      zoom: 16.8,
      pitch: 0,
      bearing: 0,
      attributionControl: false
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

    map.on("load", () => {
      addTrafficLayers(map);

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
          const statusText = p.traffic_status === "CONGESTED" ? "ÙN TẮC" : (p.traffic_status === "SLOW" ? "ĐÔNG XE" : "THÔNG THOÁNG");
          
          // Close existing popup if any
          if (activePopupRef.current) {
            activePopupRef.current.remove();
            activePopupRef.current = null;
          }

          const popup = new maplibregl.Popup({ closeButton: true, closeOnClick: true, className: "road-popup" })
            .setLngLat(e.lngLat)
            .setHTML(`
              <div style="font-family: Inter, sans-serif; padding: 6px 4px; color: #1e293b; min-width: 220px;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px;">
                  <strong style="font-size: 13px; color: #0f172a;">${p.road_name}</strong>
                  <span style="font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 6px; background: ${p.traffic_color}25; color: ${p.traffic_color};">
                    ${statusText}
                  </span>
                </div>
                <div style="font-size: 11px; line-height: 1.6; color: #334155; background: #f8fafc; padding: 8px; border-radius: 8px; border: 1px solid #e2e8f0;">
                  <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
                    <span style="color: #64748b;">📏 Chiều dài thực tế:</span>
                    <b style="color: #059669; font-family: monospace;">${p.road_length_m || 450} m</b>
                  </div>
                  <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
                    <span style="color: #64748b;">📐 Chiều rộng mặt đường:</span>
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
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Handle Basemap Switch
  useEffect(() => {
    if (!mapRef.current) return;
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
      addTrafficLayers(map);
    } else {
      map.once("styledata", () => {
        addTrafficLayers(map);
      });
    }
  }, [segmentsGeoJSON]);

  // Toggle Segments visibility
  useEffect(() => {
    if (!mapRef.current) return;
    const map = mapRef.current;
    const vis = layersConfig.segments ? "visible" : "none";
    if (map.getLayer("traffic-segments-core")) map.setLayoutProperty("traffic-segments-core", "visibility", vis);
    if (map.getLayer("traffic-segments-glow")) map.setLayoutProperty("traffic-segments-glow", "visibility", vis);
    if (map.getLayer("traffic-segments-casing")) map.setLayoutProperty("traffic-segments-casing", "visibility", vis);
    if (map.getLayer("traffic-segments-dash")) map.setLayoutProperty("traffic-segments-dash", "visibility", vis);
  }, [layersConfig.segments]);

  // Smoothly Fly and Center Selected Node on Map with Camera Padding (Anti-Jitter)
  // IMPORTANT: nodesGeoJSON is intentionally accessed via nodesGeoJSONRef.current to avoid
  // re-triggering flyTo every few seconds on WebSocket telemetry updates!
  useEffect(() => {
    if (!mapRef.current) return;
    const map = mapRef.current;

    // When drawer closes (selectedNodeId becomes null), smoothly ease padding back to zero
    if (!selectedNodeId) {
      map.easeTo({
        padding: { top: 0, right: 0, bottom: 0, left: 0 },
        duration: 400
      });
      return;
    }

    // Automatically close any open road segment popups so they don't cover the node
    if (activePopupRef.current) {
      activePopupRef.current.remove();
      activePopupRef.current = null;
    }

    const geoData = nodesGeoJSONRef.current;
    if (!geoData) return;

    const feature = geoData.features.find((f) => f.properties.edge_id === selectedNodeId);
    if (!feature || !feature.geometry || !feature.geometry.coordinates) return;

    const coords = feature.geometry.coordinates as [number, number];
    const currentZoom = map.getZoom();
    const targetZoom = Math.max(currentZoom, 17.2);

    map.flyTo({
      center: coords,
      zoom: targetZoom,
      padding: getCameraPadding(true),
      duration: 1200,
      essential: true
    });
  }, [selectedNodeId, selectNodeTrigger]);

  // Render & Update Pulsing Dot Markers for Nodes
  useEffect(() => {
    if (!mapRef.current) return;
    const map = mapRef.current;

    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];

    if (!layersConfig.nodes || !nodesGeoJSON) return;

    nodesGeoJSON.features.forEach((feature) => {
      const coords = feature.geometry.coordinates as [number, number];
      const props = feature.properties;
      const isSelected = selectedNodeId === props.edge_id;

      const el = document.createElement("div");
      el.className = isSelected ? "pulsing-marker selected-node-marker" : "pulsing-marker";
      el.style.zIndex = isSelected ? "50" : "10";
      el.style.setProperty("--marker-glow-color", props.marker_color);

      // Pulsing outer ring
      const ring = document.createElement("div");
      ring.className = "pulsing-marker-ring";
      ring.style.backgroundColor = props.marker_color;

      // Core dot
      const core = document.createElement("div");
      core.className = "pulsing-marker-core";
      core.style.backgroundColor = props.marker_color;
      if (isSelected) {
        core.style.boxShadow = `0 0 0 3px rgba(255, 255, 255, 0.9), 0 0 24px 8px ${props.marker_color}`;
        core.style.transform = "scale(1.55)";
      }

      el.appendChild(ring);
      el.appendChild(core);

      // Floating Name Badge above Selected Marker
      if (isSelected) {
        const badge = document.createElement("div");
        badge.className = "node-floating-badge";
        badge.innerHTML = `
          <span class="node-badge-dot" style="background-color: ${props.marker_color};"></span>
          <span class="node-badge-text">${props.name || props.edge_id}</span>
        `;
        el.appendChild(badge);
      }

      // Camera FOV cone / orientation indicator
      if (layersConfig.fovCones && props.heading !== undefined) {
        const cone = document.createElement("div");
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

      el.addEventListener("click", (e) => {
        // If user is in location picking mode, let the map click handler handle it
        if (isPickingLocationRef.current) {
          return;
        }
        e.stopPropagation();
        onSelectNode(props.edge_id);
      });

      const marker = new maplibregl.Marker({ element: el, anchor: "center" })
        .setLngLat(coords)
        .addTo(map);

      markersRef.current.push(marker);
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
