"""End-to-end API tests via FastAPI's TestClient."""

from fastapi.testclient import TestClient

from app.config import settings as app_settings
from app.main import app

client = TestClient(app)


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["loaded_files"]["truth_model_roles"] > 0
    assert "llm_configured" in data["loaded_files"]
    assert "meeting_advisor_configured" in data["loaded_files"]


def test_classify():
    res = client.post(
        "/api/classify",
        json={"description": "Kafka streaming pipelines and real-time ingestion"},
    )
    assert res.status_code == 200
    assert res.json()["archetype_id"] == "C_data_streaming_systems"


def test_full_draft_with_question():
    res = client.post(
        "/api/full-draft",
        json={
            "description": "Senior Backend Engineer, Payments Platform: transaction integrity, compliance, audit trail.",
            "question": "Why this role?",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["classification"]["archetype_id"] == "B_fintech_transaction_systems"
    assert data["resume"]["summary"]
    assert data["resume"]["selected_bullets"]
    assert data["answer"] is not None
    assert data["answer"]["answer"]
    assert "fit" in data
    assert 0.0 <= data["fit"]["score"] <= 10.0
    assert data["fit"]["band"]
    assert data.get("meeting_advice") is None
    assert data.get("meeting_advisor_note") is None


def test_full_draft_without_question_omits_answer():
    res = client.post(
        "/api/full-draft",
        json={"description": "Distributed backend role, low latency and concurrency."},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["answer"] is None
    assert "fit" in data


def test_fit_score_endpoint():
    res = client.post(
        "/api/fit-score",
        json={"description": "Kafka streaming pipelines and real-time ingestion."},
    )
    assert res.status_code == 200
    data = res.json()
    assert 0.0 <= data["score"] <= 10.0
    assert data["band"]
    assert data["reasons"]


def test_full_draft_with_meeting_advisor_mocked(monkeypatch):
    monkeypatch.setattr(app_settings, "meeting_advisor_url", "http://test.local")
    monkeypatch.setattr(
        "app.routers.api.advise_for_job_context",
        lambda **kwargs: {"advice": {"opening_move": "Ping"}},
    )
    res = client.post(
        "/api/full-draft",
        json={
            "description": "Senior Backend Engineer, Payments Platform: transaction integrity.",
            "meeting_advisor": True,
            "company": "Acme",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["meeting_advice"]["advice"]["opening_move"] == "Ping"


def test_generate_resume_download():
    res = client.post(
        "/api/generate-resume",
        json={
            "description": "Backend role, distributed systems, low latency, concurrency.",
            "target_company": "Acme Corp",
        },
    )
    assert res.status_code == 200
    assert (
        res.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert 'attachment; filename="' in res.headers.get("content-disposition", "")
    body = res.content
    assert len(body) > 5000
    assert body[:2] == b"PK"


def test_generate_resume_requires_description():
    res = client.post("/api/generate-resume", json={"description": "   "})
    assert res.status_code == 400


def test_outreach_enrich_requires_fields():
    res = client.post("/api/outreach/enrich", json={"company_description": "x", "hits": []})
    assert res.status_code == 400
    res = client.post(
        "/api/outreach/enrich",
        json={
            "company_description": "   ",
            "hits": [{"title": "t", "url": "https://x.com"}],
        },
    )
    assert res.status_code == 400


def test_outreach_enrich_returns_dossiers():
    res = client.post(
        "/api/outreach/enrich",
        json={
            "company_description": "Fintech backend NYC",
            "hits": [
                {
                    "title": "Recruiter",
                    "url": "https://linkedin.com/in/x",
                    "snippet": "Hiring engineers",
                    "query": "q",
                    "engine": "google",
                }
            ],
            "use_llm": False,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["url"] == "https://linkedin.com/in/x"
    assert "recruiter" in data[0]


def test_root_serves_html():
    res = client.get("/")
    assert res.status_code == 200
    assert "Resume Agent" in res.text
