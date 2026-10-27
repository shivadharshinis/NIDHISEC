from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["service"] == "NidhiSec API"


def test_cors_allows_vite_dev_origin() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_ignores_unknown_origin() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health", headers={"Origin": "http://unknown.example"})

    assert "access-control-allow-origin" not in response.headers
