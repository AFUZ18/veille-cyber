"""Criticality and relevance scoring.

Criticality (0-100) combines: CISA KEV membership, CVSS (NVD), EPSS (FIRST),
critical keywords and official sources. Relevance (0-100) combines themes,
sector/technology keywords, feed priority and criticality. All weights and
thresholds live in config/settings.yaml (sections `criticality`, `relevance`).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import timedelta
from typing import Any

from .common import (
    CVE_CACHE_FILE,
    KEV_CACHE_FILE,
    THEME_IDS,
    Config,
    find_keywords,
    http_get,
    iso,
    parse_iso,
    read_json,
    utcnow,
    write_json,
)

log = logging.getLogger("veille.score")

LEVELS = ("Critique", "Élevé", "Moyen", "Info")


def offline() -> bool:
    return os.environ.get("VEILLE_OFFLINE", "") == "1"


# --------------------------------------------------------------------------- enrichment sources


def load_kev(cfg: Config) -> dict[str, dict[str, Any]]:
    """CISA Known Exploited Vulnerabilities, cached on disk. Returns {CVE: info}."""
    e = cfg.settings["enrichment"]
    path = cfg.data_dir / KEV_CACHE_FILE
    cache = read_json(path, {})
    fresh = cache.get("fetched") and utcnow() - parse_iso(cache["fetched"]) < timedelta(hours=e["kev_cache_hours"])
    if not fresh and not offline():
        try:
            resp = http_get(e["kev_url"], user_agent=cfg.settings["collect"]["user_agent"], timeout=30, retries=2)
            resp.raise_for_status()
            vulns = resp.json().get("vulnerabilities", [])
            cache = {
                "fetched": iso(utcnow()),
                "items": {
                    v["cveID"]: {
                        "vendor": v.get("vendorProject", ""),
                        "product": v.get("product", ""),
                        "added": v.get("dateAdded", ""),
                        "ransomware": v.get("knownRansomwareCampaignUse", "") == "Known",
                    }
                    for v in vulns
                    if v.get("cveID")
                },
            }
            write_json(path, cache)
            log.info("Catalogue CISA KEV : %d CVE", len(cache["items"]))
        except Exception as exc:
            log.warning("CISA KEV indisponible (%s) : utilisation du cache existant", exc)
    return cache.get("items", {})


def enrich_cves(cves: set[str], cfg: Config) -> dict[str, dict[str, Any]]:
    """Fetch EPSS (batch) and CVSS (NVD, rate-limited) for CVEs not in the fresh cache."""
    e = cfg.settings["enrichment"]
    ua = cfg.settings["collect"]["user_agent"]
    path = cfg.data_dir / CVE_CACHE_FILE
    cache: dict[str, dict[str, Any]] = read_json(path, {})
    ttl = timedelta(days=e["cve_cache_days"])
    stale = sorted(c for c in cves if c not in cache or utcnow() - parse_iso(cache[c]["fetched"]) > ttl)
    if offline() or not stale:
        return cache

    # EPSS: up to 100 CVEs per request
    if e.get("epss_enabled", True):
        for i in range(0, len(stale), 100):
            chunk = stale[i : i + 100]
            try:
                resp = http_get(e["epss_url"], user_agent=ua, params={"cve": ",".join(chunk)}, timeout=20)
                resp.raise_for_status()
                for row in resp.json().get("data", []):
                    cache.setdefault(row["cve"], {})["epss"] = float(row.get("epss", 0))
            except Exception as exc:
                log.warning("EPSS indisponible : %s", exc)
                break

    # NVD: one request per CVE, respecting the public rate limit
    if e.get("nvd_enabled", True):
        api_key = os.environ.get("NVD_API_KEY", "")
        delay = e["nvd_delay_seconds_with_key"] if api_key else e["nvd_delay_seconds"]
        headers = {"apiKey": api_key} if api_key else {}
        for n, cve in enumerate(stale[: e["nvd_max_lookups_per_run"]]):
            if n:
                time.sleep(delay)
            try:
                resp = http_get(e["nvd_url"], user_agent=ua, params={"cveId": cve}, headers=headers, timeout=20)
                if resp.status_code == 200:
                    payload = resp.json()
                    entry = cache.setdefault(cve, {})
                    entry["cvss"] = _nvd_cvss(payload)
                    entry["nvd_found"] = bool(payload.get("vulnerabilities"))
            except Exception as exc:
                log.warning("NVD indisponible pour %s : %s", cve, exc)
                break
    for cve in stale:
        if cve in cache:
            cache[cve]["fetched"] = iso(utcnow())
    write_json(path, cache)
    return cache


def _nvd_cvss(payload: dict[str, Any]) -> float | None:
    """Best available CVSS base score (v4 > v3.1 > v3.0 > v2)."""
    for vuln in payload.get("vulnerabilities", []):
        metrics = vuln.get("cve", {}).get("metrics", {})
        for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            for m in metrics.get(key, []):
                score = m.get("cvssData", {}).get("baseScore")
                if score is not None:
                    return float(score)
    return None


# --------------------------------------------------------------------------- scoring


def criticality_level(score: int, levels: dict[str, int]) -> str:
    if score >= levels["critical"]:
        return "Critique"
    if score >= levels["high"]:
        return "Élevé"
    if score >= levels["medium"]:
        return "Moyen"
    return "Info"


def compute_criticality(
    article: dict[str, Any], kev: dict[str, Any], cve_info: dict[str, dict[str, Any]], cfg: dict[str, Any]
) -> tuple[int, str, list[str]]:
    """Return (score 0-100, level, human-readable reasons)."""
    reasons: list[str] = []
    score = 0.0
    cves = article.get("cves", [])
    kev_hits = [c for c in cves if c in kev]
    if kev_hits:
        score += cfg["kev_points"]
        reasons.append(f"CISA KEV ({', '.join(kev_hits[:3])})")
    cvss = max((cve_info.get(c, {}).get("cvss") or 0 for c in cves), default=0)
    if cvss:
        score += cvss / 10 * cfg["cvss_weight"]
        reasons.append(f"CVSS {cvss:.1f}")
    epss = max((cve_info.get(c, {}).get("epss") or 0 for c in cves), default=0)
    if epss:
        score += epss * cfg["epss_weight"]
        reasons.append(f"EPSS {epss:.0%}")
    text = f"{article.get('title', '')} {article.get('excerpt', '')}"
    kws = find_keywords(text, cfg["keywords"])
    if kws:
        score += min(len(kws) * cfg["keyword_points"], cfg["keyword_cap"])
        reasons.append("mots-clés : " + ", ".join(kws[:3]))
    if any(src.lower() in article.get("source", "").lower() for src in cfg["official_sources"]):
        score += cfg["official_source_points"]
        reasons.append("source officielle")
    final = int(round(min(score, 100)))
    return final, criticality_level(final, cfg["levels"]), reasons


def compute_relevance(article: dict[str, Any], criticality: int, cfg: dict[str, Any]) -> int:
    themes = [t for t in article.get("themes", []) if t in THEME_IDS]
    score = min(len(themes) * cfg["theme_points"], cfg["theme_cap"])
    score += min(len(article.get("sectors", [])) * cfg["sector_points"], cfg["sector_cap"])
    priority_points = {int(k): v for k, v in cfg["priority_points"].items()}
    score += priority_points.get(int(article.get("feed_priority", 3)), 0)
    score += criticality * cfg["criticality_factor"]
    return int(round(min(score, 100)))


def score_articles(articles: list[dict[str, Any]], cfg: Config) -> list[dict[str, Any]]:
    kev = load_kev(cfg)
    all_cves = {c for a in articles for c in a.get("cves", [])}
    cve_info = enrich_cves(all_cves, cfg)
    for art in articles:
        crit, level, reasons = compute_criticality(art, kev, cve_info, cfg.settings["criticality"])
        art["criticality"] = crit
        art["level"] = level
        art["criticality_reasons"] = reasons
        art["kev"] = any(c in kev for c in art.get("cves", []))
        art["kev_ransomware"] = any(kev.get(c, {}).get("ransomware") for c in art.get("cves", []))
        art["cve_details"] = {
            c: {k: cve_info.get(c, {}).get(k) for k in ("cvss", "epss", "nvd_found")} | {"kev": c in kev}
            for c in art.get("cves", [])
        }
        art["relevance"] = compute_relevance(art, crit, cfg.settings["relevance"])
    counts = {lvl: sum(1 for a in articles if a["level"] == lvl) for lvl in LEVELS}
    log.info("Scoring : %s", ", ".join(f"{k}={v}" for k, v in counts.items()))
    return articles
