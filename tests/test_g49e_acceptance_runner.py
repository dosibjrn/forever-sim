"""G49e acceptance gate must not confuse a partial/blocked test with closure."""
from pathlib import Path
import subprocess
import pytest

from scripts import g49_acceptance_gate as gate
from src.version import SOFTWARE_VERSION


def row(name, status="PASS"):
    return gate.GateResult(name, status, 2, 0, 0, 0, 0, 1.2, "")


def test_g49e_report_requires_all_stages_and_zero_skips():
    assert tuple(map(int, SOFTWARE_VERSION.split("."))) >= (0, 11, 48, 182)
    assert gate.build_report([row("fast"), row("slow")])["acceptance_passed"] is False
    assert gate.build_report([row("fast"), row("http"), row("slow"), row("native", "SKIPPED")])["acceptance_passed"] is False
    assert gate.build_report([row("fast"), row("http"), row("slow"), row("native", "BLOCKED")])["acceptance_passed"] is False
    assert gate.build_report([row("fast"), row("http"), row("slow"), row("native")])["acceptance_passed"] is True


def test_g49e_junit_parser_counts_skip_as_non_pass(tmp_path):
    xml = tmp_path / "junit.xml"
    xml.write_text('<testsuites><testsuite tests="2" failures="0" errors="0" skipped="1" time="0.2">'
                   '<testcase name="good"/><testcase name="skipped"><skipped/></testcase>'
                   '</testsuite></testsuites>')
    assert gate.parse_junit(xml) == (2, 0, 0, 1, 0.2)


def test_g49e_native_strict_gate_is_not_optional(monkeypatch):
    def run(cmd, **kwargs):
        assert kwargs['env']['WOW_REQUIRE_NATIVE_BROWSER_E2E'] == '1'
        assert 'tests/test_g49d_native_browser_e2e.py' in cmd
        Path(cmd[cmd.index('--junitxml') + 1]).write_text(
            '<testsuite tests="1" failures="0" errors="0" skipped="0" time="0.4"/>')
        return subprocess.CompletedProcess(cmd, 0, '1 passed')
    monkeypatch.setattr(gate.subprocess, 'run', run)
    assert gate.run_stage('native').status == 'PASS'


def test_g49e_native_blocked_must_fail(monkeypatch):
    def run(cmd, **kwargs):
        Path(cmd[cmd.index('--junitxml') + 1]).write_text(
            '<testsuite tests="1" failures="1" errors="0" skipped="0" time="0.1"/>')
        kwargs['stdout'].write('Native browser socket blocked')
        return subprocess.CompletedProcess(cmd, 1, None)
    monkeypatch.setattr(gate.subprocess, 'run', run)
    assert gate.run_stage('native').status == 'BLOCKED'


def test_g49e_native_skip_even_exit_zero_is_not_pass(monkeypatch):
    def run(cmd, **kwargs):
        Path(cmd[cmd.index('--junitxml') + 1]).write_text(
            '<testsuite tests="1" failures="0" errors="0" skipped="1" time="0.1"/>')
        return subprocess.CompletedProcess(cmd, 0, '1 skipped')
    monkeypatch.setattr(gate.subprocess, 'run', run)
    assert gate.run_stage('native').status == 'SKIPPED'


def test_g49e_stage_timeout_is_not_pass(monkeypatch):
    def run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1)
    monkeypatch.setattr(gate.subprocess, 'run', run)
    result = gate.run_stage('slow', timeout=1)
    assert result.status == 'TIMEOUT'
    assert result.exit_code is None


def test_g49e_browser_executable_can_be_overridden_for_local_runner():
    native = Path('tests/test_g49d_native_browser_e2e.py').read_text()
    slow = Path('tests/test_generic_all_class_product_gate_g48d.py').read_text()
    assert 'WOW_CHROMIUM_EXECUTABLE' in native
    assert 'WOW_CHROMIUM_EXECUTABLE' in slow


def test_g49e_canonical_route_snapshots_are_fresh_before_slow_gate():
    # Inspect metadata only. Calling the public reader on a stale snapshot
    # silently triggers a full canonical solve and makes a 30s CI test take
    # minutes. A stale release is a test failure, never a valid slow fallback.
    import hashlib
    import json
    from src.v2 import generic_frontier, generic_melee_routes
    db = hashlib.sha256(generic_frontier.CANONICAL_ITEM_DB_PATH.read_bytes()).hexdigest()
    druid = json.loads(generic_frontier.ROUTE_PUBLICATION_CACHE_PATH.read_text())
    melee = json.loads(generic_melee_routes.MELEE_CACHE_PATH.read_text())
    assert druid["software_version"] == SOFTWARE_VERSION
    assert melee["software_version"] == SOFTWARE_VERSION
    assert druid["canonical_item_db_sha256"] == db
    assert melee["canonical_item_db_sha256"] == db
    assert druid["route_authority"] == generic_frontier.ROUTE_AUTHORITY
    assert melee["route_authority"] == generic_melee_routes.ROUTE_AUTHORITY
    assert druid["levels"] == list(generic_frontier.GENERIC_DRUID_ROUTE_LEVELS)
    assert melee["levels"] == {k: list(v) for k, v in generic_melee_routes.MELEE_CORRIDORS.items()}
    assert melee["source_code_fingerprint"] == generic_melee_routes._fingerprint()
