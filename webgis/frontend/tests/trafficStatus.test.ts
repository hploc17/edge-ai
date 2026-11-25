import assert from "node:assert/strict";
import { test } from "node:test";
import { getTrafficStatus, trafficStatusFromScore, trafficTelemetry } from "../src/lib/trafficStatus.ts";

test("producer status wins over instantaneous score, including unknown and stale", () => {
  for (const status of ["FREE", "SLOW", "CONGESTED", "UNKNOWN", "STALE"]) {
    assert.equal(getTrafficStatus(status, 100).status, status);
    assert.equal(getTrafficStatus(status, 0).status, status);
  }
});
test("versioned fallback respects exact SPI v3 boundaries and legacy thresholds", () => {
  for (const [score, status] of [[0, "FREE"], [49.99, "FREE"], [50, "SLOW"], [74.99, "SLOW"], [75, "CONGESTED"], [100, "CONGESTED"]] as const) {
    assert.equal(trafficStatusFromScore(score, "v3").status, status);
  }
  assert.equal(trafficStatusFromScore(35).status, "SLOW");
  assert.equal(trafficStatusFromScore(65).status, "CONGESTED");
  for (const score of [null, undefined, NaN]) assert.equal(trafficStatusFromScore(score, "v3").status, "UNKNOWN");
});
test("old telemetry is stale even if producer was congested", () => {
  assert.equal(getTrafficStatus("CONGESTED", 99, 1, 31_002).status, "STALE");
});
test("additive telemetry preserves explicit null and does not erase absent fields", () => {
  const previous = { spi: 50, congestion_score: 50, status_confirm_seconds: 10 };
  const merged = { ...previous, ...trafficTelemetry({ spi: null, congestion_score: null, status_pending: false, edge_id: "ignore" }) };
  assert.deepEqual(merged, { spi: null, congestion_score: null, status_confirm_seconds: 10, status_pending: false });
});
