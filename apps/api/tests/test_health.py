from fastapi.testclient import TestClient

from app import store
from app.config import settings
from app.main import app

client = TestClient(app)


def test_root_endpoint() -> None:
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert data["health"] == "/api/health"


def test_health_endpoint() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "Abtract API"
    assert "version" in data
    assert "timestamp" in data


def test_hosted_sites_share_the_api_process(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    site = store.site_dir("demo", "v0")
    site.mkdir(parents=True)
    (site / "index.html").write_text("<h1>Mounted demo</h1>")

    response = client.get("/s/demo/v0/")

    assert response.status_code == 200
    assert "Mounted demo" in response.text
