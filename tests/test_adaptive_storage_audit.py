import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from adaptive.live_runtime import Runtime

class StorageAudit(unittest.TestCase):
    def runtime(self, path):
        r = Runtime.__new__(Runtime)
        r.experiment_path = path
        r.experiment_since = None
        r.experiment_initial = None
        r.experiment_saved = False
        r.experiment_error = None
        r.experiment_counts_saved = [0]*len(r.EXPERIMENT_LEVELS)
        r.experiment_watermark = 0
        r.observer = SimpleNamespace(rows=[])
        r.load_experiment()
        return r

    def test_migration_restart_and_eviction(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/".adaptive-experiment.json"
            since = time.time()-100
            path.write_text(json.dumps({"schema":1,"session":{"since":since,"initial":["eco",False]}}))
            r = self.runtime(path)
            row = {"context":["experiment","eco",False],"start":{"at":since+1}}
            r.observer.rows = [row]
            r.checkpoint_experiment_progress()
            self.assertEqual(r.experiment_counts()[0],1)
            r = self.runtime(path)
            self.assertEqual(r.experiment_counts()[0],1)
            r.observer.rows = [row]
            self.assertEqual(r.experiment_counts()[0],1)
            r.observer.rows = []
            self.assertEqual(r.experiment_counts()[0],1)
            r.observer.rows = [{"context":["experiment","eco",False],"start":{"at":since+i}} for i in range(2,7)]
            r.checkpoint_experiment_progress()
            self.assertEqual(self.runtime(path).experiment_counts()[0],3)

    def test_diagnostics_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/".adaptive-test.json"
            path.write_text("test")
            before = path.stat().st_mtime_ns
            r = self.runtime(Path(d)/".adaptive-experiment.json")
            data = r.storage_diagnostics()
            self.assertEqual(data["state_files"][path.name],4)
            self.assertGreater(data["disk_total_bytes"],0)
            self.assertEqual(path.stat().st_mtime_ns,before)
            self.assertEqual(list(Path(d).iterdir()),[path])

if __name__ == "__main__":
    unittest.main()
