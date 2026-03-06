"""Integration tests for the FastAPI backend (uses TestClient with real SQLite in-memory DB)."""
import json
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sqlalchemy.pool import StaticPool
from backend.database import Base, get_db
from backend.main import app


# --- Test DB setup (StaticPool ensures all connections share the same in-memory DB) ---
TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    # Patch _cleanup_orphaned_runs so lifespan doesn't hit the real DB
    with patch("backend.main._cleanup_orphaned_runs"):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


class TestHealthEndpoint:
    def test_llm_health_returns_json(self, client):
        resp = client.get("/api/health/llm")
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data
        assert "provider" in data


class TestSourcesEndpoints:
    def test_list_sources_empty(self, client):
        resp = client.get("/api/sources")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_source(self, client):
        payload = {
            "name": "Test Blog",
            "agent_type": "competitor",
            "urls": ["https://example.com/blog"],
            "rss_feeds": [],
            "keywords": ["AI", "ML"],
            "rate_limit": 1.0,
            "enabled": True,
        }
        resp = client.post("/api/sources", json=payload)
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["name"] == "Test Blog"
        assert data["id"] is not None

    def test_create_then_list(self, client):
        client.post("/api/sources", json={
            "name": "Blog A",
            "agent_type": "research",
            "urls": [],
            "rss_feeds": [],
            "keywords": [],
            "rate_limit": 1.0,
            "enabled": True,
        })
        resp = client.get("/api/sources")
        assert resp.status_code == 200
        sources = resp.json()
        assert len(sources) == 1
        assert sources[0]["name"] == "Blog A"

    def test_update_source(self, client):
        create_resp = client.post("/api/sources", json={
            "name": "Original",
            "agent_type": "competitor",
            "urls": [],
            "rss_feeds": [],
            "keywords": [],
            "rate_limit": 1.0,
            "enabled": True,
        })
        source_id = create_resp.json()["id"]
        update_resp = client.put(f"/api/sources/{source_id}", json={
            "name": "Updated",
            "agent_type": "competitor",
            "urls": ["https://new.com"],
            "rss_feeds": [],
            "keywords": [],
            "rate_limit": 2.0,
            "enabled": False,
        })
        assert update_resp.status_code == 200
        assert update_resp.json()["name"] == "Updated"
        assert update_resp.json()["enabled"] is False

    def test_delete_source(self, client):
        create_resp = client.post("/api/sources", json={
            "name": "ToDelete",
            "agent_type": "hf_benchmark",
            "urls": [],
            "rss_feeds": [],
            "keywords": [],
            "rate_limit": 1.0,
            "enabled": True,
        })
        source_id = create_resp.json()["id"]
        del_resp = client.delete(f"/api/sources/{source_id}")
        assert del_resp.status_code == 204
        list_resp = client.get("/api/sources")
        assert list_resp.json() == []

    def test_filter_by_agent_type(self, client):
        for name, agent_type in [("A", "competitor"), ("B", "research"), ("C", "competitor")]:
            client.post("/api/sources", json={
                "name": name,
                "agent_type": agent_type,
                "urls": [],
                "rss_feeds": [],
                "keywords": [],
                "rate_limit": 1.0,
                "enabled": True,
            })
        resp = client.get("/api/sources?agent_type=competitor")
        assert resp.status_code == 200
        sources = resp.json()
        assert len(sources) == 2
        assert all(s["agent_type"] == "competitor" for s in sources)


class TestRunsEndpoints:
    def test_list_runs_empty(self, client):
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["runs"] == []

    def test_get_nonexistent_run(self, client):
        resp = client.get("/api/runs/9999")
        assert resp.status_code == 404


class TestFindingsEndpoints:
    def test_list_findings_empty(self, client):
        resp = client.get("/api/findings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["findings"] == []

    def test_findings_stats_empty(self, client):
        resp = client.get("/api/findings/stats/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert isinstance(data["by_category"], dict)

    def test_entity_heatmap_empty(self, client):
        resp = client.get("/api/findings/stats/entities")
        assert resp.status_code == 200
        data = resp.json()
        assert "entities" in data
        assert "categories" in data

    def test_finding_diff_not_found(self, client):
        resp = client.get("/api/findings/9999/diff")
        assert resp.status_code == 404


class TestStatsEndpoint:
    def test_stats_returns_expected_fields(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_runs" in data
        assert "total_findings" in data
        assert "total_digests" in data
        assert "today_findings" in data
