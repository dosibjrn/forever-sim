"""G50b: the production generic decision path must not import legacy scorers.

Run in a fresh interpreter so a warm pytest process cannot conceal eager
imports in sys.modules. The legacy/oracle adapter remains available explicitly.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _isolated_python(script: str, *, timeout: int = 65) -> subprocess.CompletedProcess:
    env = dict(os.environ, WOW_DISABLE_LEGACY_DECISIONS="1")
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)], cwd=PROJECT_ROOT,
        env=env, text=True, capture_output=True, timeout=timeout,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    return proc


def test_native_generic_http_payload_never_imports_legacy_scorers():
    _isolated_python('''
        import importlib.abc
        import sys

        # Legacy-only scoring/search, rehydration and projection are forbidden
        # even as imports; not merely forbidden as calls. The native generic
        # route DP and shared ClassModel are intentionally NOT on this list.
        FORBIDDEN = {
            "src.v2.decision_stat_weights",
            "src.v2.stat_weight_model",
            "src.v2.legacy_decision_projection",
            "src.v2.mature_decision_artifacts",
        }
        LEGACY_CLASS_SUFFIXES = (".engine", ".mechanics")
        def forbidden(name):
            return (name in FORBIDDEN or
                    (name.startswith("src.rulesets.forever.classes.") and
                     name.endswith(LEGACY_CLASS_SUFFIXES)))

        class Guard(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if forbidden(fullname):
                    raise AssertionError("G50b forbidden legacy scorer import: " + fullname)
                return None

        assert not any(forbidden(name) for name in sys.modules)
        sys.meta_path.insert(0, Guard())
        from src.v2.decision_dashboard import build_decision_payload
        assert not any(forbidden(name) for name in sys.modules)
        result = build_decision_payload(
            selected_level=10, class_name="druid", backend_id="generic"
        )
        assert result["active_backend"] == "generic"
        assert result["backend_selection"]["legacy_fallback"] is False
        assert len(result["decisions"]) == 7
        assert len(result["native_route_decisions"]) == 26
        assert result["generic_routes"]["legacy_fallback"] is False
        assert not any(forbidden(name) for name in sys.modules)
    ''')


def test_legacy_package_facades_still_export_engine_symbols_on_demand():
    _isolated_python('''
        import sys
        from src.rulesets.forever.classes import druid, hunter
        assert "src.rulesets.forever.classes.druid.engine" not in sys.modules
        assert "src.rulesets.forever.classes.hunter.engine" not in sys.modules
        from src.rulesets.forever.classes.druid import rage
        from src.rulesets.forever.classes.hunter import pets
        assert rage is not None and pets is not None
        assert "src.rulesets.forever.classes.druid.engine" not in sys.modules
        assert "src.rulesets.forever.classes.hunter.engine" not in sys.modules
        assert druid.RULESET == "forever"
        assert hunter.RULESET == "forever"
        assert callable(druid.experimental_level_score)
        assert callable(hunter.experimental_level_score)
        assert "src.rulesets.forever.classes.druid.engine" in sys.modules
        assert "src.rulesets.forever.classes.hunter.engine" in sys.modules
        assert "experimental_level_score" in druid.__all__
        assert "experimental_level_score" in hunter.__all__
    ''')


def test_legacy_star_exports_and_explicit_adapter_remain_available():
    _isolated_python('''
        from src.rulesets.forever.classes.druid import *
        assert RULESET == "forever" and callable(experimental_level_score)
        from src.rulesets.forever.classes.hunter import *
        assert RULESET == "forever" and callable(marginal_stat_weights)
        from src.v2.backend_decision import DecisionRecord
        record = DecisionRecord.from_legacy_route_row(
            class_name="druid", target_level=10, route_name="balance",
            row={"level": 10, "score_s_per_100": 1900.0, "policy": "Wrath"},
        )
        assert record.backend["id"] == "legacy"
        assert record.compatibility["legacy_route_row"]["level"] == 10
    ''')
