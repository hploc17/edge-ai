export type TrafficStatus = "FREE" | "SLOW" | "CONGESTED" | "STALE" | "UNKNOWN";

export interface TrafficStatusInfo {
  status: TrafficStatus;
  label: string;
  color: string;
  background: string;
  textColor: string;
  chipClassName: string;
}

const STATUS_INFO: Record<TrafficStatus, TrafficStatusInfo> = {
  FREE: { status: "FREE", label: "Thông thoáng", color: "#16A34A", background: "#DCFCE7", textColor: "#166534", chipClassName: "bg-traffic-free-bg text-traffic-free-text border-traffic-free" },
  SLOW: { status: "SLOW", label: "Chậm", color: "#F59E0B", background: "#FEF3C7", textColor: "#92400E", chipClassName: "bg-traffic-slow-bg text-traffic-slow-text border-traffic-slow" },
  CONGESTED: { status: "CONGESTED", label: "Ùn tắc", color: "#DC2626", background: "#FEE2E2", textColor: "#991B1B", chipClassName: "bg-traffic-congested-bg text-traffic-congested-text border-traffic-congested" },
  STALE: { status: "STALE", label: "Mất dữ liệu", color: "#94A3B8", background: "#F1F5F9", textColor: "#475569", chipClassName: "bg-traffic-stale-bg text-traffic-stale-text border-traffic-stale" },
  UNKNOWN: { status: "UNKNOWN", label: "Chờ dữ liệu", color: "#94A3B8", background: "#F1F5F9", textColor: "#475569", chipClassName: "bg-traffic-stale-bg text-traffic-stale-text border-traffic-stale" }
};

export const TRAFFIC_STATUS_COLORS = {
  free: STATUS_INFO.FREE.color,
  slow: STATUS_INFO.SLOW.color,
  congested: STATUS_INFO.CONGESTED.color,
  stale: STATUS_INFO.STALE.color
} as const;

export function getTrafficStatus(status?: string, score?: number | null, lastUpdated?: string | number, now = Date.now(), algorithmVersion?: string): TrafficStatusInfo {
  if (lastUpdated && now - new Date(lastUpdated).getTime() > 30_000) return STATUS_INFO.STALE;
  if (status && Object.prototype.hasOwnProperty.call(STATUS_INFO, status)) return STATUS_INFO[status as TrafficStatus];
  if (status === "idle" || score == null || !Number.isFinite(score)) return STATUS_INFO.UNKNOWN;
  if (score >= (algorithmVersion === "v3" ? 75 : 65)) return STATUS_INFO.CONGESTED;
  if (score >= (algorithmVersion === "v3" ? 50 : 35)) return STATUS_INFO.SLOW;
  return STATUS_INFO.FREE;
}

export const trafficStatusFromScore = (score?: number | null, algorithmVersion?: string) => getTrafficStatus(undefined, score, undefined, Date.now(), algorithmVersion);

// Copy only fields supplied by the producer; explicit null clears old readings.
export function trafficTelemetry(source: Record<string, any>): Record<string, any> {
  const keys = ["algorithm_version", "method", "spi", "spi_level", "speed_ratio_percent", "speed_reduction_index", "status_pending", "status_pending_seconds", "status_confirm_seconds", "reference_speed_kmh", "free_flow_speed_kmh", "minimum_valid_tracks", "valid_speed_tracks", "median_speed_kmh", "stopped_ratio", "pce", "data_quality", "reason", "congestion_score", "raw_traffic_state", "stable_traffic_state", "spi_thresholds", "score_thresholds", "hcm_los_proxy", "hcm_los_proxy_is_official", "hcm_los_proxy_thresholds", "spi_signalized", "traffic_context"];
  keys.push("raw_traffic_status", "representative_speed_kmh", "representative_speed_method", "forecast");
  return Object.fromEntries(keys.filter(key => source[key] !== undefined).map(key => [key, source[key]]));
}
