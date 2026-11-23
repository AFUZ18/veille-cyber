"""Theme classification (H1-H4), sector/technology tagging and noise exclusion."""

from __future__ import annotations

import logging
from typing import Any

from .common import EVENTS_THEME, THEME_IDS, Config, find_keywords

log = logging.getLogger("veille.classify")


def article_text(article: dict[str, Any]) -> str:
    return " ".join([article.get("title", ""), article.get("excerpt", ""), " ".join(article.get("tags", []))])


def detect_themes(article: dict[str, Any], themes_cfg: dict[str, Any]) -> tuple[list[str], dict[str, list[str]]]:
    """Feed themes + any theme with at least `min_hits` keyword matches."""
    text = article_text(article)
    themes = [t for t in article.get("feed_themes", []) if t in THEME_IDS]
    hits: dict[str, list[str]] = {}
    for theme_id in THEME_IDS:
        spec = themes_cfg["themes"].get(theme_id, {})
        found = find_keywords(text, spec.get("keywords", []))
        if found:
            hits[theme_id] = found
        if len(found) >= spec.get("min_hits", 1) and theme_id not in themes:
            themes.append(theme_id)
    return sorted(themes), hits


def glossary_terms(concept: dict[str, Any]) -> list[str]:
    """All French and English terms of a glossary concept."""
    return list(concept.get("fr") or []) + list(concept.get("en") or [])


def detect_glossary(article: dict[str, Any], glossary: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (matched concept ids, axes implied by those concepts).

    Terms are searched in BOTH languages whatever the article language, so a French
    and an English article on the same subject map to the same concept and axes.
    """
    text = article_text(article)
    concepts: list[str] = []
    axes: set[str] = set()
    for concept in glossary.get("concepts", []) or []:
        if find_keywords(text, glossary_terms(concept)):
            concepts.append(concept["id"])
            axes.update(a for a in concept.get("axes", []) if a in THEME_IDS)
    return concepts, sorted(axes)


def detect_sectors(article: dict[str, Any], themes_cfg: dict[str, Any]) -> list[str]:
    """Names of sectors / technologies / cloud providers / priority topics mentioned."""
    text = article_text(article)
    found: list[str] = []
    for group in themes_cfg.get("sectoral", {}).values():
        for name, keywords in (group or {}).items():
            if find_keywords(text, keywords or []):
                found.append(name)
    return found


def is_event(article: dict[str, Any], themes_cfg: dict[str, Any]) -> bool:
    if EVENTS_THEME in article.get("feed_themes", []):
        return True
    return bool(find_keywords(article_text(article), themes_cfg.get("events_keywords", [])))


def is_excluded(article: dict[str, Any], themes_cfg: dict[str, Any], official_sources: list[str]) -> str | None:
    """Return the exclusion reason, or None if the article is kept."""
    excl = themes_cfg.get("exclusions", {})
    official = any(src.lower() in article["source"].lower() for src in official_sources)
    if article.get("cves") or official:
        return None
    noise = find_keywords(article["title"], excl.get("title_patterns", []))
    if noise:
        return f"bruit: {noise[0]}"
    if article["source"] in excl.get("generic_feeds", []):
        if not find_keywords(article_text(article), excl.get("cyber_keywords", [])):
            return "hors sujet (flux généraliste)"
    return None


def classify(articles: list[dict[str, Any]], cfg: Config) -> list[dict[str, Any]]:
    """Annotate each article in place and drop excluded ones."""
    official_sources = cfg.settings["criticality"].get("official_sources", [])
    kept: list[dict[str, Any]] = []
    excluded = 0
    for art in articles:
        reason = is_excluded(art, cfg.themes, official_sources)
        if reason:
            excluded += 1
            log.debug("Exclu (%s) : %s", reason, art["title"])
            continue
        themes, hits = detect_themes(art, cfg.themes)
        concepts, glossary_axes = detect_glossary(art, cfg.glossary)
        added = sorted(set(glossary_axes) - set(themes))
        art["themes"] = sorted(set(themes) | set(glossary_axes))
        art["glossary_concepts"] = concepts
        art["glossary_axes_added"] = added  # axes reached only thanks to the bilingual glossary
        art["keyword_hits"] = hits
        art["sectors"] = detect_sectors(art, cfg.themes)
        art["is_event"] = is_event(art, cfg.themes)
        art["official"] = any(src.lower() in art["source"].lower() for src in official_sources)
        kept.append(art)
    log.info("Classement : %d articles conservés, %d exclus", len(kept), excluded)
    return kept
