"""Static site generation: public/index.html + articles.json + feed.xml.

The browser never calls third-party services: everything it needs is in
articles.json, served from the same origin. All feed-derived text is escaped
(XML here, DOM textContent in the page) — see site/index.html.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import date, datetime
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from .common import ROOT, THEME_IDS, Config, iso, parse_iso, utcnow
from .simple import home_payload, render_template, simple_reasons

log = logging.getLogger("veille.build")

TEMPLATE_DIR = ROOT / "site"

PUBLIC_FIELDS = (
    "id", "title", "url", "source", "published", "language", "themes", "sectors", "is_event",
    "cves", "kev", "kev_ransomware", "cve_details", "criticality", "level", "criticality_reasons",
    "relevance", "excerpt", "summary", "why", "action", "action_type", "ai_tags", "summary_source", "also_in",
    # quality layer
    "reliability", "checks", "source_language", "translation_steps", "summary_from", "glossary_concepts",
    "corroboration_sources", "domain",
    # plain-language layer
    "why_simple", "todo_simple", "official",
)  # fmt: skip


def safe_url(url: str) -> str:
    return url if isinstance(url, str) and url.startswith(("https://", "http://")) else ""


def _as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def events_payload(events: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    out = []
    for ev in events:
        try:
            start = _as_date(ev["start"])
            end = _as_date(ev.get("end", ev["start"]))
        except (KeyError, ValueError):
            log.warning("events.yaml : dates invalides pour %s", ev.get("name"))
            continue
        out.append(
            {
                "name": str(ev.get("name", "")),
                "start": start.isoformat(),
                "end": end.isoformat(),
                "location": str(ev.get("location", "")),
                "url": safe_url(ev.get("url", "")),
                "confirmed": bool(ev.get("confirmed", False)),
                "description": str(ev.get("description", "")),
                "past": end < today,
            }
        )
    return sorted(out, key=lambda e: e["start"])


def repository(cfg: Config) -> str:
    """owner/name of the GitHub repository (for the usage issue forms)."""
    import os
    import re

    repo = os.environ.get("GITHUB_REPOSITORY") or cfg.settings["site"].get("repository", "")
    return repo if re.fullmatch(r"[\w.-]+/[\w.-]+", repo or "") else ""


def kpi_payload(report: dict[str, Any] | None, cfg: Config) -> dict[str, Any]:
    """Data of the « KPI & qualité » tab (public/kpi.json)."""
    if not report:
        return {"available": False}
    values = {k["id"]: k for k in report["kpis"]}
    objectives = {
        t: {"label": spec.get("label", t), **(spec.get("objectifs") or {})}
        for t, spec in cfg.themes.get("themes", {}).items()
        if t in THEME_IDS
    }
    biases = []
    for b in (cfg.bias or {}).get("biais", []) or []:
        ind = values.get(b.get("indicateur") or "")
        biases.append(
            {
                **b,
                "indicator_name": ind["nom"] if ind else None,
                "indicator_value": ind["value"] if ind else None,
                "indicator_unit": ind["unite"] if ind else None,
                "indicator_status": ind["status_label"] if ind else None,
            }
        )
    return {
        "available": True,
        **report,
        "objectives": objectives,
        "biases": biases,
        "checklist": (cfg.checklist or {}).get("criteres", []),
        "glossary_concepts": len((cfg.glossary or {}).get("concepts", []) or []),
    }


def site_payload(articles: list[dict[str, Any]], cfg: Config, feeds_status: list[dict], now: datetime) -> dict:
    limit = cfg.settings["site"]["max_articles_on_site"]
    ordered = sorted(articles, key=lambda a: a["published"], reverse=True)[:limit]
    for a in ordered:
        a["why_simple"], a["todo_simple"] = simple_reasons(a, cfg.ui or {})
    public = [{k: a.get(k) for k in PUBLIC_FIELDS} for a in ordered]
    labels = {t: cfg.themes["themes"][t]["label"] for t in THEME_IDS}
    return {
        "generated_at": iso(now),
        "site": {
            "title": cfg.settings["site"]["title"],
            "subtitle": cfg.settings["site"]["subtitle"],
            "url": cfg.site_url,
            "repository": repository(cfg),
        },
        "theme_labels": labels,
        "counts": {t: sum(1 for a in public if t in (a["themes"] or [])) for t in THEME_IDS}
        | {"EVENTS": sum(1 for a in public if a["is_event"]), "ALL": len(public)},
        "events": events_payload(cfg.events, now.date()),
        "feeds_status": [{k: s.get(k) for k in ("name", "ok", "entries", "error", "latest", "checked")} for s in feeds_status],
        "articles": public,
        "home": home_payload(ordered, cfg, now),
        "ui": cfg.ui or {},
        "glossary": (cfg.glossary_ui or {}).get("termes", {}),
    }


def build_rss(articles: list[dict[str, Any]], cfg: Config, now: datetime) -> str:
    """RSS 2.0 of the most recent relevant items, every field XML-escaped."""
    n = cfg.settings["site"]["feed_items"]
    items = sorted(articles, key=lambda a: a["published"], reverse=True)[:n]
    site_url = cfg.site_url
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        f"<title>{xml_escape(cfg.settings['site']['title'])}</title>",
        f"<link>{xml_escape(site_url)}</link>",
        f'<atom:link href="{xml_escape(site_url)}feed.xml" rel="self" type="application/rss+xml"/>',
        f"<description>{xml_escape(cfg.settings['site']['subtitle'])}</description>",
        "<language>fr</language>",
        f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>",
    ]
    for a in items:
        url = safe_url(a["url"])
        if not url:
            continue
        labels = ", ".join(a.get("themes", []))
        body = f"[{a['level']}] [{labels}] {a.get('summary') or ''}"
        if a.get("why"):
            body += f" — Pourquoi c'est important : {a['why']}"
        title = "[" + a["level"] + "] " + a["title"]
        parts += [
            "<item>",
            f"<title>{xml_escape(title)}</title>",
            f"<link>{xml_escape(url)}</link>",
            f'<guid isPermaLink="false">{xml_escape(a["id"])}</guid>',
            f"<pubDate>{format_datetime(parse_iso(a['published']))}</pubDate>",
            f'<source url="{xml_escape(url)}">{xml_escape(a["source"])}</source>',
            *[f"<category>{xml_escape(t)}</category>" for t in a.get("themes", [])],
            f"<description>{xml_escape(body)}</description>",
            "</item>",
        ]
    parts += ["</channel>", "</rss>", ""]
    return "\n".join(parts)


def build_site(
    articles: list[dict[str, Any]],
    cfg: Config,
    feeds_status: list[dict],
    now: datetime | None = None,
    kpi_report: dict[str, Any] | None = None,
) -> Path:
    now = now or utcnow()
    out = ROOT / cfg.settings["site"]["output_dir"]
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    payload = site_payload(articles, cfg, feeds_status, now)

    (out / "articles.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), "utf-8")
    template = (TEMPLATE_DIR / "index.html").read_text("utf-8")
    page = render_template(template, cfg)
    (out / "index.html").write_text(page, "utf-8")
    (out / "feed.xml").write_text(build_rss(articles, cfg, now), "utf-8")
    (out / "kpi.json").write_text(json.dumps(kpi_payload(kpi_report, cfg), ensure_ascii=False, separators=(",", ":")), "utf-8")
    from .kpi import history_csv, load_history  # local import: avoids a cycle at module load

    (out / "kpi_history.csv").write_text(history_csv(load_history(cfg), cfg), "utf-8")
    (out / ".nojekyll").write_text("", "utf-8")
    if (TEMPLATE_DIR / "favicon.svg").exists():
        shutil.copy(TEMPLATE_DIR / "favicon.svg", out / "favicon.svg")
    log.info("Site généré dans %s (%d articles)", out, len(payload["articles"]))
    return out
