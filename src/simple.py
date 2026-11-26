"""Plain-language layer of the site (chantier 3).

- render_template: fills {{ui.path}} (HTML-escaped) and {{json:ui.path}} (JS-safe) placeholders
  of site/index.html from config/ui_texts.yaml, so that no displayed text lives in the code;
- simple_reasons: « Pourquoi c'est important » / « Que faire » sentences, from the AI summary
  when available, otherwise from the plain rules of ui_texts.yaml > raisons_auto;
- home_payload: one-sentence summary of the week and the « À lire en priorité » list.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta
from typing import Any

from .common import Config, parse_iso

PLACEHOLDER_RE = re.compile(r"\{\{(json:)?ui\.([\w.]+)\}\}")
LEVEL_RANK = {"Critique": 3, "Élevé": 2, "Moyen": 1, "Info": 0}


def lookup(ui: dict[str, Any], path: str) -> Any:
    node: Any = ui
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"Texte introuvable dans config/ui_texts.yaml : {path}")
        node = node[part]
    return node


def render_template(template: str, cfg: Config) -> str:
    def repl(m: re.Match[str]) -> str:
        value = lookup(cfg.ui, m.group(2))
        if m.group(1):  # inside a <script>: JSON string, with "</" neutralised
            return json.dumps(str(value), ensure_ascii=False).replace("</", "<\\/")
        return html.escape(str(value), quote=True)

    page = PLACEHOLDER_RE.sub(repl, template)
    return page.replace("{{SITE_TITLE}}", html.escape(cfg.settings["site"]["title"]))


def fill(template: str, **values: Any) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), template or "")


# --------------------------------------------------------------------------- why / what to do


def _condition(article: dict[str, Any], name: str) -> bool:
    level = article.get("level")
    if name == "pirates":
        return bool(article.get("kev"))
    if name == "rancongiciel":
        return "rancongiciel" in (article.get("glossary_concepts") or []) or "ransomware" in article.get("title", "").lower()
    if name == "faille_grave":
        return level in ("Critique", "Élevé") and bool(article.get("cves"))
    if name == "source_officielle":
        return bool(article.get("official")) and level != "Info"
    if name == "urgent":
        return level == "Critique"
    if name == "important":
        return level == "Élevé"
    return False


def simple_reasons(article: dict[str, Any], ui: dict[str, Any]) -> tuple[str | None, str | None]:
    """(why, what to do). The AI text wins; otherwise the first matching plain rule; Info articles get nothing."""
    why, todo = article.get("why"), article.get("action")
    if why and todo:
        return why, todo
    if article.get("level") == "Info" and not article.get("kev"):
        return why, todo
    for rule in ui.get("raisons_auto", []) or []:
        if _condition(article, rule.get("condition", "")):
            return why or rule.get("pourquoi"), todo or rule.get("que_faire")
    return why, todo


# --------------------------------------------------------------------------- home


def plural(texts: dict[str, Any], key: str, n: int) -> str:
    template = texts.get(f"{key}_0") if n == 0 and f"{key}_0" in texts else texts.get(f"{key}_1" if n == 1 else f"{key}_n", "")
    return fill(template, n=n)


def home_payload(articles: list[dict[str, Any]], cfg: Config, now: datetime) -> dict[str, Any]:
    texts = (cfg.ui or {}).get("accueil", {})
    week = [a for a in articles if parse_iso(a["published"]) >= now - timedelta(days=7)]
    urgent = sum(a.get("level") == "Critique" for a in week)
    important = sum(a.get("level") == "Élevé" for a in week)
    if urgent == 0 and important == 0:
        summary = fill(texts.get("resume_rien", ""), total=len(week))
    else:
        summary = fill(
            texts.get("resume", ""),
            urgent_txt=plural(texts, "urgent", urgent),
            important_txt=plural(texts, "important", important),
        )
        summary = summary[:1].upper() + summary[1:]

    def rank(a: dict[str, Any]) -> tuple:
        return (
            LEVEL_RANK.get(a.get("level"), 0),
            bool(a.get("kev")),
            a.get("criticality", 0) + a.get("relevance", 0),
            a["published"],
        )

    top = sorted((a for a in week if a.get("level") in ("Critique", "Élevé")), key=rank, reverse=True)[:5]
    if len(top) < 3:  # complete with the most relevant « À suivre » items, never more than 3 in total then
        extra = sorted((a for a in week if a.get("level") == "Moyen"), key=rank, reverse=True)
        top += extra[: 3 - len(top)]
    return {"summary": summary, "urgent": urgent, "important": important, "priority": [a["id"] for a in top]}
