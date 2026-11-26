"""Tests of chantier 3: plain-language site, honest KPI cards, learning mode, single weekly review."""

from __future__ import annotations

import json
import re
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path

import pytest

from src import calibration, cards, issues, kpi, newsletter, simple
from src.common import ROOT, iso, load_config, utcnow

NOW = utcnow()
SIGLES = re.compile(r"\b(KEV|CVSS|EPSS|SQS|TTRI|HHI)\b")
ENGLISH = re.compile(
    r"\b(the|and|with|from|click|loading|search|filter|more|less|show|hide|settings|error|warning|details|help|news)\b", re.I
)
TEMPLATE = (ROOT / "site" / "index.html").read_text("utf-8")


@pytest.fixture()
def cfg(tmp_path: Path):
    return load_config(data_dir=tmp_path)


def walk(node, path=()):
    """Yield (path, string) for every string of a nested YAML structure."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, path + (str(k),))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, path + (str(i),))
    elif isinstance(node, str):
        yield path, node


# =========================================================================== vocabulary (5.3)


def test_no_sigles_outside_details_and_glossary(cfg):
    for path, text in walk(cfg.ui):
        if "details" in path or path[0] == "technique":
            continue
        assert not SIGLES.search(text), (path, text)
    for card in cfg.kpi["cartes"]:
        for key in ("question", "chiffre", "chiffre_ok", "message", "pourquoi", "que_faire", "action_probleme", "sans_donnees"):
            assert not SIGLES.search(card.get(key, "") or ""), (card["id"], key)
    for k in cfg.kpi["kpis"]:
        for key in ("question", "libelle_simple", "phrase_resultat", "pourquoi", "que_faire", "message_sans_donnees"):
            assert not SIGLES.search(k.get(key, "") or ""), (k["id"], key)


def test_no_english_interface_strings(cfg):
    for path, text in walk(cfg.ui):
        assert not ENGLISH.search(text), (path, text)
    for card in cfg.kpi["cartes"]:
        assert not ENGLISH.search(card["question"] + card["pourquoi"] + card["que_faire"]), card["id"]


def test_every_text_key_used_by_the_page_is_a_string(cfg):
    """t("a.b") must resolve to a string, not to a sub-section (would display an empty label)."""
    for key in sorted(k for k in set(re.findall(r'\bt\("([\w.]+)"', TEMPLATE)) if not k.endswith(".")):
        value = simple.lookup(cfg.ui, key)
        assert isinstance(value, str), key
    for key in set(re.findall(r'\bt\(T \+ "([\w.]+)"', TEMPLATE)):
        if not key.endswith("."):
            assert isinstance(simple.lookup(cfg.ui, "technique.details." + key), str), key


def test_levels_use_plain_words(cfg):
    labels = {k: v["libelle"] for k, v in cfg.ui["niveaux"].items()}
    assert labels == {"Critique": "Urgent", "Élevé": "Important", "Moyen": "À suivre", "Info": "Pour info"}
    assert all(v["icone"] for v in cfg.ui["niveaux"].values())  # never colour alone


def test_glossary_covers_required_terms(cfg):
    terms = cfg.glossary_ui["termes"]
    for word in ("CVE", "CVSS", "EPSS", "KEV", "DFIR", "IA", "Flux RSS"):
        assert word in terms and len(terms[word]) < 160


# =========================================================================== template (5.1, 5.2)


class TextCollector(HTMLParser):
    """Collect visible text nodes outside <script>/<style>."""

    def __init__(self):
        super().__init__()
        self.skip = 0
        self.texts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.texts.append(data.strip())


def test_template_has_no_hardcoded_text_or_sigles(cfg):
    p = TextCollector()
    p.feed(TEMPLATE)
    for text in p.texts:
        assert re.fullmatch(r"(\{\{[\w.:]+\}\}\s*)+|—", text), f"texte en dur dans site/index.html : {text!r}"
    # in the script, sigles may only appear as term("…") calls: the « ? » definitions shown inside « Détails »
    script = re.sub(r'term\("\w+"\)', "", TEMPLATE[TEMPLATE.index("<script>") :])
    assert not SIGLES.search(script)


def test_template_placeholders_resolve(cfg):
    page = simple.render_template(TEMPLATE, cfg)
    assert "{{" not in page and "Santé de la veille" in page


def test_three_views_and_three_visible_controls():
    nav = re.findall(r'data-view="(\w+)"', TEMPLATE)
    assert nav == ["actualites", "sante", "aide"]
    home = TEMPLATE[TEMPLATE.index('id="view-actualites"') : TEMPLATE.index('id="morebox"')]
    controls = re.findall(r"<(input|select)\b|role=\"switch\"", home)
    assert len(controls) == 3  # search, « Urgent seulement », period


# =========================================================================== home (5.2)


def art(i, level="Info", days=1, **kw):
    base = {"id": f"{i:016x}", "title": f"Article {i}", "url": f"https://x/{i}", "source": "S", "level": level,
            "published": iso(NOW - timedelta(days=days)), "criticality": 10, "relevance": 10, "cves": []}  # fmt: skip
    base.update(kw)
    return base


def test_home_summary_and_priority(cfg):
    arts = [art(1, "Critique", kev=True), art(2, "Élevé"), art(3, "Élevé"), art(4, "Moyen"), art(5, "Élevé", days=10)]
    home = simple.home_payload(arts, cfg, NOW)
    assert home["summary"] == "Cette semaine : 1 alerte urgente, 2 sujets importants."
    assert home["priority"][0] == arts[0]["id"] and len(home["priority"]) == 3
    calm = simple.home_payload([art(1), art(2, "Moyen")], cfg, NOW)
    assert calm["summary"].startswith("Cette semaine : rien d'urgent")


def test_priority_is_capped_at_five(cfg):
    home = simple.home_payload([art(i, "Élevé") for i in range(9)], cfg, NOW)
    assert len(home["priority"]) == 5


def test_simple_reasons_rules_and_ai_precedence(cfg):
    why, todo = simple.simple_reasons(art(1, "Élevé", kev=True), cfg.ui)
    assert "pirates" in why and todo.startswith("Vérifiez")
    why, _ = simple.simple_reasons(art(2, "Élevé", cves=["CVE-1"]), cfg.ui)
    assert why == "Faille grave dans un logiciel répandu."
    assert simple.simple_reasons(art(3, "Info"), cfg.ui) == (None, None)
    ai = art(4, "Élevé", why="Texte IA", action="Action IA")
    assert simple.simple_reasons(ai, cfg.ui) == ("Texte IA", "Action IA")


# =========================================================================== KPI availability (6.2)


def ctx_for(cfg, articles=(), **kw):
    for a in articles:
        a.setdefault("themes", ["H4"])
        a.setdefault("reliability", "Vérifié")
    return kpi.KpiContext(articles=list(articles), cfg=cfg, now=NOW, **kw)


def test_kpi_requiring_input_is_not_red_without_usage(cfg):
    values = kpi.compute_all(ctx_for(cfg))
    for kid in ("D1_utilisations", "D2_signaux_transformes", "D3_taux_transformation", "A3_temps_hors_sujet"):
        assert values[kid]["status"] == "na" and values[kid]["reason"], kid


def test_kpi_requiring_history_gives_availability_date(cfg):
    ctx = ctx_for(cfg)
    ctx.history = [{"ts": iso(NOW - timedelta(days=2)), "kpis": {}}]
    v = kpi.compute_all(ctx)["C1_signaux_faibles"]
    assert v["status"] == "na" and v["available_from"] == (NOW - timedelta(days=2) + timedelta(days=7)).date().isoformat()


def test_not_available_never_creates_action(cfg):
    hist = [{"ts": iso(NOW - timedelta(weeks=w)), "kpis": {"D1_utilisations": {"value": None, "status": "na"}}} for w in range(6)]
    state = kpi.update_actions(cfg, hist, NOW)
    assert not any(a["kpi"] == "D1_utilisations" for a in state.values())


# =========================================================================== cards (6.1 - 6.3, 6.6)


def realistic_ctx(cfg):
    """Situation of 22-23 November 2026: 23/34 sources OK, no usage, < 1 week of history."""
    status = [{"name": f"Source {i}", "ok": i < 23, "error": None if i < 23 else "HTTP 403"} for i in range(34)]
    arts = [art(i, "Élevé" if i % 5 == 0 else "Info", source=f"Source {i % 10}", relevance=60 if i % 2 else 20,
                themes=["H1"] if i % 3 else ["H2"], source_language="en", source_country="US",
                collected=iso(NOW - timedelta(hours=10)), published=iso(NOW - timedelta(hours=14))) for i in range(40)]  # fmt: skip
    ctx = ctx_for(cfg, arts, feeds_status=status)
    ctx.history = [{"ts": iso(NOW - timedelta(days=3)), "kpis": {}}]
    ctx.source_scores = {"A": {"source": "A", "sqs": 72.0}, "B": {"source": "B", "sqs": 41.0}}
    return ctx


def test_cards_show_reality(cfg):
    ctx = realistic_ctx(cfg)
    values = kpi.compute_all(ctx)
    built = {c["id"]: c for c in cards.build_cards(ctx, values, ctx.history)}
    assert len(built) == 9
    assert built["sources"]["answer"] == "probleme" and built["sources"]["chiffre"] == "23 sources sur 34 répondent"
    assert len(built["sources"]["details"]) == 11
    assert built["usage"]["answer"] == "sans_donnees" and "Signaler un usage" in built["usage"]["reason"]
    assert built["emergents"]["answer"] == "sans_donnees" and built["emergents"]["available_from"]
    assert built["fiabilite_sources"]["estimation"] is True
    assert "anglais" in built["diversite"]["chiffre"]


def test_card_without_data_is_never_red_or_actionable(cfg):
    ctx = realistic_ctx(cfg)
    values = kpi.compute_all(ctx)
    for c in cards.build_cards(ctx, values, ctx.history):
        if c["answer"] == "sans_donnees":
            assert c["color"] == "gris" and c["action"] is None and c["reason"]
    assert all(p["answer"] != "sans_donnees" for p in cards.priorities(cards.build_cards(ctx, values, ctx.history)))


def test_verdict_and_priorities(cfg):
    fake = [
        {"id": "a", "question": "Q1", "answer": "probleme", "importance": 5, "action": "Faire A", "que_faire": "x", "answer_label": "Problème", "icon": "✖"},
        {"id": "b", "question": "Q2", "answer": "surveiller", "importance": 1, "action": None, "que_faire": "Faire B", "answer_label": "À surveiller", "icon": "▲"},
        {"id": "c", "question": "Q3", "answer": "probleme", "importance": 2, "action": "Faire C", "que_faire": "x", "answer_label": "Problème", "icon": "✖"},
        {"id": "d", "question": "Q4", "answer": "bon", "importance": 3, "action": None, "que_faire": "x", "answer_label": "Bon", "icon": "✔"},
        {"id": "e", "question": "Q5", "answer": "sans_donnees", "importance": 0, "action": None, "que_faire": "x", "answer_label": "…", "icon": "…"},
        {"id": "f", "question": "Q6", "answer": "surveiller", "importance": 4, "action": None, "que_faire": "Faire F", "answer_label": "À surveiller", "icon": "▲"},
    ]  # fmt: skip
    v = cards.verdict(fake, cfg.ui["sante"])
    assert v["sentence"] == "1 point fonctionne, 2 sont à surveiller, 2 posent problème, 1 n'est pas encore mesurable."
    assert [p["text"] for p in cards.priorities(fake)] == ["Faire C", "Faire A", "Faire B"]  # max 3, problems first


def test_trend_needs_one_week_of_history(cfg):
    texts = cfg.ui["sante"]
    assert cards.trend(texts, 70, None, "%") is None
    assert "hausse" in cards.trend(texts, 70, 60, "%") and "+10 points" in cards.trend(texts, 70, 60, "%")
    hist = [{"ts": iso(NOW - timedelta(days=7)), "kpis": {"X": {"value": 5}}}]
    assert cards.value_week_ago(hist, "X", NOW) == 5


# =========================================================================== learning mode & review (6.4, 6.5)


def test_learning_mode_period(cfg):
    ctx = ctx_for(cfg)
    ctx.history = [{"ts": iso(NOW - timedelta(days=10)), "kpis": {}}]
    assert ctx.in_learning and ctx.learning_until.date() == (NOW - timedelta(days=10) + timedelta(weeks=4)).date()
    ctx.history = [{"ts": iso(NOW - timedelta(weeks=5)), "kpis": {}}]
    assert not ctx.in_learning


class FakeGH:
    def __init__(self, existing=None):
        self.issues = existing or []
        self.comments = []

    def list_issues(self, label):
        return [i for i in self.issues if label in i.get("labels", [])]

    def create_labeled(self, title, body, label):
        self.issues.append({"number": len(self.issues) + 1, "title": title, "body": body, "state": "open", "labels": [label]})

    def update(self, number, **fields):
        next(i for i in self.issues if i["number"] == number).update(fields)

    def comment(self, number, body):
        self.comments.append((number, body))


def health(learning, problems=True):
    c = [{"question": "Mes sources fonctionnent-elles ?", "answer": "probleme" if problems else "bon", "importance": 1,
          "chiffre": "23 sources sur 34 répondent", "action": "Corriger 11 sources", "failing_sources": ["A", "B"]},
         {"question": "La veille sert-elle à quelque chose ?", "answer": "sans_donnees", "importance": 2, "action": None}]  # fmt: skip
    return {"cards": c, "verdict": {"sentence": "bilan"}, "learning": {"active": learning}}


def test_no_issue_during_learning():
    gh = FakeGH()
    assert issues.sync_review(health(learning=True), gh, "https://site/", "2026-W48") == "none"
    assert gh.issues == []


def test_single_weekly_review_without_duplicates():
    gh = FakeGH()
    assert issues.sync_review(health(False), gh, "https://site/", "2026-W52") == "created"
    assert issues.sync_review(health(False), gh, "https://site/", "2026-W52") == "unchanged"
    assert issues.sync_review(health(False), gh, "https://site/", "2027-W01") == "updated"
    assert len(gh.issues) == 1
    body = gh.issues[0]["body"]
    assert "Corriger 11 sources" in body and "### Sources en panne" in body and "- A" in body
    assert "La veille sert-elle" not in body  # cards without data never produce an action
    assert issues.sync_review(health(False, problems=False), gh, "https://site/", "2027-W02") == "closed"
    assert issues.sync_review(health(False), gh, "https://site/", "2027-W03") == "reopened" and len(gh.issues) == 1


def test_legacy_action_issues_are_closed():
    legacy = {"number": 1, "body": "x <!-- action-key: B1| -->", "state": "open", "labels": [issues.LABEL]}
    gh = FakeGH([legacy])
    assert issues.close_legacy_action_issues(gh) == 1 and legacy["state"] == "closed"


# =========================================================================== calibration (6.4)


def test_calibration_proposes_median_and_never_edits_config(cfg):
    kpi_yaml = (ROOT / "config" / "kpi.yaml").read_text("utf-8")
    hist = [{"ts": iso(NOW - timedelta(days=d)), "kpis": {"B6_disponibilite_flux": {"value": 60.0 + d}}} for d in range(20)]
    rows = {r["id"]: r for r in calibration.propose(cfg, hist, NOW)}
    assert rows["B6_disponibilite_flux"]["mediane"] == 69.5 and rows["B6_disponibilite_flux"]["cible_proposee"] == 70.0
    assert calibration.maybe_write(cfg, {"active": True}, NOW) is False
    assert calibration.maybe_write(cfg, {"active": False}, NOW) is True
    assert calibration.maybe_write(cfg, {"active": False}, NOW) is False  # never overwritten
    assert "Rien n'a été modifié" in (cfg.data_dir / "kpi_calibration.md").read_text()
    assert (ROOT / "config" / "kpi.yaml").read_text("utf-8") == kpi_yaml


# =========================================================================== e-mail (7) and end-to-end


def test_email_health_block_three_lines(cfg):
    report = {"sante": {"verdict": {"sentence": "3 points fonctionnent…", "groups": {"sans_donnees": ["Q8", "Q9"]}},
                        "priorities": [{"text": "A"}, {"text": "B"}, {"text": "C"}, {"text": "D"}], "learning": {"active": True}}}  # fmt: skip
    (cfg.data_dir / "kpi_latest.json").write_text(json.dumps(report), "utf-8")
    h = newsletter.health_summary(cfg)
    assert h["todo"] == ["A", "B", "C"] and h["missing"] == ["Q8", "Q9"] and "provisoires" in h["verdict"]


def test_end_to_end_site_and_email(env):
    from src.pipeline import run

    assert run(fixtures=env["feeds"]) == 0
    payload = json.loads((env["public"] / "articles.json").read_text())
    assert payload["home"]["summary"].startswith("Cette semaine")
    assert payload["ui"]["navigation"]["sante"] == "Santé de la veille" and "KEV" in payload["glossary"]
    assert any(a["why_simple"] for a in payload["articles"])
    k = json.loads((env["public"] / "kpi.json").read_text())
    assert len(k["sante"]["cards"]) == 9 and k["sante"]["learning"]["active"] is True
    assert len(k["sante"]["priorities"]) <= 3
    page = (env["public"] / "index.html").read_text()
    assert "{{" not in page
    newsletter.main([])
    md = next((env["data"] / "weekly").glob("*-W*.md")).read_text()
    assert "## Santé de la veille" in md and "**Bilan**" in md and "Pas encore mesurable" in md
    assert "Important" in md or "Urgent" in md or "Pour info" in md
