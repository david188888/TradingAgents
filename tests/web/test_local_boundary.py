"""Browser requests must stay on the loopback workbench origin."""

import pytest
from fastapi.testclient import TestClient

from tradingagents.runtime.store import RunStore
from tradingagents.web.api import create_app

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("host", ["attacker.example", "127.0.0.1.attacker.example"])
def test_untrusted_host_is_rejected_before_serving_history(tmp_path, host):
    app = create_app(store=RunStore(tmp_path), recover_startup=False, environment={})
    with TestClient(app, base_url=f"http://{host}:8765") as client:
        assert client.get("/api/runs").status_code == 403


@pytest.mark.parametrize("origin", ["https://attacker.example", "null", "http://localhost:8765"])
def test_foreign_origin_cannot_mutate_run_history(tmp_path, origin):
    app = create_app(store=RunStore(tmp_path), recover_startup=False, environment={})
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.delete("/api/runs", headers={"Origin": origin})
        assert response.status_code == 403


def test_same_origin_browser_and_originless_local_client_remain_supported(tmp_path):
    app = create_app(store=RunStore(tmp_path), recover_startup=False, environment={})
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.delete("/api/runs", headers={"Origin": "http://127.0.0.1:8765"}).status_code == 200
        assert client.delete("/api/runs").status_code == 200
