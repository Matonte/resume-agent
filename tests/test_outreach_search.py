"""Tests for combination outreach web search (query planning + merge)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.services.outreach_search import (
    OutreachSearchConfig,
    WebSearchHit,
    build_query_plan,
    load_outreach_search_config,
    merge_dedupe_hits,
    run_combination_search,
)


def test_build_query_plan_includes_open_and_rule_queries() -> None:
    cfg = OutreachSearchConfig(
        open_queries=['{description} "open" test'],
        keyword_rules=[
            {
                "match": ["fintech"],
                "extra_queries": [
                    'site:example.com {description} extra',
                ],
            }
        ],
        max_queries=50,
    )
    qs = build_query_plan("Payments fintech startup in NY", config=cfg)
    assert any("open" in q and "test" in q for q in qs)
    assert any("example.com" in q and "extra" in q for q in qs)


def test_build_query_plan_explicit_tag_triggers_rule() -> None:
    cfg = OutreachSearchConfig(
        open_queries=[],
        keyword_rules=[
            {
                "match": ["fintech"],
                "extra_queries": ['site:crunchbase.com {description} x'],
            }
        ],
        max_queries=10,
    )
    qs = build_query_plan("plain description without keyword", config=cfg, explicit_tags=["fintech"])
    assert any("crunchbase.com" in q for q in qs)


def test_build_query_plan_empty_description() -> None:
    cfg = OutreachSearchConfig(open_queries=['{description} a'])
    assert build_query_plan("   ", config=cfg) == []


def test_merge_dedupe_hits_first_wins() -> None:
    a = "https://Acme.com/page?utm_source=x"
    b = "https://acme.com/page"
    h1 = WebSearchHit("t1", a, "s1", "google", "q")
    h2 = WebSearchHit("t2", b, "s2", "bing", "q")
    m = merge_dedupe_hits([h1, h2])
    assert len(m) == 1
    assert m[0].title == "t1"
    assert m[0].engine == "google"


def test_load_outreach_search_config_missing_file_uses_defaults(tmp_path: Path) -> None:
    cfg = load_outreach_search_config(tmp_path / "missing.yaml")
    assert isinstance(cfg, OutreachSearchConfig)
    assert isinstance(cfg.open_queries, list)


def test_run_combination_search_no_api_keys_returns_message(monkeypatch: pytest.MonkeyPatch) -> None:
    s = settings.model_copy(
        update={
            "google_cse_api_key": "",
            "google_cse_cx": "",
            "bing_search_key": "",
        }
    )
    monkeypatch.setattr("app.services.outreach_search.settings", s)
    r = run_combination_search("seed stage AI startup", config=OutreachSearchConfig(
        open_queries=['{description} one'],
        keyword_rules=[],
        max_queries=5,
    ))
    assert r.queries
    assert r.hits == []
    assert any("No search API" in e for e in r.errors)


def test_run_combination_search_mocked_http(monkeypatch: pytest.MonkeyPatch) -> None:
    s = settings.model_copy(
        update={
            "google_cse_api_key": "k",
            "google_cse_cx": "cx",
            "bing_search_key": "bk",
        }
    )
    monkeypatch.setattr("app.services.outreach_search.settings", s)

    class FakeResponse:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return self._payload

    class FakeClient:
        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def get(self, url: str, **kwargs: object) -> FakeResponse:
            if "googleapis.com" in url:
                return FakeResponse(
                    {
                        "items": [
                            {
                                "title": "Co",
                                "link": "https://ex.com/a?utm_medium=social",
                                "snippet": "g",
                            }
                        ],
                    }
                )
            if "bing.microsoft.com" in url:
                return FakeResponse(
                    {
                        "webPages": {
                            "value": [
                                {
                                    "name": "Co2",
                                    "url": "https://ex.com/a",
                                    "snippet": "b",
                                }
                            ],
                        }
                    }
                )
            raise AssertionError(url)

    monkeypatch.setattr("app.services.outreach_search.httpx.Client", lambda: FakeClient())
    r = run_combination_search(
        "x",
        config=OutreachSearchConfig(
            open_queries=['{description} only'],
            keyword_rules=[],
            max_queries=2,
        ),
    )
    assert len(r.hits) == 1
    assert "ex.com" in r.hits[0].url
