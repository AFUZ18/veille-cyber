"""Weak signal detection.

A weak signal is a term whose frequency rises sharply over the last 7 days compared
with the previous N weeks, while staying rare (few articles, few sources).

Terms are:
- glossary concepts (config/glossary.yaml), matched in French AND English, so that
  « rançongiciel » and « ransomware » count as the same term;
- proper-noun-like tokens from titles (product names, malware families, threat actors).
All thresholds live in config/kpi.yaml > signaux_faibles.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from .common import THEME_IDS, Config, fold, parse_iso

log = logging.getLogger("veille.signals")

# Capitalised or mixed tokens: "Akira", "GhostRAT", "PAN-OS", "Citrix", "XWorm", "LLMjacking"
ENTITY_RE = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:[-.][A-Za-z0-9]+)*\b")
CVE_RE = re.compile(r"^CVE-", re.I)


def article_terms(article: dict[str, Any], cfg: Config, stop: set[str]) -> dict[str, tuple[str, str]]:
    """Return {term_key: (label, kind)} for one article."""
    terms: dict[str, tuple[str, str]] = {}
    labels = {c["id"]: c.get("label", c["id"]) for c in (cfg.glossary or {}).get("concepts", []) or []}
    for cid in article.get("glossary_concepts", []) or []:
        terms[f"concept:{cid}"] = (labels.get(cid, cid), "concept")
    title = article.get("title", "")
    words = [w for w in re.findall(r"[A-Za-zÀ-ÿ][\w'-]*", title) if len(w) > 3]
    # "Title Case Headlines" capitalise every word: only distinctive tokens are kept then
    rest = words[1:]  # the first word is always capitalised
    title_case = len(rest) >= 2 and sum(w[0].isupper() for w in rest) / len(rest) >= 0.6
    for match in ENTITY_RE.finditer(title):
        tok = match.group(0)
        if len(tok) < 4 or fold(tok) in stop or CVE_RE.match(tok):
            continue
        distinctive = any(c.isdigit() for c in tok) or sum(c.isupper() for c in tok) > 1
        # the first word of a title is capitalised anyway: keep it only if it looks like a name
        if (title_case or match.start() == 0) and not distinctive:
            continue
        terms[f"entity:{fold(tok)}"] = (tok, "entité")
    return terms


def reference_weeks(articles: list[dict[str, Any]], now: datetime, weeks: int) -> float:
    """Weeks of reference history actually covered by the collection (0 while warming up).

    The reference period cannot start before the first collection: entries fetched on
    day one only cover each feed's last items, not a complete history.
    """
    collected = [parse_iso(a["collected"]) for a in articles if a.get("collected")]
    if not collected:
        return 0.0
    cur_start = now - timedelta(days=7)
    ref_start = max(cur_start - timedelta(weeks=weeks), min(collected))
    return max(0.0, (cur_start - ref_start).total_seconds() / (7 * 86400))


def detect_weak_signals(articles: list[dict[str, Any]], cfg: Config, now: datetime) -> list[dict[str, Any]]:
    """Return weak signals; an empty list while the reference history is shorter than one week."""
    params = (cfg.kpi or {}).get("signaux_faibles", {}) or {}
    weeks = int(params.get("semaines_reference", 4))
    stop = {fold(w) for w in params.get("mots_ignores", []) or []}
    stop |= {fold(f["name"].split()[0]) for f in cfg.feeds}  # source names are not signals

    covered = reference_weeks(articles, now, weeks)
    if covered < 1:
        log.info("Signaux faibles : période d'apprentissage (%.1f semaine(s) d'historique sur 1 requise)", covered)
        return []
    weeks_used = min(float(weeks), covered)
    cur_start = now - timedelta(days=7)
    ref_start = cur_start - timedelta(weeks=weeks_used)
    current: dict[str, list[dict[str, Any]]] = defaultdict(list)
    reference: Counter[str] = Counter()
    labels: dict[str, tuple[str, str]] = {}
    for a in articles:
        pub = parse_iso(a["published"])
        if pub < ref_start:
            continue
        for key, lab in article_terms(a, cfg, stop).items():
            labels.setdefault(key, lab)
            if pub >= cur_start:
                current[key].append(a)
            else:
                reference[key] += 1

    out = []
    for key, arts in current.items():
        n = len(arts)
        sources = {a["source"] for a in arts} | {s for a in arts for s in a.get("also_in", []) or []}
        baseline = reference[key] / weeks_used
        if not (params.get("min_articles_semaine", 2) <= n <= params.get("max_articles_semaine", 8)):
            continue
        if len(sources) > params.get("max_sources", 3):
            continue
        if baseline > params.get("max_moyenne_reference", 1.0):
            continue
        if n < params.get("croissance_min", 3.0) * max(baseline, 0.25) and baseline > 0:
            continue
        axes = Counter(t for a in arts for t in a.get("themes", []) if t in THEME_IDS)
        label, kind = labels[key]
        out.append(
            {
                "key": key,
                "term": label,
                "kind": kind,
                "axis": axes.most_common(1)[0][0] if axes else None,
                "count_week": n,
                "baseline_weekly": round(baseline, 2),
                "sources": sorted(sources),
                "languages": sorted({a.get("source_language") or a.get("language", "en") for a in arts}),
                "articles": [
                    {"id": a["id"], "title": a["title"], "url": a["url"], "source": a["source"]}
                    for a in sorted(arts, key=lambda x: x["published"], reverse=True)[:6]
                ],
            }
        )
    out.sort(key=lambda s: (-s["count_week"], s["term"].lower()))
    log.info("Signaux faibles : %d détecté(s)", len(out))
    return out


def render_weak_signals_md(existing: str, signals: list[dict[str, Any]], week_label: str) -> str:
    """Append a hypothesis template for each NEW signal; keep what the user already wrote."""
    header = (
        "# Signaux faibles et hypothèses de transformation\n\n"
        "Ce fichier est complété automatiquement à chaque nouveau signal faible détecté.\n"
        "Remplissez les champs de chaque fiche, puis déclarez la transformation avec le formulaire\n"
        "GitHub « Signal faible transformé » (ou dans data/usage.yaml, `kind: signal`).\n"
    )
    text = existing if existing.strip() else header
    for s in signals:
        marker = f"<!-- signal:{week_label}:{s['key']} -->"
        if marker in text:
            continue
        lines = [
            "",
            marker,
            f"## {week_label} · {s['term']} ({s['axis'] or 'sans axe'})",
            "",
            f"- **Signal** : « {s['term']} » cité {s['count_week']} fois cette semaine "
            f"(moyenne précédente : {s['baseline_weekly']}/semaine) par {', '.join(s['sources'])}.",
            "- **Articles** : " + " ; ".join(f"[{a['title'][:80]}]({a['url']})" for a in s["articles"][:3]),
            "- **Hypothèse** : _(ex. « ce produit va être massivement ciblé en France d'ici 3 mois »)_",
            "- **Indicateurs à surveiller** : _(nombre d'articles, CVE associées, avis CERT-FR…)_",
            "- **Échéance** : _(date de réévaluation)_",
            "- **Décision** : _(surveiller / alerter les clients / créer une offre / abandonner)_",
        ]
        text = text.rstrip("\n") + "\n" + "\n".join(lines) + "\n"
    return text
