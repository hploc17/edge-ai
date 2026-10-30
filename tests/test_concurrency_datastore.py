import concurrent.futures
import threading
import time
from webgis.backend.services.data_store import DataStore, normalize_counts_by_class


def test_normalize_counts_by_class():
    counts = {"motorbike": 5, "bike": 2, "car": 3, "van": 1}
    norm = normalize_counts_by_class(counts)
    assert norm["motorcycle"] == 7
    assert norm["car"] == 3
    assert norm["truck"] == 1


def test_datastore_thread_safety():
    store = DataStore()
    edge_id = "test-node-concurrency"
    seg_id = "test-seg-concurrency"

    # Seed test node and segment
    store.upsert_segment({
        "segment_id": seg_id,
        "name": "Test Segment",
        "road_length_m": 250.0,
        "lane_count": 2,
    })
    store.upsert_node({
        "edge_id": edge_id,
        "segment_id": seg_id,
        "name": "Test Node",
        "latitude": 21.0,
        "longitude": 105.8,
    })

    # Simulate 20 concurrent threads sending telemetry simultaneously
    num_threads = 20
    errors = []

    def send_telemetry(idx):
        try:
            payload = {
                "segment_id": seg_id,
                "current_vehicle_count": idx,
                "avg_speed_kmh": 25.0 + (idx % 10),
                "congestion_score": idx * 3,
                "traffic_status": "SLOW" if idx > 10 else "FREE",
                "counts_by_class": {"motorbike": idx, "car": 2},
                "edge_metrics": {
                    "cpu_percent": 35.0,
                    "gpu_percent": 50.0,
                    "ram_percent": 45.0,
                    "temperature_c": 48.5,
                    "fps": 28.5,
                }
            }
            store.update_telemetry(edge_id, payload)
            # Also concurrently read live states
            states = store.get_live_states()
            assert edge_id in states
        except Exception as e:
            errors.append(str(e))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(send_telemetry, i) for i in range(num_threads)]
        concurrent.futures.wait(futures)

    assert len(errors) == 0, "Concurrent telemetry updates raised errors: %s" % errors

    # Check that segment was correctly updated
    seg = store.get_segment(seg_id)
    assert seg is not None
    assert seg["traffic_status"] in ("FREE", "SLOW", "CONGESTED")
    assert seg["traffic_color"] in ("#10B981", "#F59E0B", "#EF4444")


def test_mark_node_telemetry_stale():
    store = DataStore()
    edge_id = "test-node-stale"
    seg_id = "test-seg-stale"

    store.upsert_segment({
        "segment_id": seg_id,
        "name": "Stale Test Segment",
        "road_length_m": 200.0,
        "lane_count": 2,
    })
    store.upsert_node({
        "edge_id": edge_id,
        "segment_id": seg_id,
        "name": "Stale Test Node",
        "latitude": 21.0,
        "longitude": 105.8,
    })

    # 1. Update telemetry with congested state
    store.update_telemetry(edge_id, {
        "segment_id": seg_id,
        "current_vehicle_count": 35,
        "avg_speed_kmh": 8.5,
        "congestion_score": 85,
        "traffic_status": "CONGESTED",
        "counts_by_class": {"motorbike": 25, "car": 10},
    })

    node = store.get_node(edge_id)
    assert node["data_status"] == "live"
    assert node["traffic_status"] == "CONGESTED"
    assert node["congestion_score"] == 85
    assert node["last_telemetry_at"] is not None

    seg = store.get_segment(seg_id)
    assert seg["traffic_status"] == "CONGESTED"
    assert seg["traffic_color"] == "#EF4444"

    # 2. Mark stale (e.g. pipeline stopped or telemetry timeout)
    store.mark_node_telemetry_stale(edge_id)

    node_stale = store.get_node(edge_id)
    assert node_stale["data_status"] == "stale"
    assert node_stale["traffic_status"] == "STALE"
    assert node_stale["congestion_score"] == 0
    assert node_stale["current_vehicle_count"] == 0

    seg_stale = store.get_segment(seg_id)
    assert seg_stale["traffic_status"] == "STALE"
    assert seg_stale["congestion_score"] == 0
    assert seg_stale["traffic_color"] == "#9CA3AF"

    # 3. Test update_pipeline_status(running=False) marks stale
    # Re-feed telemetry
    store.update_telemetry(edge_id, {
        "segment_id": seg_id,
        "current_vehicle_count": 10,
        "congestion_score": 30,
        "traffic_status": "FREE",
    })
    assert store.get_node(edge_id)["data_status"] == "live"

    # Stop pipeline
    store.update_pipeline_status(edge_id, running=False)
    node_stopped = store.get_node(edge_id)
    assert node_stopped["pipeline_running"] is False
    assert node_stopped["data_status"] in ("stale", "idle")
    assert node_stopped["traffic_status"] == "STALE"
    assert node_stopped["congestion_score"] == 0

