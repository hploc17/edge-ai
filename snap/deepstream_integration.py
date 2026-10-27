"""Attach to an EXISTING RGBA nvdsosd source pad; never create a camera source.

get_metrics(frame_meta) must return metrics for that source/frame from your main.
Do not attach if your main already calls submit_frame in another snapshot probe.
"""
import logging
import time


def attach_snapshot_probe(osd, service, get_metrics, source_id=0):
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    import pyds
    if osd is None:
        raise ValueError("Existing RGBA/OSD branch required even with --no-display")
    pad = osd.get_static_pad("src")
    if pad is None:
        raise ValueError("nvdsosd src pad missing")
    last_warning = [0.0]

    def probe(current_pad, info):
        buffer = info.get_buffer()
        if not buffer:
            return Gst.PadProbeReturn.OK
        batch = pyds.gst_buffer_get_nvds_batch_meta(hash(buffer))
        if not batch:
            return Gst.PadProbeReturn.OK
        cursor = batch.frame_meta_list
        while cursor:
            frame = pyds.NvDsFrameMeta.cast(cursor.data)
            if int(frame.source_id) == source_id:
                try:
                    metrics = get_metrics(frame)
                    if metrics is not None and service.update_telemetry(metrics):
                        if service.should_map_frame(metrics.get("traffic_status")):
                            caps = current_pad.get_current_caps()
                            if caps is None or caps.get_structure(0).get_string("format") != "RGBA":
                                raise RuntimeError("Snapshot pad must negotiate RGBA, not NV12")
                            # DS 6.0.1 Jetson supports RGBA mapping. Own the copy before returning.
                            mapped = False
                            try:
                                surface = pyds.get_nvds_buf_surface(hash(buffer), int(frame.batch_id))
                                mapped = True
                                service.submit_frame(surface, metrics, color_format="RGBA")
                            finally:
                                # Newer bindings expose explicit unmap; older 6.0.1 may not.
                                if mapped and hasattr(pyds, "unmap_nvds_buf_surface"):
                                    pyds.unmap_nvds_buf_surface(hash(buffer), int(frame.batch_id))
                except Exception as error:
                    if time.monotonic() - last_warning[0] > 5:
                        logging.warning("Snapshot probe skipped (%s); check RGBA/source adapter", type(error).__name__)
                        last_warning[0] = time.monotonic()
            try:
                cursor = cursor.next
            except StopIteration:
                break
        return Gst.PadProbeReturn.OK

    probe_id = pad.add_probe(Gst.PadProbeType.BUFFER, probe)
    return pad, probe_id
