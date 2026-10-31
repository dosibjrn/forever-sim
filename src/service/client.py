from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_SERVICE_URL = os.environ.get("WOW_OPTIMIZER_SERVICE_URL", "http://127.0.0.1:8765").rstrip("/")
API_PREFIX = "/api/v1"


class ServiceClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServiceClient:
    """Small stdlib-only client shared by CLI/listener thin clients.

    It never falls back to QueueStore implicitly: callers must choose direct/local
    recovery mode explicitly so a dead service cannot silently split authority.
    """

    base_url: str = DEFAULT_SERVICE_URL
    timeout: float = 2.0

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None, *, timeout: float | None = None) -> Any:
        url = self.base_url.rstrip("/") + path
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(url, data=data, method=method, headers=headers)
        try:
            with urlopen(req, timeout=self.timeout if timeout is None else float(timeout)) as resp:
                raw = resp.read()
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error")
            except Exception:
                detail = None
            raise ServiceClientError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ServiceClientError(f"optimizer service unavailable at {self.base_url}: {exc}") from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ServiceClientError(f"invalid JSON from optimizer service: {url}") from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def status(self) -> dict[str, Any]:
        return dict(self._request("GET", f"{API_PREFIX}/status"))

    def decisions(self, *, level: int | None = None, backend_id: str | None = None,
                  class_name: str | None = None) -> dict[str, Any]:
        path=f"{API_PREFIX}/decisions"
        params: dict[str, Any] = {}
        if backend_id is not None:
            params["backend"] = str(backend_id)
        if level is not None:
            params["level"] = int(level)
        if class_name is not None:
            params["class"] = str(class_name)
        if params:
            path += "?" + urlencode(params)
        # Generic selected-level payloads can require a cold all-class source
        # publication (~38s measured at L20 in G48d).  A deliberate 60s UI
        # source-only level refresh must not be cut off by the listener's old
        # 15s service-client deadline.  Other control-plane requests stay fast.
        decision_timeout = 65.0 if (backend_id is None and class_name is not None) or str(backend_id).lower() == "generic" else 15.0
        return dict(self._request("GET", path, timeout=max(self.timeout, decision_timeout)))

    def queued_generic_decision(self, *, class_name: str, level: int,
                                backend_id: str) -> dict[str, Any]:
        params=urlencode({"class": class_name, "level": int(level), "backend": backend_id})
        return dict(self._request("GET", f"{API_PREFIX}/decisions/queued?{params}"))

    def list_jobs(self, states: list[str] | None = None) -> list[dict[str, Any]]:
        query = ""
        if states:
            query = "?" + urlencode([("state", x) for x in states])
        return list(self._request("GET", f"{API_PREFIX}/jobs{query}").get("jobs") or [])

    def get_job(self, job_id: str) -> dict[str, Any]:
        return dict(self._request("GET", f"{API_PREFIX}/jobs/{job_id}"))

    def enqueue(self, body: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        value = self._request("POST", f"{API_PREFIX}/jobs", body)
        return dict(value["job"]), bool(value.get("created"))

    def submit_intent(self, body: dict[str, Any]) -> dict[str, Any]:
        return dict(self._request("POST", f"{API_PREFIX}/intents", body))

    def refresh_items(self, classes: list[str] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if classes is not None:
            body["classes"] = classes
        return dict(self._request("POST", f"{API_PREFIX}/items/refresh", body).get("refresh") or {})

    def item_refresh_status(self, task_id: str | None = None) -> dict[str, Any] | None:
        path=f"{API_PREFIX}/items/refresh" + (("?" + urlencode({"task_id":task_id})) if task_id else "")
        value=self._request("GET", path).get("refresh")
        return dict(value) if value else None

    def abilities_status(self, task_id: str | None = None) -> dict[str, Any]:
        path=f"{API_PREFIX}/abilities/refresh" + (("?" + urlencode({"task_id":task_id})) if task_id else "")
        return dict(self._request("GET", path))

    def refresh_abilities(self, *, mode: str = 'index', max_details: int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {'mode': mode}
        if max_details is not None:
            body['max_details'] = int(max_details)
        return dict(self._request('POST', f'{API_PREFIX}/abilities/refresh', body).get('refresh') or {})

    def add_item(self, item: str | int, *, class_name: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"item": item}
        if class_name:
            body["class_name"] = class_name
        # Exact Wowhead point-add launches a real browser fetch and can legitimately
        # take tens of seconds. Keep the normal control-plane timeout short, but do
        # not make the listener give up after 2 s while the service is still working.
        return dict(self._request("POST", f"{API_PREFIX}/items/add", body, timeout=max(self.timeout, 75.0)))

    def set_priority(self, job_id: str, value: int) -> dict[str, Any]:
        return dict(self._request("POST", f"{API_PREFIX}/jobs/{job_id}/priority", {"priority": int(value)}))

    def reorder(self, job_ids: list[str]) -> list[dict[str, Any]]:
        return list(self._request("POST", f"{API_PREFIX}/queue/reorder", {"job_ids": job_ids}).get("jobs") or [])

    def control(self, job_id: str, action: str) -> dict[str, Any]:
        if action not in {"pause", "resume", "cancel", "checkpoint"}:
            raise ValueError(f"unsupported action {action}")
        return dict(self._request("POST", f"{API_PREFIX}/jobs/{job_id}/{action}", {}))


    def clone(self, job_id: str, *, overrides: dict[str, Any] | None = None, priority: int | None = None, deduplicate: bool = False) -> tuple[dict[str, Any], bool]:
        body: dict[str, Any] = {"overrides": dict(overrides or {}), "deduplicate": bool(deduplicate)}
        if priority is not None:
            body["priority"] = int(priority)
        value=self._request("POST", f"{API_PREFIX}/jobs/{job_id}/clone", body)
        return dict(value["job"]), bool(value.get("created"))

    def attempts(self, job_id: str) -> list[dict[str, Any]]:
        return list(self._request("GET", f"{API_PREFIX}/jobs/{job_id}/attempts").get("attempts") or [])

    def checkpoints(self, job_id: str) -> list[dict[str, Any]]:
        return list(self._request("GET", f"{API_PREFIX}/jobs/{job_id}/checkpoints").get("checkpoints") or [])

    def saved_states(self, job_id: str) -> list[dict[str, Any]]:
        return list(self._request("GET", f"{API_PREFIX}/jobs/{job_id}/saved-states").get("saved_states") or [])

    def select_saved_state(self, job_id: str, checkpoint_id: str, mode: str) -> dict[str, Any]:
        return dict(self._request("POST", f"{API_PREFIX}/jobs/{job_id}/saved-state", {"checkpoint_id": checkpoint_id, "mode": mode}))

    def publications(self, *, job_id: str | None = None, class_name: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        params={"limit":int(limit)}
        if job_id is not None: params["job_id"]=job_id
        if class_name is not None: params["class_name"]=class_name
        return list(self._request("GET", f"{API_PREFIX}/publications?{urlencode(params)}").get("publications") or [])

    def lineage(self, job_id: str) -> dict[str, Any]:
        return dict(self._request("GET", f"{API_PREFIX}/jobs/{job_id}/lineage"))

    def events(self, *, after: int = 0, job_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        path = f"{API_PREFIX}/events" if job_id is None else f"{API_PREFIX}/jobs/{job_id}/events"
        query = urlencode({"after": int(after), "limit": int(limit)})
        return list(self._request("GET", f"{path}?{query}").get("events") or [])
