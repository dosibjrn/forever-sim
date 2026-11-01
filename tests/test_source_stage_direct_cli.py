"""Direct source-stage entrypoints must resolve the canonical source modules.

These are executable CLI checks, not mocked GameIR or a P1/P2 gate.
The full staged SQLite ingestion is verified separately with real source data.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "wf292_ingest_verified_detail_headers_sqlite",
    "wf293_ingest_source_effect_atoms_sqlite",
    "wf315_source_index_typed_runtime_batch",
    "wf317_stage_canonical_verified_effects",
)


class SourceStageEntrypointTest(unittest.TestCase):
    def test_direct_file_and_module_invocation(self):
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        for name in SCRIPTS:
            for command in (
                [sys.executable, str(ROOT / "tools" / (name + ".py")), "--help"],
                [sys.executable, "-m", "tools." + name, "--help"],
            ):
                with self.subTest(name=name, mode=command[1]):
                    result = subprocess.run(
                        command, cwd=ROOT, env=env, text=True,
                        capture_output=True, timeout=30, check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("--help", result.stdout)


if __name__ == "__main__":
    unittest.main()
