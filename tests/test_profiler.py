#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import shutil
import tempfile
import time
import unittest

from measure_jetson import (
    JetsonPerformanceProfiler,
    describe,
    extract_phase_from_cmdline,
    is_process_alive,
    parse_tegrastats,
)


class TestProfiler(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_profiler_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_tegrastats(self):
        line = "RAM 1500/3964MB (lfb 210x4MB) SWAP 0/1982MB (cached 0MB) CPU [15%@1479,12%@1479,18%@1479,10%@1479] EMC_FREQ 0% GR3D_FREQ 45% PLL@38C CPU@39.5C thermal@39C AO@36C GPU@38.5C POM_5V_IN 3200/3200"
        data = parse_tegrastats(line)
        self.assertEqual(data.get("ram_used_mb"), 1500)
        self.assertEqual(data.get("ram_total_mb"), 3964)
        self.assertEqual(data.get("gpu_pct"), 45.0)
        self.assertAlmostEqual(data.get("cpu_avg_pct"), 13.75, places=2)
        self.assertEqual(data.get("cpu_max_core_pct"), 18.0)
        self.assertEqual(data.get("temp_cpu_c"), 39.5)
        self.assertEqual(data.get("temp_gpu_c"), 38.5)
        self.assertEqual(data.get("power_in_mw"), 3200)

    def test_describe_statistics(self):
        vals = [10.0, 20.0, 30.0]
        res = describe(vals)
        self.assertEqual(res["n"], 3)
        self.assertEqual(res["mean"], 20.0)
        self.assertEqual(res["min"], 10.0)
        self.assertEqual(res["max"], 30.0)

        empty_res = describe([])
        self.assertIsNone(empty_res)

    def test_profiler_lifecycle_and_output(self):
        fps_val = [25.0]
        profiler = JetsonPerformanceProfiler(
            phase="test_run",
            duration=1,
            warmup=0,
            interval=0.2,
            out_dir=self.temp_dir,
            no_tegrastats=True,
            get_fps_fn=lambda: fps_val[0]
        )
        run_dir = profiler.start()
        self.assertTrue(profiler.is_running())
        self.assertTrue(os.path.isdir(run_dir))

        time.sleep(1.2)
        profiler.stop()
        self.assertFalse(profiler.is_running())

        metrics_csv = os.path.join(run_dir, "metrics.csv")
        summary_json = os.path.join(run_dir, "summary.json")
        summary_md = os.path.join(run_dir, "summary.md")

        self.assertTrue(os.path.isfile(metrics_csv))
        self.assertTrue(os.path.isfile(summary_json))
        self.assertTrue(os.path.isfile(summary_md))

        with open(metrics_csv, "r", encoding="utf-8") as f:
            lines = f.readlines()
            self.assertGreater(len(lines), 1)  # Header + at least 1 sample

        with open(summary_md, "r", encoding="utf-8") as f:
            md_content = f.read()
            self.assertIn("Ket qua do hieu nang", md_content)
            self.assertIn("FPS chuoi phan tich", md_content)

    def test_extract_phase_from_cmdline(self):
        parts1 = ["python3", "main.py", "--source", "Video/le_duc_tho.mp4", "--algo-version", "v3", "--no-display"]
        self.assertEqual(extract_phase_from_cmdline(parts1), "le_duc_tho_v3")

        parts2 = ["python3", "main.py", "-s", "csi", "--no-display"]
        self.assertEqual(extract_phase_from_cmdline(parts2), "csi")

        parts3 = ["python3", "main.py", "--source=videos/sample_01.mkv"]
        self.assertEqual(extract_phase_from_cmdline(parts3), "sample_01")

        parts4 = ["python3", "main.py"]
        self.assertEqual(extract_phase_from_cmdline(parts4), "pipeline_run")

    def test_is_process_alive(self):
        self.assertTrue(is_process_alive(os.getpid()))
        self.assertFalse(is_process_alive(9999999))


if __name__ == "__main__":
    unittest.main()
