"""G46e: predictable failure UX for cold Decision API evaluation."""
from pathlib import Path
from src.listener import DECISIONS_HTML

def test_decisions_request_is_bounded_and_retriable():
    html = DECISIONS_HTML
    assert 'new AbortController()' in html
    assert 'const timeoutMs=options.sourceOnlyLevelChange===true||!explicit?60000:20000' in html
    assert 'setTimeout(()=>controller.abort(),timeoutMs)' in html
    assert "controller.abort()" in html
    assert 'previous publication retained' in html
    assert 'id="retryDecisionLoad"' in html
    assert "data=previous" in html
    assert 'No new decision was published.' in html

def test_service_and_listener_routes_remain_distinct():
    service = Path('src/service/http_api.py').read_text()
    listener = Path('src/listener.py').read_text()
    assert 'path == f"{API_PREFIX}/decisions"' in service
    assert "path == '/api/decisions'" in listener
    assert 'return _SERVICE_CLIENT.decisions(level=level, backend_id=backend_id,' in listener
    assert 'class_name=class_name)' in listener
