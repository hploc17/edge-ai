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
