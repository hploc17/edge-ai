import io
import json
import os
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from measure_jetson import TegrastatsReader, JetsonPerformanceProfiler, parse_tegrastats


SAMPLE = 'RAM 1500/3964MB CPU [15%@1479] GR3D_FREQ 45% CPU@39.5C GPU@38.5C POM_5V_IN 3200/3200\n'


class TegrastatsCaptureTests(unittest.TestCase):
    def test_failure_preserves_output_and_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Mock(stdout=io.StringIO('Permission denied\n'))
            proc.wait.return_value = 1
            proc.poll.return_value = 1
            reader = TegrastatsReader(1000, directory)
            with patch('measure_jetson.subprocess.Popen', return_value=proc):
                reader.run()
            self.assertEqual(reader.diagnostics()['status'], 'error')
            self.assertEqual(reader.returncode, 1)
            self.assertEqual(reader.snapshot(), {})
            with open(os.path.join(directory, 'tegrastats.log')) as handle:
                self.assertIn('Permission denied', handle.read())

    def test_missing_binary(self):
        reader = TegrastatsReader(1000)
        with patch('measure_jetson.subprocess.Popen', side_effect=OSError('not found')):
            reader.run()
        self.assertIn('not found', reader.error)

    def test_snapshot_expires(self):
        reader = TegrastatsReader(1000)
        reader.latest = parse_tegrastats(SAMPLE)
        reader.last_sample = time.monotonic()
        self.assertEqual(reader.snapshot()['gpu_pct'], 45)
        reader.last_sample -= 10
        self.assertEqual(reader.snapshot(), {})

    def test_profiler_writes_hardware_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = Mock()
            reader.error = None
            reader.snapshot.return_value = parse_tegrastats(SAMPLE)
            reader.diagnostics.return_value = {'status': 'collected'}
            with patch('measure_jetson.TegrastatsReader', return_value=reader):
                profiler = JetsonPerformanceProfiler(out_dir=directory, interval=0.1)
                run_dir = profiler.start()
                time.sleep(0.35)
                profiler.stop()
            with open(os.path.join(run_dir, 'summary.json')) as handle:
                summary = json.load(handle)
            self.assertEqual(summary['gpu_pct']['mean'], 45)
            self.assertEqual(summary['ram_used_mb']['mean'], 1500)
            self.assertEqual(summary['temp_cpu_c']['mean'], 39.5)
            self.assertEqual(summary['power_in_mw']['mean'], 3200)
            self.assertEqual(summary['meta']['tegrastats']['status'], 'collected')
