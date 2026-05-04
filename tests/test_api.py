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
    assert "whoiswhat_people_intel_configured" in data["loaded_files"]
    assert "web_search_configured" in data["loaded_files"]


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


def test_meeting_advisor_standalone_not_configured(monkeypatch):
    monkeypatch.setattr(app_settings, "meeting_advisor_url", "")
    res = client.post(
        "/api/meeting-advisor",
        json={"description": "Senior Backend Engineer role with Python and AWS " * 2},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["configured"] is False


def test_meeting_advisor_standalone_single_mocked(monkeypatch):
    monkeypatch.setattr(app_settings, "meeting_advisor_url", "http://test.local")
    monkeypatch.setattr(
        "app.routers.api.advise_for_job_context",
        lambda **kwargs: {"advice": {"opening_move": "Brief intro"}},
    )
    res = client.post(
        "/api/meeting-advisor",
        json={
            "description": "Senior Backend Engineer role with Python and AWS " * 2,
            "company": "Acme",
            "subject_name": "Jamie Chen",
            "extract_people": False,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["configured"] is True
    assert data["advice"]["advice"]["opening_move"] == "Brief intro"


def test_meeting_advisor_standalone_extract_empty_falls_back_to_generic_advice(monkeypatch):
    monkeypatch.setattr(app_settings, "meeting_advisor_url", "http://test.local")
    monkeypatch.setattr(
        "app.routers.api.extract_people_from_posting_corpus",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "app.routers.api.advise_for_job_context",
        lambda **kwargs: {"advice": {"opening_move": "Generic prep"}},
    )
    res = client.post(
        "/api/meeting-advisor",
        json={
            "description": "Senior Backend Engineer role with Python and AWS " * 2,
            "company": "Acme",
            "use_llm": False,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["configured"] is True
    assert data["advice"]["advice"]["opening_move"] == "Generic prep"
    assert data.get("meeting_advisor_note")
    assert "names" in data["meeting_advisor_note"].lower() or "posting" in data[
        "meeting_advisor_note"
    ].lower()


def test_meeting_advisor_standalone_extract_people_mocked(monkeypatch):
    from app.services.outreach_enrich import OutreachContactDossier, OutreachStakeholderNotes
    from app.services.outreach_posting_people import PostingPerson

    monkeypatch.setattr(app_settings, "meeting_advisor_url", "http://test.local")
    monkeypatch.setattr(
        "app.routers.api.extract_people_from_posting_corpus",
        lambda *a, **k: [
            PostingPerson(name="Riley Nova", role_hint="Talent Partner", evidence="Riley Nova")
        ],
    )

    def _fake_dossiers(people, **kwargs):
        return [
            OutreachContactDossier(
                title="Riley Nova — Co",
                url="x",
                snippet="s",
                inferred_primary_role="recruiter",
                recruiter=OutreachStakeholderNotes(),
                hiring_manager=OutreachStakeholderNotes(),
                combined_opening="Hi",
            )
        ]

    monkeypatch.setattr("app.routers.api.advise_posting_people_dossiers", _fake_dossiers)
    res = client.post(
        "/api/meeting-advisor",
        json={
            "description": "Senior Backend Engineer role with Python and AWS " * 2,
            "company": "Co",
            "extract_people": True,
            "use_llm": False,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["configured"] is True
    assert len(data["people"]) == 1
    assert data["people"][0]["inferred_primary_role"] == "recruiter"


def test_meeting_advisor_page_loads(monkeypatch):
    monkeypatch.setattr(app_settings, "meeting_advisor_url", "")
    monkeypatch.setattr(app_settings, "meeting_advisor_ui_url", "")
    res = client.get("/meeting-advisor")
    assert res.status_code == 200
    assert "Meeting advisor" in res.text


def test_meeting_advisor_aliases_redirect_to_embedded_page(monkeypatch):
    monkeypatch.setattr(app_settings, "meeting_advisor_url", "")
    monkeypatch.setattr(app_settings, "meeting_advisor_ui_url", "")
    r = client.get("/advisor", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers.get("location") == "/api/meeting-advisor/page"
    r2 = client.get("/meeting-advisor/", follow_redirects=False)
    assert r2.status_code == 307
    assert r2.headers.get("location") == "/api/meeting-advisor/page"


def test_meeting_advisor_serves_embedded_when_api_configured_without_ui_url(
    monkeypatch,
):
    monkeypatch.setattr(app_settings, "meeting_advisor_url", "http://127.0.0.1:5003")
    monkeypatch.setattr(app_settings, "meeting_advisor_ui_url", "")
    res = client.get("/meeting-advisor", follow_redirects=False)
    assert res.status_code == 200
    assert "Meeting advisor" in res.text


def test_meeting_advisor_standalone_honors_meeting_advisor_ui_url(monkeypatch):
    monkeypatch.setattr(app_settings, "meeting_advisor_url", "http://api.example:5003")
    monkeypatch.setattr(app_settings, "meeting_advisor_ui_url", "http://ui.example/advisor/")
    r = client.get("/advisor", follow_redirects=False)
    assert r.headers.get("location") == "http://ui.example/advisor"


def test_meeting_advisor_nested_page_loads(monkeypatch):
    monkeypatch.setattr(app_settings, "meeting_advisor_url", "")
    monkeypatch.setattr(app_settings, "meeting_advisor_ui_url", "")
    res = client.get("/meeting-advisor/page")
    assert res.status_code == 200
    assert "Meeting advisor" in res.text


def test_api_meeting_advisor_trailing_slash_redirects_embedded(monkeypatch):
    monkeypatch.setattr(app_settings, "meeting_advisor_url", "")
    monkeypatch.setattr(app_settings, "meeting_advisor_ui_url", "")
    r = client.get("/api/meeting-advisor/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers.get("location") == "/api/meeting-advisor/page"


def test_api_meeting_advisor_trailing_slash_redirects_to_page_when_api_configured(
    monkeypatch,
):
    monkeypatch.setattr(app_settings, "meeting_advisor_url", "http://127.0.0.1:5003")
    monkeypatch.setattr(app_settings, "meeting_advisor_ui_url", "")
    r = client.get("/api/meeting-advisor/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers.get("location") == "/api/meeting-advisor/page"


def test_meeting_advisor_page_under_api_loads(monkeypatch):
    monkeypatch.setattr(app_settings, "meeting_advisor_url", "")
    monkeypatch.setattr(app_settings, "meeting_advisor_ui_url", "")
    res = client.get("/api/meeting-advisor/page")
    assert res.status_code == 200
    assert "Meeting advisor" in res.text


def test_api_meeting_advisor_get_help(monkeypatch):
    monkeypatch.setattr(app_settings, "meeting_advisor_url", "")
    monkeypatch.setattr(app_settings, "meeting_advisor_ui_url", "")
    res = client.get("/api/meeting-advisor")
    assert res.status_code == 200
    data = res.json()
    assert data["method"] == "POST"
    assert data["ui"] == "/meeting-advisor"


def test_api_meeting_advisor_get_help_embedded_ui_when_only_api_configured(monkeypatch):
    monkeypatch.setattr(app_settings, "meeting_advisor_url", "http://flask.local:5003")
    monkeypatch.setattr(app_settings, "meeting_advisor_ui_url", "")
    res = client.get("/api/meeting-advisor")
    assert res.status_code == 200
    assert res.json()["ui"] == "/meeting-advisor"


def test_api_meeting_advisor_get_help_external_ui_when_ui_url_set(monkeypatch):
    monkeypatch.setattr(app_settings, "meeting_advisor_url", "http://api.example:5003")
    monkeypatch.setattr(app_settings, "meeting_advisor_ui_url", "http://ui.example/advisor/")
    res = client.get("/api/meeting-advisor")
    assert res.status_code == 200
    assert res.json()["ui"] == "http://ui.example/advisor"


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


def test_person_web_search_when_keys_missing(monkeypatch):
    from app.config import settings as app_settings

    s = app_settings.model_copy(
        update={
            "google_cse_api_key": "",
            "google_cse_cx": "",
            "bing_search_key": "",
        }
    )
    monkeypatch.setattr("app.routers.api.settings", s)
    res = client.post("/api/person-web-search", json={"name": "Jane Doe"})
    assert res.status_code == 200
    body = res.json()
    assert body["web_search_configured"] is False
    assert body["hits"] == []


def test_person_web_search_short_name(monkeypatch):
    from app.config import settings as app_settings

    s = app_settings.model_copy(
        update={
            "google_cse_api_key": "dummy-key",
            "google_cse_cx": "dummy-cx",
            "bing_search_key": "",
        }
    )
    monkeypatch.setattr("app.routers.api.settings", s)
    res = client.post("/api/person-web-search", json={"name": "x"})
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
