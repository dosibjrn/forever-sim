"""Keep historical paid native-world probes available without auto-replaying them.

These expensive source diagnostics are not M1 gate executions or a replacement
for the one-call balanced, three-mob multi-level optimizer. This is solely a
regression against accidental Actions compute/storage consumption.
"""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
LEGACY = (
    "wf-gsim-go-native-range-loop.yml",
    "wf-gsim-rust-native-world.yml",
)


def test_historical_native_world_probes_require_explicit_dispatch():
    for filename in LEGACY:
        path = ROOT / ".github/workflows" / filename
        text = path.read_text(encoding="utf-8")
        head, sep, remainder = text.partition("\non:\n")
        assert sep, f"{filename}: missing workflow event declaration"
        events, sep, jobs = remainder.partition("\npermissions:\n")
        assert sep and "\njobs:\n" in jobs, (
            f"{filename}: keep the real source-native diagnostic jobs"
        )
        declared = re.findall(r"^  ([a-z][a-z_-]*):", events, re.MULTILINE)
        assert declared == ["workflow_dispatch"], (
            f"{filename}: old source probes must never replay on push/PR/schedule"
        )
        assert "10000" in text, (
            f"{filename}: this scope guard applies to long, historical paid probes"
        )
