"""Tests of the quality / KPI layer (chantier 2)."""

from __future__ import annotations

import gzip
import json
from datetime import timedelta
from pathlib import Path

import pytest

from src import archive, issues, kpi, quality, signals, usage
from src.classify import classify, detect_glossary
from src.common import iso, load_config, utcnow

NOW = utcnow()


@pytest.fixture()
def cfg(tmp_path: Path):
    c = load_config(data_dir=tmp_path)
    return c


def art(i: int = 0, **kw):
    base = {
        "id": f"{i:016x}",
        "title": f"Article {i}",
        "url": f"https://www.cert.ssi.gouv.fr/avis/{i}/",
        "source": "CERT-FR - Avis",
        "published": iso(NOW - timedelta(hours=10)),
        "collected": iso(NOW - timedelta(hours=8)),
        "excerpt": "",
        "language": "fr",
        "source_language": "fr",
        "feed_themes": ["H4"],
        "feed_priority": 1,
        "tags": [],
        "cves": [],
        "themes": ["H4"],
        "relevance": 50,
        "criticality": 30,
        "level": "Moyen",
        "summary_source": "extrait",
    }
    base.update(kw)
    return base


def ctx_for(cfg, articles, **kw):
    for a in articles:
        a.setdefault("reliability", "Vérifié")
    return kpi.KpiContext(articles=articles, cfg=cfg, now=NOW, **kw)


# =========================================================================== glossary (5.3)


def test_glossary_maps_french_and_english_to_same_concept(cfg):
    fr = art(1, title="Une campagne de rançongiciel cible les hôpitaux", feed_themes=[])
    en = art(2, title="New ransomware campaign targets hospitals", feed_themes=[], language="en")
    c_fr, ax_fr = detect_glossary(fr, cfg.glossary)
    c_en, ax_en = detect_glossary(en, cfg.glossary)
    assert "rancongiciel" in c_fr and "rancongiciel" in c_en
    assert ax_fr == ax_en == ["H4"]


def test_glossary_adds_axis_missing_from_keywords(cfg):
    a = art(3, title="Extraction de modèle : une nouvelle technique d'attaque", feed_themes=["H4"])
    a.pop("themes")
    out = classify([a], cfg)[0]
    assert "H3" in out["themes"] and out["glossary_axes_added"] == ["H3"]
    assert "vol-modele" in out["glossary_concepts"]


# =========================================================================== source quality (5.1 B)


def test_credibility_weights():
    assert quality.credibility({"ae": 90, "ir": 95, "pr": 90}, {"ae": 0.3, "ir": 0.4, "pr": 0.3}) == 92.0


def test_domain_approval_with_host_and_path():
    approved = ["cert.cyber.gouv.fr", "github.com/NVIDIA/garak"]
    assert quality.domain_approved("https://www.cert.cyber.gouv.fr/avis/x", approved)
    assert quality.domain_approved("https://github.com/NVIDIA/garak/releases/tag/v1", approved)
    assert not quality.domain_approved("https://github.com/evil/garak", approved)
    assert not quality.domain_approved("https://cert.cyber.gouv.fr.evil.com/x", approved)


def test_source_quality_score_formula(cfg):
    arts = [
        art(1, relevance=80, level="Élevé"),
        art(2, relevance=10, level="Info"),
    ]
    quality.annotate(arts, cfg)
    row = quality.source_scores(arts, cfg, NOW)["CERT-FR - Avis"]
    assert row["pertinence"] == 50.0  # 1 of 2 above 35
    assert row["credibilite"] == 92.0
    assert row["nouveaute"] == 100.0  # sole publisher
    # efficiency = 0.5 * speed(2h -> 100) + 0.5 * useful (Élevé only = 50 %)
    assert row["ttri_h"] is None or row["efficacite"] == 75.0
    expected = round(0.30 * 50 + 0.25 * 92 + 0.25 * 100 + 0.20 * row["efficacite"], 1)
    assert row["sqs"] == expected


def test_source_without_articles_is_not_available(cfg):
    scores = quality.source_scores([], cfg, NOW)
    assert scores["Wiz Blog"]["sqs"] is None and scores["Wiz Blog"]["credibilite"] > 0


def test_novelty_first_publisher(cfg):
    a = art(1, source="BleepingComputer", url="https://www.bleepingcomputer.com/x", published=iso(NOW - timedelta(hours=5)))
    a["also_in"] = ["The Hacker News"]
    a["also_in_published"] = {"The Hacker News": iso(NOW - timedelta(hours=3))}
    quality.annotate([a], cfg)
    assert a["first_publishers"] == ["BleepingComputer"]
    scores = quality.source_scores([a], cfg, NOW)
    assert scores["BleepingComputer"]["nouveaute"] == 100.0


def test_corroboration_by_shared_cve_and_independent_orgs(cfg):
    a = art(1, source="CERT-FR - Avis", cves=["CVE-2099-1"])
    b = art(2, source="CERT-FR - Alertes", cves=["CVE-2099-1"], url="https://www.cert.ssi.gouv.fr/alerte/2/")
    c = art(3, source="BleepingComputer", cves=["CVE-2099-1"], url="https://www.bleepingcomputer.com/c")
    quality.annotate([a, b], cfg)
    assert a["corroboration_orgs"] == ["ANSSI"]  # same organisation: not independent
    quality.annotate([a, b, c], cfg)
    assert set(a["corroboration_orgs"]) == {"ANSSI", "BleepingComputer"}


def test_ttri_ignores_first_collection_backlog(cfg):
    first = iso(NOW - timedelta(days=2))
    backlog = art(1, published=iso(NOW - timedelta(days=6)), collected=first)
    fresh = art(2, published=iso(NOW - timedelta(hours=5)), collected=iso(NOW - timedelta(hours=1)))
    delays = quality.ttri_delays([backlog, fresh], cfg)["CERT-FR - Avis"]
    assert delays == [4.0]


# =========================================================================== reliability badge (5.4)


def test_badge_verified_for_official_source(cfg):
    a = art(1)
    quality.annotate([a], cfg)
    assert a["reliability"] == "Vérifié"


def test_badge_unreferenced_domain(cfg):
    a = art(1, url="https://random-blog.example/post")
    quality.annotate([a], cfg)
    assert a["reliability"] == "Source non référencée"


def test_badge_to_crosscheck_vendor_alone_and_sensational(cfg):
    a = art(1, source="Wiz Blog", url="https://www.wiz.io/blog/x", title="Massive hack hits cloud")
    quality.annotate([a], cfg)
    assert a["reliability"] == "À recouper"
    assert a["checks"]["corroborated"] is False and a["checks"]["not_sensational"] is False


def test_badge_refuted_cve_and_http(cfg):
    a = art(1, cves=["CVE-2099-9"], cve_details={"CVE-2099-9": {"nvd_found": False, "kev": False}})
    quality.annotate([a], cfg)
    assert a["checks"]["cves_confirmed"] is False and a["reliability"] == "À recouper"
    b = art(2, url="http://www.cert.ssi.gouv.fr/avis/2/")
    quality.annotate([b], cfg)
    assert b["checks"]["https"] is False


def test_translation_steps(cfg):
    en = art(1, source_language="en", summary_source="ia")
    fr = art(2, source_language="fr", summary_source="ia")
    raw = art(3, source_language="en", summary_source="extrait")
    quality.annotate([en, fr, raw], cfg)
    assert [en["translation_steps"], fr["translation_steps"], raw["translation_steps"]] == [1, 0, 0]
    assert all(a["summary_from"] == "original" for a in (en, fr, raw))


# =========================================================================== weak signals (5.1 C)


def _old(i, title, weeks_ago, **kw):
    pub = NOW - timedelta(weeks=weeks_ago, hours=1)
    return art(i, title=title, published=iso(pub), collected=iso(pub + timedelta(hours=2)), **kw)


def _history_padding():
    """Articles proving 5 weeks of collection (end of warm-up), unrelated titles."""
    return [_old(900 + w, f"Bulletin hebdomadaire numéro {w}", w) for w in range(1, 6)]


def test_weak_signal_detected_in_both_languages(cfg):
    arts = _history_padding() + [
        art(1, title="Nouvelle campagne de rançongiciel « Cairn » contre les PME", glossary_concepts=["rancongiciel"]),
        art(2, title="Manufacturers hit by Cairn ransomware", source="BleepingComputer", source_language="en",
            url="https://www.bleepingcomputer.com/c", glossary_concepts=["rancongiciel"]),
    ]  # fmt: skip
    found = {s["term"]: s for s in signals.detect_weak_signals(arts, cfg, NOW)}
    assert "Rançongiciel" in found and "Cairn" in found
    assert found["Rançongiciel"]["languages"] == ["en", "fr"]
    assert found["Cairn"]["count_week"] == 2


def test_weak_signal_rejects_frequent_or_widespread_terms(cfg):
    arts = _history_padding()
    arts += [_old(100 + w, "Exchange flaw exploited again", w, source="BleepingComputer") for w in range(1, 5) for _ in range(2)]
    arts += [art(1, title="Exchange flaw exploited"), art(2, title="Exchange servers attacked")]
    assert "Exchange" not in {s["term"] for s in signals.detect_weak_signals(arts, cfg, NOW)}


def test_weak_signal_warmup_and_title_case(cfg):
    arts = [art(1, title="Cairn ransomware hits"), art(2, title="Cairn ransomware again")]
    assert signals.detect_weak_signals(arts, cfg, NOW) == []  # less than one week of history
    terms = signals.article_terms(art(3, title="Hackers Exploit Flaw In BIG-IP Appliances Warns Agency"), cfg, set())
    labels = {v[0] for v in terms.values()}
    assert "BIG-IP" in labels and "Warns" not in labels and "Appliances" not in labels


def test_weak_signals_markdown_keeps_user_edits():
    sig = [
        {
            "key": "entity:cairn",
            "term": "Cairn",
            "axis": "H4",
            "count_week": 2,
            "baseline_weekly": 0,
            "sources": ["A"],
            "articles": [],
        }
    ]
    md = signals.render_weak_signals_md("", sig, "2026-W48")
    md = md.replace("_(ex. « ce produit va être massivement ciblé en France d'ici 3 mois »)_", "Mon hypothèse")
    again = signals.render_weak_signals_md(md, sig, "2026-W48")
    assert again.count("<!-- signal:2026-W48:entity:cairn -->") == 1 and "Mon hypothèse" in again


# =========================================================================== KPI families (5.1)


def test_family_a_relevance_and_coverage(cfg):
    arts = [art(i, themes=["H1"], relevance=60 if i < 3 else 10) for i in range(4)]
    ctx = ctx_for(cfg, arts)
    res = kpi.relevance_share_by_axis(ctx)
    assert res["subs"]["H1"] == 75.0 and res["subs"]["H2"] is None
    cov = kpi.weekly_coverage_by_axis(ctx)
    assert cov["subs"]["H1"] == 30.0  # 3 relevant / weekly target 10


def test_family_a_offtopic_needs_usage(cfg):
    assert kpi.offtopic_time_share(ctx_for(cfg, []))["value"] is None
    today = NOW.date().isoformat()
    use = [
        {"kind": "usage", "type": usage.OFFTOPIC_TYPE, "date": today},
        {"kind": "usage", "type": "alerte envoyée", "date": today},
    ]
    assert kpi.offtopic_time_share(ctx_for(cfg, [], usage=use))["value"] == 50.0


def test_family_b_corroboration_unreferenced_availability(cfg):
    arts = [art(1, level="Critique", corroboration_orgs=["ANSSI", "CISA"]), art(2, level="Élevé", corroboration_orgs=["ANSSI"])]
    arts.append(art(3, reliability="Source non référencée", domain="x.example"))
    ctx = ctx_for(cfg, arts, feeds_status=[{"name": "A", "ok": True}, {"name": "B", "ok": False}])
    assert kpi.corroboration_rate(ctx)["value"] == 50.0
    assert kpi.unreferenced_articles(ctx)["value"] == 1.0
    assert kpi.feed_availability(ctx)["value"] == 50.0
    assert kpi.feed_availability_by_source(ctx)["subs"] == {"A": 100.0, "B": 0.0}


def test_family_d_usage_and_transformation(cfg):
    today = NOW.date().isoformat()
    use = [
        {"kind": "usage", "type": "alerte envoyée", "date": today},
        {"kind": "usage", "type": "note rédigée", "date": "2000-01-01"},  # out of window
        {"kind": "signal", "type": "hypothèse de transformation", "date": today},
    ]
    sig = [{"key": "entity:a", "axis": "H4"}, {"key": "entity:b", "axis": "H1"}]
    ctx = ctx_for(cfg, [], usage=use, signals=sig)
    assert kpi.usage_count(ctx)["value"] == 1.0
    assert kpi.transformed_signals_count(ctx)["value"] == 1.0
    assert kpi.transformation_rate(ctx)["value"] == 50.0
    assert kpi.weak_signals_count(ctx)["subs"]["H4"] == 1.0


def test_family_e_and_f(cfg):
    arts = [art(i, source="The Hacker News", source_language="en", source_country="IN", source_type="presse") for i in range(3)]
    arts.append(art(9, source_country="FR", source_type="officielle", glossary_axes_added=["H3"]))
    ctx = ctx_for(cfg, arts)
    assert kpi.language_distribution(ctx)["subs"] == {"en": 75.0, "fr": 25.0}
    assert kpi.single_translation_share(ctx)["value"] == 100.0
    assert kpi.glossary_assisted_share(ctx)["value"] == 25.0
    assert kpi.max_source_share(ctx)["value"] == 75.0
    assert kpi.herfindahl_index(ctx)["value"] == 75**2 + 25**2
    assert kpi.french_share(ctx)["value"] == 25.0
    assert kpi.geo_distribution(ctx)["subs"]["IN"] == 75.0


# =========================================================================== thresholds & SLA (5.7)


@pytest.mark.parametrize(
    "value,sens,cible,seuil,expected",
    [(50, "hausse", 40, 20, "vert"), (30, "hausse", 40, 20, "orange"), (10, "hausse", 40, 20, "rouge"),
     (5, "baisse", 6, 24, "vert"), (12, "baisse", 6, 24, "orange"), (30, "baisse", 6, 24, "rouge"),
     (3, "info", None, None, "info"), (None, "hausse", 40, 20, "na")],
)  # fmt: skip
def test_evaluate(value, sens, cible, seuil, expected):
    assert kpi.evaluate(value, {"sens": sens, "cible": cible, "seuil_alerte": seuil}) == expected


def test_calculator_error_is_not_available(cfg, monkeypatch):
    def boom(ctx):
        raise RuntimeError("x")

    monkeypatch.setitem(kpi.CALCULATORS, "herfindahl_index", boom)
    values = kpi.compute_all(ctx_for(cfg, [art(1)]))
    assert values["F2_concentration_hhi"]["status"] == "na"


def _snap(ts, status, sub=None):
    item = {"value": 40.0, "status": status}
    if sub:
        return {"ts": iso(ts), "kpis": {"B2_qualite_source": {"value": 40.0, "status": status, "subs": {sub: item}}}}
    return {"ts": iso(ts), "kpis": {"B1_qualite_moyenne": item}}


def test_action_after_consecutive_weeks_then_resolved(cfg):
    weeks = [NOW - timedelta(weeks=w) for w in (3, 2, 1, 0)]
    hist = [_snap(t, "rouge", "Krebs on Security") for t in weeks[:3]]
    assert not any(a["status"] == "ouverte" for a in kpi.update_actions(cfg, hist, NOW).values())  # 3 weeks < 4
    hist.append(_snap(weeks[3], "orange", "Krebs on Security"))
    state = kpi.update_actions(cfg, hist, NOW)
    key = "B2_qualite_source|Krebs on Security"
    assert state[key]["status"] == "ouverte" and "Krebs on Security" in state[key]["action"]
    # same problem next run: still one action (no duplicate)
    state = kpi.update_actions(cfg, hist + [_snap(NOW, "rouge", "Krebs on Security")], NOW)
    assert sum(k.startswith("B2_qualite_source|Krebs") for k in state) == 1
    state = kpi.update_actions(cfg, hist + [_snap(NOW + timedelta(weeks=1), "vert", "Krebs on Security")], NOW)
    assert state[key]["status"] == "résolue"
    assert "Krebs on Security" in kpi.render_actions_md(state, NOW)


def test_consecutive_counter_skips_not_available():
    assert kpi.consecutive_off_target(["rouge", "orange", "na", "rouge"]) == 3
    assert kpi.consecutive_off_target(["rouge", "vert", "rouge"]) == 1


class FakeGitHub:
    def __init__(self):
        self.issues: list[dict] = []
        self.comments: list[tuple[int, str]] = []

    def ensure_label(self, *a, **k):
        pass

    def list_action_issues(self):
        out = {}
        for it in self.issues:
            m = issues.MARKER_RE.search(it["body"])
            out[m.group(1)] = it
        return out

    def create(self, title, body):
        self.issues.append({"number": len(self.issues) + 1, "title": title, "body": body, "state": "open"})

    def update(self, number, **fields):
        self.issues[number - 1].update(fields)

    def comment(self, number, body):
        self.comments.append((number, body))


def test_issue_sync_creates_once_then_closes():
    gh = FakeGitHub()
    action = {"key": "B1|", "kpi": "B1", "kpi_nom": "Qualité", "sujet": None, "action": "Revoir", "first_seen": iso(NOW),
              "last_seen": iso(NOW), "status": "ouverte", "periods": 4}  # fmt: skip
    issues.sync_actions({"B1|": action}, gh, "https://x/")
    issues.sync_actions({"B1|": action}, gh, "https://x/")
    assert len(gh.issues) == 1 and gh.issues[0]["state"] == "open"
    action.update(status="résolue", resolved=iso(NOW))
    issues.sync_actions({"B1|": action}, gh, "https://x/")
    assert gh.issues[0]["state"] == "closed" and gh.comments


# =========================================================================== usage journal (5.5)


def test_usage_yaml_and_validation(cfg):
    (cfg.data_dir / "usage.yaml").write_text(
        "entries:\n"
        "  - {article_id: 0123456789abcdef, type: alerte envoyée, entreprise: Client A, date: 2026-11-20}\n"
        "  - {article_id: bad, type: inconnu, date: 2026-11-20}\n"
        "  - {kind: signal, signal: Cairn, date: 2026-11-21}\n",
        encoding="utf-8",
    )
    entries = usage.read_yaml_usage(cfg)
    assert len(entries) == 2
    assert entries[0]["article_id"] == "0123456789abcdef" and entries[0]["company"] == "Client A"
    assert entries[1]["kind"] == "signal" and entries[1]["type"] == "hypothèse de transformation"


def test_issue_form_parsing_is_sanitised():
    body = (
        "### Identifiant de l'article\n\n0123456789abcdef\n\n### Type d'usage\n\ncorrectif appliqué\n\n"
        "### Entreprise concernée\n\n<script>alert(1)</script>ACME\n\n### Date\n\n_No response_\n\n"
        "### Commentaire\n\nsecret interne à ne pas publier"
    )
    issue = {"number": 7, "body": body, "created_at": "2026-11-22T10:00:00Z", "labels": [{"name": "usage"}]}
    e = usage.issue_to_entry(issue)
    assert e["type"] == "correctif appliqué" and e["date"] == "2026-11-22" and e["origin"] == "issue#7"
    assert "<" not in (e["company"] or "") and "secret" not in json.dumps(e)


def test_usage_without_token_uses_cache(cfg, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    (cfg.data_dir / "cache").mkdir(exist_ok=True)
    cached = [
        {
            "origin": "issue#1",
            "kind": "usage",
            "type": "note rédigée",
            "article_id": None,
            "signal": None,
            "company": None,
            "date": "2026-11-20",
        }
    ]
    (cfg.data_dir / "cache" / "usage_issues.json").write_text(json.dumps({"entries": cached}))
    assert usage.load_usage(cfg) == cached


# =========================================================================== history & archive (5.2)


def test_history_csv_export(cfg):
    kpi.append_history(
        cfg,
        {
            "ts": iso(NOW),
            "kpis": {"A1_pertinence_axe": {"value": 64.5, "status": "vert", "subs": {"H1": {"value": 91.2, "status": "vert"}}}},
        },
    )
    csv_text = kpi.history_csv(kpi.load_history(cfg), cfg)
    lines = csv_text.lstrip("﻿").splitlines()
    assert lines[0].startswith("horodatage;kpi_id") and len(lines) == 3
    assert "64,5" in lines[1] and "Dans la cible" in lines[1] and ";H1;" in lines[2]


def test_archive_upsert_and_compression(cfg):
    old = art(1, published="2024-01-15T10:00:00Z")
    new = art(2)
    archive.update_archive([new], cfg, NOW)
    archive.update_archive([new, art(3)], cfg, NOW)
    month_file = cfg.data_dir / "archive" / f"{NOW.strftime('%Y-%m')}.jsonl"
    assert len(month_file.read_text().splitlines()) == 2
    (cfg.data_dir / "archive" / "2024-01.jsonl").write_text(json.dumps(archive.light(old)) + "\n")
    archive.update_archive([new], cfg, NOW)
    gz = cfg.data_dir / "archive" / "2024-01.jsonl.gz"
    assert gz.exists() and not (cfg.data_dir / "archive" / "2024-01.jsonl").exists()
    assert json.loads(gzip.open(gz).read().decode())["id"] == old["id"]
    assert "excerpt" not in json.loads(month_file.read_text().splitlines()[0])


# =========================================================================== end-to-end


def test_pipeline_end_to_end_quality_layer(env):
    from src import newsletter
    from src.pipeline import run

    assert run(fixtures=env["feeds"]) == 0
    assert run(fixtures=env["feeds"]) == 0  # second run: history grows, no duplicate actions
    data = env["data"]
    history = kpi.load_history(load_config())
    assert len(history) == 2
    latest = json.loads((data / "kpi_latest.json").read_text())
    ids = {k["id"] for k in latest["kpis"]}
    assert {
        "A1_pertinence_axe",
        "B2_qualite_source",
        "C1_signaux_faibles",
        "D3_taux_transformation",
        "E2_traduction_une_etape",
        "F2_concentration_hhi",
    } <= ids
    arts = json.loads((data / "articles.json").read_text())["articles"]
    assert all(a["reliability"] in quality.RELIABILITY_LEVELS for a in arts)
    assert all("translation_steps" in a and a["summary_from"] == "original" for a in arts)
    assert (data / "improvement_actions.md").exists() and (data / "weak_signals.md").exists()
    assert list((data / "archive").glob("*.jsonl"))
    site = json.loads((env["public"] / "kpi.json").read_text())
    assert site["available"] and site["sources"] and site["biases"] and site["objectives"]["H3"]["cible_hebdo"]
    assert (env["public"] / "kpi_history.csv").read_text().count("\n") > 10
    articles_json = json.loads((env["public"] / "articles.json").read_text())
    assert articles_json["site"]["repository"] == "AFUZ18/veille-cyber"
    assert all("reliability" in a for a in articles_json["articles"])
    # Monday e-mail gets the « Santé de la veille » block
    newsletter.main([])
    md = next((data / "weekly").glob("*-W*.md")).read_text()
    assert "## Santé de la veille" in md


def test_quality_layer_failure_never_blocks_pipeline(env, monkeypatch):
    from src.pipeline import run

    def boom(*a, **k):
        raise RuntimeError("panne simulée")

    monkeypatch.setattr("src.kpi.run", boom)
    assert run(fixtures=env["feeds"]) == 0
    assert json.loads((env["public"] / "kpi.json").read_text()) == {"available": False}
    assert (env["public"] / "index.html").exists()


def test_kpi_documentation_is_up_to_date():
    import subprocess
    import sys

    root = Path(__file__).resolve().parent.parent
    res = subprocess.run([sys.executable, str(root / "scripts" / "kpi_doc.py"), "--check"], capture_output=True, text=True)
    assert res.returncode == 0, res.stdout


def test_every_kpi_has_a_calculator_and_smart_fields():
    cfg = load_config()
    for k in cfg.kpi["kpis"]:
        assert k["calcul"] in kpi.CALCULATORS, k["id"]
        assert set(k["smart"]) == {"specifique", "mesurable", "atteignable", "realiste", "temporel"}, k["id"]
        for field in ("nom", "famille", "formule", "unite", "periode", "sens", "responsable"):
            assert field in k, (k["id"], field)


def test_every_feed_has_quality_metadata():
    cfg = load_config()
    names = set(cfg.sources_quality["sources"])
    missing = [f["name"] for f in cfg.feeds if f["name"] not in names]
    assert not missing, missing
