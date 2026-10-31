"""G50c: cold *process* → real HTTP generic Decisions, without legacy scorers.

Unlike an in-process HTTP handler test, this starts the production service CLI
in a new interpreter with an import-deny guard installed *before* service imports.  The guard logs attempted imports even if the service swallows
ImportError; HTTP 200 alone is not sufficient evidence.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]

def _guard_environment(tmp_path: Path, audit_name: str) -> tuple[dict[str, str], Path]:
    guard_dir = tmp_path / "guard"
    guard_dir.mkdir(exist_ok=True)
    audit = tmp_path / audit_name
    guard_script = guard_dir / "import_guard.py"
    guard_script.write_text('''
import importlib.abc
import os
from pathlib import Path
import sys

AUDIT = Path(os.environ["WOW_G50C_IMPORT_AUDIT"])
FORBIDDEN = {
    "src.v2.decision_stat_weights",
    "src.v2.stat_weight_model",
    "src.v2.legacy_decision_projection",
    "src.v2.mature_decision_artifacts",
}
def forbidden(name):
    return name in FORBIDDEN or (name.startswith("src.rulesets.forever.classes.")
                                  and name.endswith((".engine", ".mechanics")))
class ImportDeny(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if forbidden(fullname):
            with AUDIT.open("a") as output:
                output.write("BLOCKED:" + fullname + "\\n")
            raise ImportError("G50c legacy scorer import forbidden: " + fullname)
        return None
sys.meta_path.insert(0, ImportDeny())
with AUDIT.open("a") as output:
    output.write("GUARD_LOADED:" + str(os.getpid()) + "\\n")
''', encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": os.pathsep.join((str(guard_dir), str(ROOT), env.get("PYTHONPATH", ""))),
        "WOW_G50C_IMPORT_AUDIT": str(audit),
        "WOW_G50C_GUARD_SCRIPT": str(guard_script),
        "WOW_DISABLE_LEGACY_DECISIONS": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    return env, audit


def _http_json(url: str, *, timeout: float = 35) -> tuple[int, dict]:
    try:
        with urlopen(url, timeout=timeout) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_cold_service_http_generic_survives_legacy_scorer_import_deny(tmp_path):
    env, audit = _guard_environment(tmp_path, "service_imports.log")
    port = _unused_local_port()
    url = f"http://127.0.0.1:{port}"
    # -c bootstrap is intentional: some hosts inject their own sitecustomize
    # ahead of PYTHONPATH, so relying on our sitecustomize would be a false pass.
    # The guard executes before the real production service module is imported.
    bootstrap = (
        'import os,runpy,sys;'
        'runpy.run_path(os.environ["WOW_G50C_GUARD_SCRIPT"]);'
        'sys.argv[0]="src.service.http_api";'
        'runpy.run_module("src.service.http_api",run_name="__main__")'
    )
    command = [
        sys.executable, "-c", bootstrap,
        "--host", "127.0.0.1", "--port", str(port),
        "--db", str(tmp_path / "queue.sqlite3"),
        "--project-root", str(ROOT),
    ]
    service = subprocess.Popen(
        command, cwd=ROOT, env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 15
        while True:
            if service.poll() is not None:
                raise AssertionError(f"cold service exited {service.returncode}: {service.stderr.read()}")
            try:
                health_status, health = _http_json(url + "/health", timeout=1)
                break
            except (URLError, TimeoutError, ConnectionError):
                if time.monotonic() > deadline:
                    raise AssertionError("cold service did not bind within 15 seconds")
                time.sleep(0.1)
        assert health_status == 200 and health["ok"] is True
        assert audit.is_file(), "import guard was not loaded by the service"
        assert f"GUARD_LOADED:{service.pid}" in audit.read_text()

        status, payload = _http_json(url + "/api/v1/decisions?backend=generic&class=druid&level=10")
        assert status == 200, payload
        assert payload["active_backend"] == "generic"
        assert payload["backend_selection"]["backend"] == "generic"
        assert payload["backend_selection"]["legacy_fallback"] is False
        assert payload["generic_routes"]["legacy_fallback"] is False
        assert len(payload["decisions"]) == 7
        assert len(payload["native_route_decisions"]) == 26
        assert {row["identity"]["class_name"].lower() for row in payload["decisions"]} == {
            "druid", "mage", "priest", "rogue", "shaman", "warlock", "warrior"
        }

        # The default is NOT generic while the capability gate is incomplete.
        # Disabled legacy/compare/default must fail closed, not return HTTP 200.
        for query in (
            "backend=legacy&class=druid&level=10",
            "backend=compare&class=druid&level=10",
            "class=druid&level=10",
        ):
            error_status, error = _http_json(url + "/api/v1/decisions?" + query)
            assert error_status == 503, (query, error_status, error)
            assert error["error"] == "legacy_decisions_disabled"
            assert error["legacy_fallback"] is False
            assert error["offline_fallback"] is False
            assert "decisions" not in error

        # Any attempted forbidden import, even one swallowed by application
        # code, makes the test fail; the guard is process-wide from startup.
        assert "BLOCKED:" not in audit.read_text(), audit.read_text()
    finally:
        service.terminate()
        try:
            _, stderr = service.communicate(timeout=6)
        except subprocess.TimeoutExpired:
            service.kill()
            _, stderr = service.communicate(timeout=6)
        assert service.returncode is not None, stderr


def test_import_deny_guard_has_a_failing_negative_control(tmp_path):
    for index, forbidden_import in enumerate((
        "src.v2.legacy_decision_projection",
        "src.rulesets.forever.classes.druid.engine",
    )):
        env, audit = _guard_environment(tmp_path, f"control_imports_{index}.log")
        control = subprocess.run(
            [sys.executable, "-c", (
                'import os,runpy;'
                'runpy.run_path(os.environ["WOW_G50C_GUARD_SCRIPT"]);'
                f'import {forbidden_import}'
            )],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=12,
        )
        assert control.returncode != 0
        assert "G50c legacy scorer import forbidden" in control.stderr
        assert f"BLOCKED:{forbidden_import}" in audit.read_text()
