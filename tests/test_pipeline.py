"""End-to-end tests on synthetic feeds: degraded mode, LLM mode, site output, newsletter."""

from __future__ import annotations

import json

import pytest

from src import newsletter, summarize
from src.common import load_config, read_json
from src.pipeline import run


class FakeProvider(summarize.LLMProvider):
    """Deterministic provider: echoes a valid summary; fails on demand."""

    calls: list[str] = []

    def complete(self, system: str, user: str) -> str:
        FakeProvider.calls.append(user)
        if "XSS test title" in user:
            return "désolé, pas de JSON"  # forces retry then fallback
        return json.dumps(
            {
                "resume": "Résumé de test fondé uniquement sur le titre et l'extrait fournis.",
                "pourquoi": "Concerne des technologies utilisées par les entreprises clientes.",
                "tags": ["test"],
                "action": "Vérifier l'exposition et appliquer les correctifs.",
                "action_type": "patch",
            },
            ensure_ascii=False,
        )


def _articles(env):
    return read_json(env["data"] / "articles.json", {})["articles"]


def test_pipeline_degraded_mode(env):
    assert run(fixtures=env["feeds"]) == 0
    arts = _articles(env)
    titles = [a["title"] for a in arts]
    assert not any("webinar" in t.lower() for t in titles), "webinar must be excluded"
    assert not any("Ancien avis" in t for t in titles), "retention must drop old items"
    assert sum("Hospital" in t or "hospital" in t for t in titles) == 1, "cross-source duplicate removed"
    forti = next(a for a in arts if "FortiOS" in a["title"])
    assert forti["kev"] and forti["level"] == "Critique" and "utm_" not in forti["url"]
    assert all(a["summary_source"] == "extrait" for a in arts)
    assert all(len(a["excerpt"]) <= 300 for a in arts)
    # site
    payload = json.loads((env["public"] / "articles.json").read_text())
    assert payload["counts"]["ALL"] == len(arts)
    assert (env["public"] / "index.html").exists() and (env["public"] / "feed.xml").exists()
    feed = (env["public"] / "feed.xml").read_text()
    assert "XSS test title" in feed
    assert "<img" not in feed and "<script" not in feed, "feed content must never contain raw markup"
    xss = next(a for a in arts if "XSS" in a["title"])
    if "<script>" in xss["excerpt"]:  # entity-encoded payload decoded to text: must be escaped on output
        assert "&lt;script&gt;" in feed


def test_pipeline_with_llm(env, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setitem(summarize.PROVIDERS, "anthropic", FakeProvider)
    monkeypatch.setattr(summarize.time, "sleep", lambda s: None)
    FakeProvider.calls = []
    assert run(fixtures=env["feeds"]) == 0
    arts = _articles(env)
    ai = [a for a in arts if a["summary_source"] == "ia"]
    assert ai, "at least one AI summary expected"
    xss = next(a for a in arts if "XSS" in a["title"])
    assert xss["summary_source"] == "extrait", "invalid LLM output falls back to excerpt"
    # injection attempt is passed as delimited data
    inj = [c for c in FakeProvider.calls if "IGNORE ALL PREVIOUS" in c]
    assert inj and inj[0].index("<article_non_fiable>") < inj[0].index("IGNORE ALL PREVIOUS") < inj[0].index(
        "</article_non_fiable>"
    )

    # cache: second run must not re-summarise successful articles
    n_calls = len(FakeProvider.calls)
    assert run(fixtures=env["feeds"]) == 0
    new_calls = FakeProvider.calls[n_calls:]
    assert all("XSS test title" in c for c in new_calls), "only the failed article may be retried"


def test_summary_cap(env, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setitem(summarize.PROVIDERS, "anthropic", FakeProvider)
    cfg = load_config()
    cfg.settings["llm"]["max_summaries_per_run"] = 2
    cfg.settings["llm"]["min_relevance"] = 0
    monkeypatch.setattr("src.pipeline.load_config", lambda: cfg)
    FakeProvider.calls = []
    run(fixtures=env["feeds"])
    assert len(FakeProvider.calls) <= 2 * (cfg.settings["llm"]["retries"] + 1)


def test_newsletter_archive_and_test_mode(env, monkeypatch):
    run(fixtures=env["feeds"])
    sent: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(newsletter, "send", lambda html, text, subj, to, smtp: sent.append((subj, to)) or len(to))
    monkeypatch.setenv("NEWSLETTER_RECIPIENTS_INTERNE", "interne@example.com")
    monkeypatch.setenv("NEWSLETTER_RECIPIENTS_CLIENTS", "client1@example.com,client2@example.com")
    assert newsletter.main(["--send", "--test"]) == 0
    archives = list((env["data"] / "weekly").glob("*-W*.md"))
    assert len(archives) == 1
    md = archives[0].read_text()
    for section in (
        "Les faits marquants",
        "## Cloud",
        "## Sécurité de l'IA",
        "Failles déjà utilisées par des pirates",
        "Prochains salons",
    ):
        assert section in md
    assert "CVE-2099-0001" in md
    assert sent and sent[0][1] == ["interne@example.com"] and sent[0][0].endswith("[TEST]")
    html_preview = (env["root"] / "build" / "newsletter_preview.html").read_text()
    assert "<script" not in html_preview and "<img" not in html_preview
    assert "display:flex" not in html_preview and "grid" not in html_preview


def test_newsletter_clients_disabled_by_default(env, monkeypatch):
    monkeypatch.setenv("NEWSLETTER_RECIPIENTS_INTERNE", "a@example.com")
    monkeypatch.setenv("NEWSLETTER_RECIPIENTS_CLIENTS", "c@example.com")
    assert newsletter.recipients(load_config(), test_mode=False) == ["a@example.com"]
    cfg = load_config()
    cfg.settings["newsletter"]["recipients"]["clients"]["enabled"] = True
    assert newsletter.recipients(cfg, test_mode=False) == ["a@example.com", "c@example.com"]
    assert newsletter.recipients(cfg, test_mode=True) == ["a@example.com"]


@pytest.mark.parametrize("hour,expected_send", [(7, True), (6, False)])
def test_schedule_guard(env, monkeypatch, hour, expected_send):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    fake_now = datetime(2027, 1, 4, hour, 0, tzinfo=ZoneInfo("Europe/Paris"))
    monkeypatch.setattr(newsletter, "utcnow", lambda: fake_now)
    monkeypatch.setenv("NEWSLETTER_RECIPIENTS_INTERNE", "a@example.com")
    sent = []
    monkeypatch.setattr(newsletter, "send", lambda *a: sent.append(1) or 1)
    newsletter.main(["--send", "--respect-schedule"])
    assert bool(sent) is expected_send


def test_no_duplicate_send_same_week(env, monkeypatch):
    run(fixtures=env["feeds"])
    monkeypatch.setenv("NEWSLETTER_RECIPIENTS_INTERNE", "a@example.com")
    sent = []
    monkeypatch.setattr(newsletter, "send", lambda *a: sent.append(1) or 1)
    newsletter.main(["--send"])
    newsletter.main(["--send"])
    assert len(sent) == 1
    newsletter.main(["--send", "--force"])
    assert len(sent) == 2
