"""End-to-end pipeline: collect → classify → score → summarise → save → build site.

python -m src.pipeline                      # normal run (network)
python -m src.pipeline --fixtures DIR       # offline run on local feed files (tests / demo)
python -m src.pipeline --no-build           # update data only
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import feedparser

from . import archive, issues, kpi, quality, signals, usage
from .build_site import build_site
from .classify import classify
from .collect import apply_retention, collect, deduplicate, normalise_entry
from .common import ARTICLES_FILE, FEEDS_STATUS_FILE, Config, iso, load_config, read_json, setup_logging, utcnow, write_json
from .score import score_articles
from .summarize import summarise

log = logging.getLogger("veille.pipeline")


def collect_from_fixtures(cfg: Config, existing: list[dict], fixtures: Path) -> tuple[list[dict], list[dict], int]:
    """Same as collect() but reads <fixtures>/<feed name slug>.xml instead of the network."""
    now = utcnow()
    c = cfg.settings["collect"]
    incoming, statuses = [], []
    for feed in (f for f in cfg.feeds if f.get("enabled", True)):
        slug = "".join(ch if ch.isalnum() else "-" for ch in feed["name"].lower()).strip("-")
        path = fixtures / f"{slug}.xml"
        status = {"name": feed["name"], "url": feed["url"], "checked": iso(now), "ok": False, "entries": 0}
        if path.exists():
            parsed = feedparser.parse(path.read_bytes())
            arts = [a for e in parsed.entries if (a := normalise_entry(e, feed, c["excerpt_max_chars"], now))]
            incoming += arts
            status.update(ok=True, entries=len(arts))
            if arts:
                status["latest"] = max(a["published"] for a in arts)
        else:
            status["error"] = "pas de fichier de test"
        statuses.append(status)
    merged, added = deduplicate(existing, incoming, c["title_similarity_threshold"], c["dedup_window_days"])
    return apply_retention(merged, c["retention_days"], now), statuses, added


def quality_layer(articles: list[dict], cfg: Config, statuses: list[dict], now) -> dict | None:
    """Quality / KPI layer (chantier 2). Any error is logged and never stops the pipeline."""
    try:
        quality.annotate(articles, cfg)
        usage_entries = usage.load_usage(cfg)
        used_ids = {u["article_id"] for u in usage_entries if u.get("article_id")}
        scores = quality.source_scores(articles, cfg, now, used_ids)
        weak = signals.detect_weak_signals(articles, cfg, now)
        year, week, _ = now.isocalendar()
        md_path = cfg.data_dir / "weak_signals.md"
        existing_md = md_path.read_text("utf-8") if md_path.exists() else ""
        md_path.write_text(signals.render_weak_signals_md(existing_md, weak, f"{year}-W{week:02d}"), "utf-8")
        weeks = int((cfg.kpi or {}).get("signaux_faibles", {}).get("semaines_reference", 4))
        covered = signals.reference_weeks(articles, now, weeks)
        warmup = None if covered >= 1 else f"{covered:.1f} semaine(s) d'historique sur 1 requise"
        ctx = kpi.KpiContext(articles=articles, cfg=cfg, now=now, feeds_status=statuses, usage=usage_entries,
                             signals=weak, source_scores=scores, signals_warmup=warmup)  # fmt: skip
        report = kpi.run(ctx)
        archive.update_archive(articles, cfg, now)
        issues.maybe_sync({a["key"]: a for a in report["actions"]}, cfg.site_url)
        return report
    except Exception:
        log.exception("Couche qualité / KPI en échec : le site est publié sans mise à jour des KPI")
        return None


def run(fixtures: Path | None = None, build: bool = True, collect_feeds: bool = True) -> int:
    started = time.monotonic()
    cfg = load_config()
    store_path = cfg.data_dir / ARTICLES_FILE
    existing = read_json(store_path, {}).get("articles", [])
    log.info("État initial : %d articles", len(existing))

    if fixtures:
        articles, statuses, added = collect_from_fixtures(cfg, existing, fixtures)
    elif collect_feeds:
        articles, statuses, added = collect(cfg, existing)
    else:  # rebuild from stored data (after a configuration change, or for tests)
        articles, added = existing, 0
        statuses = read_json(cfg.data_dir / FEEDS_STATUS_FILE, {}).get("feeds", [])

    articles = classify(articles, cfg)
    articles = score_articles(articles, cfg)
    articles = summarise(articles, cfg)
    articles.sort(key=lambda a: a["published"], reverse=True)

    now = utcnow()
    report = quality_layer(articles, cfg, statuses, now)
    write_json(store_path, {"updated": iso(now), "count": len(articles), "articles": articles})
    write_json(cfg.data_dir / FEEDS_STATUS_FILE, {"checked": iso(now), "feeds": statuses})
    if build:
        build_site(articles, cfg, statuses, now, report)

    failed = [s["name"] for s in statuses if not s["ok"]]
    log.info(
        "Terminé en %.0f s : %d nouveaux, %d au total, %d flux en erreur%s",
        time.monotonic() - started,
        added,
        len(articles),
        len(failed),
        f" ({', '.join(failed)})" if failed else "",
    )
    if statuses and len(failed) == len(statuses):
        log.error("Tous les flux ont échoué : problème réseau probable")
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline de veille cyber")
    parser.add_argument("--fixtures", type=Path, help="dossier de flux locaux (mode hors ligne)")
    parser.add_argument("--no-build", action="store_true", help="ne pas régénérer le site")
    parser.add_argument("--no-collect", action="store_true", help="recalculer à partir des données existantes, sans collecte")
    args = parser.parse_args(argv)
    setup_logging()
    return run(fixtures=args.fixtures, build=not args.no_build, collect_feeds=not args.no_collect)


if __name__ == "__main__":
    sys.exit(main())
