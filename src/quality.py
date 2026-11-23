"""Source quality, corroboration, reliability badge and translation tracking.

Everything is computed from data already collected (no extra network call):
- approved domains and source metadata come from config/sources_quality.yaml;
- corroboration groups articles describing the same information (title duplicates
  merged at collection time + articles sharing a CVE within a short window) and
  counts independent organisations;
- the reliability badge applies the automatic checks of
  config/verification_checklist.yaml.
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from .common import Config, find_keywords, parse_iso

log = logging.getLogger("veille.quality")

RELIABILITY_LEVELS = ("Vérifié", "À recouper", "Source non référencée")


# --------------------------------------------------------------------------- source metadata


def source_meta(name: str, cfg: Config) -> dict[str, Any]:
    """Quality metadata of a source, falling back to the `default` entry."""
    sq = cfg.sources_quality or {}
    default = {"ae": 50, "ir": 50, "pr": 50, "type": "communauté", "country": "INT"} | (sq.get("default") or {})
    entry = (sq.get("sources") or {}).get(name)
    meta = default | (entry or {})
    meta.setdefault("org", name)
    meta["referenced"] = entry is not None
    return meta


def credibility(meta: dict[str, Any], weights: dict[str, float]) -> float:
    """Composite credibility = w_ae*AE + w_ir*IR + w_pr*PR (0-100)."""
    return round(sum(float(meta.get(k, 50)) * float(w) for k, w in weights.items()), 1)


def approved_domains(cfg: Config) -> list[str]:
    sq = cfg.sources_quality or {}
    out = [d.lower() for d in sq.get("extra_approved_domains", []) or []]
    for entry in (sq.get("sources") or {}).values():
        out += [d.lower() for d in entry.get("domains", []) or []]
    return out


def domain_of(url: str) -> str:
    return urlsplit(url).netloc.lower().split(":")[0]


def domain_approved(url: str, approved: list[str]) -> bool:
    """True if url's host (or host/path prefix) is covered by an approved entry.

    "example.org" covers example.org and any subdomain; "github.com/org" covers that path only.
    """
    parts = urlsplit(url)
    host = parts.netloc.lower().split(":")[0]
    path = parts.path.lower()
    for entry in approved:
        dom, _, prefix = entry.partition("/")
        host_ok = host == dom or host.endswith("." + dom)
        if host_ok and (not prefix or path.startswith("/" + prefix.lower().rstrip("/"))):
            return True
    return False


# --------------------------------------------------------------------------- clusters (same information)


def mentions(article: dict[str, Any]) -> list[tuple[str, datetime | None]]:
    """(source, publication date) of the article and of every echo merged into it."""
    out: list[tuple[str, datetime | None]] = [(article["source"], parse_iso(article["published"]))]
    dated = article.get("also_in_published") or {}
    for src in article.get("also_in", []) or []:
        out.append((src, parse_iso(dated[src]) if src in dated else None))
    return out


def build_clusters(articles: list[dict[str, Any]], window_days: int) -> list[list[int]]:
    """Group article indices describing the same information: shared CVE within `window_days`.

    (Title duplicates are already merged into a single article by the collector.)
    """
    parent = list(range(len(articles)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_cve: dict[str, list[int]] = defaultdict(list)
    for i, a in enumerate(articles):
        for cve in a.get("cves", []) or []:
            by_cve[cve].append(i)
    window = timedelta(days=window_days)
    for idxs in by_cve.values():
        idxs = sorted(idxs, key=lambda i: articles[i]["published"])
        for a, b in zip(idxs, idxs[1:]):
            if parse_iso(articles[b]["published"]) - parse_iso(articles[a]["published"]) <= window:
                parent[find(b)] = find(a)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(articles)):
        groups[find(i)].append(i)
    return list(groups.values())


def annotate_clusters(articles: list[dict[str, Any]], cfg: Config) -> None:
    """Set corroborating organisations, cluster size and first-publisher flags on each article."""
    q = cfg.settings.get("quality", {})
    for idxs in build_clusters(articles, q.get("corroboration_window_days", 4)):
        all_mentions = [m for i in idxs for m in mentions(articles[i])]
        orgs = sorted({source_meta(src, cfg)["org"] for src, _ in all_mentions})
        sources = sorted({src for src, _ in all_mentions})
        dated = [d for _, d in all_mentions if d is not None]
        first = min(dated) if dated else None
        first_sources = sorted({src for src, d in all_mentions if d is not None and d == first})
        for i in idxs:
            a = articles[i]
            a["corroboration_orgs"] = orgs
            a["corroboration_sources"] = sources
            a["first_publishers"] = first_sources


# --------------------------------------------------------------------------- reliability badge


def run_checks(article: dict[str, Any], cfg: Config, approved: list[str]) -> dict[str, bool | None]:
    """Automatic verification checks. None = not applicable / unknown (counts as passed)."""
    q = cfg.settings.get("quality", {})
    cl = cfg.checklist or {}
    meta = source_meta(article["source"], cfg)
    cred = credibility(meta, q.get("credibility_weights", {"ae": 0.3, "ir": 0.4, "pr": 0.3}))
    min_orgs = q.get("min_independent_sources", 2)

    cves = article.get("cves", []) or []
    details = article.get("cve_details", {}) or {}
    cve_state: bool | None = None
    if cves:
        known = [
            bool(d.get("kev")) or d.get("cvss") is not None or d.get("nvd_found") is True
            for d in (details.get(c, {}) for c in cves)
        ]
        refuted = [details.get(c, {}).get("nvd_found") is False and not details.get(c, {}).get("kev") for c in cves]
        cve_state = True if all(known) else (False if any(refuted) else None)

    n_orgs = len(article.get("corroboration_orgs") or [meta["org"]])
    corroborated = n_orgs >= min_orgs or cred >= float(cl.get("credibilite_suffisante", 85))
    sensational = bool(find_keywords(article.get("title", ""), cl.get("formulations_sensationnalistes", []) or [])) or (
        "!!!" in article.get("title", "")
    )
    return {
        "approved_domain": domain_approved(article["url"], approved),
        "https": article["url"].startswith("https://"),
        "plausible_date": not article.get("date_adjusted", False),
        "cves_confirmed": cve_state,
        "corroborated": corroborated,
        "not_sensational": not sensational,
    }


def reliability_level(checks: dict[str, bool | None], checklist: dict[str, Any]) -> str:
    """Badge: unreferenced if the domain check fails; verified if every automatic
    blocking/major check passes (None = passed); otherwise « À recouper »."""
    if checks.get("approved_domain") is False:
        return "Source non référencée"
    for crit in checklist.get("criteres", []) or []:
        ctrl = crit.get("controle")
        if crit.get("methode") != "automatique" or not ctrl or crit.get("importance") not in ("bloquant", "majeur"):
            continue
        if checks.get(ctrl) is False:
            return "À recouper"
    return "Vérifié"


# --------------------------------------------------------------------------- pipeline step


def annotate(articles: list[dict[str, Any]], cfg: Config) -> list[dict[str, Any]]:
    """Add quality fields to every article (in place)."""
    approved = approved_domains(cfg)
    annotate_clusters(articles, cfg)
    for a in articles:
        meta = source_meta(a["source"], cfg)
        a["source_language"] = a.get("source_language") or a.get("language", "en")
        # Single-step translation: the French summary is produced directly from the original
        # title + excerpt (never from a translation or a previous summary).
        a["summary_from"] = "original"
        a["translation_steps"] = 1 if a.get("summary_source") == "ia" and a["source_language"] != "fr" else 0
        a["domain"] = domain_of(a["url"])
        a["source_type"] = meta.get("type")
        a["source_country"] = meta.get("country")
        checks = run_checks(a, cfg, approved)
        a["checks"] = checks
        a["reliability"] = reliability_level(checks, cfg.checklist or {})
    counts = {lvl: sum(1 for a in articles if a["reliability"] == lvl) for lvl in RELIABILITY_LEVELS}
    log.info("Fiabilité : %s", ", ".join(f"{k}={v}" for k, v in counts.items()))
    return articles


# --------------------------------------------------------------------------- time to receive information


def ttri_delays(articles: list[dict[str, Any]], cfg: Config) -> dict[str, list[float]]:
    """Publication-to-collection delays (hours) per source.

    Excluded: corrected dates, delays above `ttri_ignore_above_hours`, and the backlog
    of the very first collection of each source (old entries fetched on day one would
    otherwise inflate the median).
    """
    cap = cfg.settings.get("quality", {}).get("ttri_ignore_above_hours", 168)
    first_collect: dict[str, str] = {}
    for a in articles:
        if a.get("collected"):
            first_collect[a["source"]] = min(first_collect.get(a["source"], a["collected"]), a["collected"])
    out: dict[str, list[float]] = defaultdict(list)
    for a in articles:
        if not a.get("collected") or a.get("date_adjusted"):
            continue
        delay = (parse_iso(a["collected"]) - parse_iso(a["published"])).total_seconds() / 3600
        backlog = a["collected"] == first_collect.get(a["source"]) and delay > 12
        if 0 <= delay <= cap and not backlog:
            out[a["source"]].append(delay)
    return out


# --------------------------------------------------------------------------- source quality score


def _linear(value: float, good: float, bad: float) -> float:
    """100 at/under `good`, 0 at/over `bad`, linear in between."""
    if value <= good:
        return 100.0
    if value >= bad:
        return 0.0
    return round(100 * (bad - value) / (bad - good), 1)


def source_scores(
    articles: list[dict[str, Any]],
    cfg: Config,
    now: datetime,
    used_ids: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Source Quality Score, its components and the Source Authority Index, per enabled source.

    Components are None when the source published nothing in the window (KPI « non disponible »).
    """
    q = cfg.settings.get("quality", {})
    params = (cfg.kpi or {}).get("parametres", {})
    threshold = params.get("seuil_pertinence", 35)
    window = now - timedelta(days=params.get("fenetre_sources_jours", 30))
    used_ids = used_ids or set()
    wq = q.get("sqs_weights", {"pertinence": 0.3, "credibilite": 0.25, "nouveaute": 0.25, "efficacite": 0.2})
    wc = q.get("credibility_weights", {"ae": 0.3, "ir": 0.4, "pr": 0.3})
    we = q.get("efficiency_weights", {"rapidite": 0.5, "utilite": 0.5})
    wa = q.get("authority_weights", {"credibilite": 0.5, "reprise": 0.25, "nouveaute": 0.25})
    min_orgs = q.get("min_independent_sources", 2)

    recent = [a for a in articles if parse_iso(a["published"]) >= window]
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    echoed_in: dict[str, list[dict[str, Any]]] = defaultdict(list)  # articles a source echoed (also_in)
    for a in recent:
        by_source[a["source"]].append(a)
        for src in a.get("also_in", []) or []:
            echoed_in[src].append(a)

    all_delays = ttri_delays(recent, cfg)
    out: dict[str, dict[str, Any]] = {}
    for feed in cfg.feeds:
        if not feed.get("enabled", True):
            continue
        name = feed["name"]
        meta = source_meta(name, cfg)
        cred = credibility(meta, wc)
        own = by_source.get(name, [])
        appearances = own + echoed_in.get(name, [])
        row: dict[str, Any] = {
            "source": name,
            "org": meta["org"],
            "type": meta.get("type"),
            "country": meta.get("country"),
            "referenced": meta["referenced"],
            "articles": len(own),
            "credibilite": cred,
            "pertinence": None,
            "nouveaute": None,
            "efficacite": None,
            "ttri_h": None,
            "reprise": None,
            "sqs": None,
            "authority": None,
        }
        if own:
            row["pertinence"] = round(100 * sum(a.get("relevance", 0) >= threshold for a in own) / len(own), 1)
            firsts = sum(name in (a.get("first_publishers") or [a["source"]]) for a in appearances)
            row["nouveaute"] = round(100 * firsts / len(appearances), 1)
            delays = all_delays.get(name, [])
            useful = sum(
                a.get("level", "Info") != "Info" or a.get("relevance", 0) >= threshold or a["id"] in used_ids for a in own
            )
            utility = 100 * useful / len(own)
            if delays:
                row["ttri_h"] = round(statistics.median(delays), 1)
                speed = _linear(row["ttri_h"], q.get("ttri_good_hours", 6), q.get("ttri_bad_hours", 72))
                row["efficacite"] = round(we["rapidite"] * speed + we["utilite"] * utility, 1)
            else:
                row["efficacite"] = round(utility, 1)
            row["reprise"] = round(100 * sum(len(a.get("corroboration_orgs") or []) >= min_orgs for a in own) / len(own), 1)
            row["sqs"] = round(
                wq["pertinence"] * row["pertinence"]
                + wq["credibilite"] * cred
                + wq["nouveaute"] * row["nouveaute"]
                + wq["efficacite"] * row["efficacite"],
                1,
            )
            row["authority"] = round(
                wa["credibilite"] * cred + wa["reprise"] * row["reprise"] + wa["nouveaute"] * row["nouveaute"], 1
            )
        out[name] = row
    return out
