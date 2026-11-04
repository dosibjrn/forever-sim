"""Keep orphaned WF248/WF249 GameIR replay CLIs out of the live surface."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RETIRED_TOOLS = (
    "tools/wf248_source_legal_beam_replay.py",
    "tools/wf249_hit_cast_regen_replay.py",
)
RETIRED_IMPORT_NAMES = (
    "wf248_source_legal_beam_replay",
    "wf249_hit_cast_regen_replay",
)


def test_orphaned_gameir_replays_stay_retired():
    for relative in RETIRED_TOOLS:
        assert not (ROOT / relative).exists(), relative

    for root in (
        ROOT / "src",
        ROOT / "tools",
        ROOT / "tests",
        ROOT / "scripts",
        ROOT / "integrations",
    ):
        for path in root.rglob("*.py"):
            if path.resolve() == Path(__file__).resolve():
                continue
            source = path.read_text(encoding="utf-8")
            for name in RETIRED_IMPORT_NAMES:
                assert name not in source, f"{name} reintroduced by {path}"

    workflow_root = ROOT / ".github" / "workflows"
    for path in workflow_root.rglob("*.yml"):
        source = path.read_text(encoding="utf-8")
        for relative in RETIRED_TOOLS:
            assert relative not in source, f"{relative} reintroduced by {path}"
