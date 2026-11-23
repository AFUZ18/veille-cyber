"""Usage journal: data/usage.yaml (manual) + GitHub issues labelled `usage` / `signal-transforme`.

The site is static, so usage is declared either by editing data/usage.yaml or through
the GitHub issue forms opened by the « Signaler un usage » link on each card.

Issue content is UNTRUSTED: only validated, normalised fields are kept (article id,
usage type from an allow-list, date, short company name). Comments are never stored
or published. Without GITHUB_TOKEN (or on API error) the last cached issues are reused,
so the pipeline never fails because of this step.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from typing import Any

import requests

from .common import Config, iso, load_yaml, read_json, utcnow, write_json

log = logging.getLogger("veille.usage")

USAGE_FILE = "usage.yaml"
USAGE_CACHE_FILE = "cache/usage_issues.json"
LABEL_USAGE = "usage"
LABEL_SIGNAL = "signal-transforme"

USAGE_TYPES = (
    "alerte envoyée",
    "correctif appliqué",
    "note rédigée",
    "sensibilisation",
    "hypothèse de transformation",
    "article écarté (hors sujet)",
)
OFFTOPIC_TYPE = "article écarté (hors sujet)"
ARTICLE_ID_RE = re.compile(r"\b[0-9a-f]{16}\b")
HEADING_RE = re.compile(r"^###\s+(.+?)\s*$", re.M)


def normalise_type(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    for t in USAGE_TYPES:
        if text == t or text.startswith(t.split(" (")[0]):
            return t
    return None


def normalise_date(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    m = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(0)).isoformat()
    except ValueError:
        return None


def make_entry(raw: dict[str, Any], origin: str, kind: str, fallback_date: str | None = None) -> dict[str, Any] | None:
    """Validate one usage record. Returns None if it is unusable."""
    utype = normalise_type(raw.get("type"))
    if kind == "signal" and utype is None:
        utype = "hypothèse de transformation"
    if utype is None:
        return None
    ids = ARTICLE_ID_RE.findall(str(raw.get("article_id") or "").lower())
    signal = re.sub(r"[^\w .\-/àâçéèêëîïôûùüÿœ]", "", str(raw.get("signal") or ""), flags=re.I)[:60].strip()
    return {
        "origin": origin,
        "kind": kind,
        "type": utype,
        "article_id": ids[0] if ids else None,
        "signal": signal or None,
        "company": re.sub(r"[^\w .\-àâçéèêëîïôûùüÿœ]", "", str(raw.get("entreprise") or ""), flags=re.I)[:60].strip() or None,
        "date": normalise_date(raw.get("date")) or fallback_date,
    }


def read_yaml_usage(cfg: Config) -> list[dict[str, Any]]:
    path = cfg.data_dir / USAGE_FILE
    if not path.exists():
        return []
    try:
        data = load_yaml(path) or {}
    except Exception as exc:  # malformed manual file must not break the pipeline
        log.warning("data/usage.yaml illisible : %s", exc)
        return []
    out = []
    for i, raw in enumerate(data.get("entries", []) or []):
        if not isinstance(raw, dict):
            continue
        kind = "signal" if str(raw.get("kind", "usage")).lower().startswith("signal") else "usage"
        entry = make_entry(raw, f"usage.yaml#{i + 1}", kind)
        if entry:
            out.append(entry)
    return out


def parse_issue_form(body: str) -> dict[str, str]:
    """Parse the Markdown body GitHub generates from an issue form (### Label + value)."""
    fields: dict[str, str] = {}
    matches = list(HEADING_RE.finditer(body or ""))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        value = body[m.end() : end].strip()
        fields[m.group(1).strip().lower()] = "" if value == "_No response_" else value
    return fields


FORM_KEYS = {
    "identifiant de l'article": "article_id",
    "type d'usage": "type",
    "entreprise concernée": "entreprise",
    "date": "date",
    "signal faible": "signal",
}


def issue_to_entry(issue: dict[str, Any]) -> dict[str, Any] | None:
    labels = {lbl.get("name") for lbl in issue.get("labels", []) if isinstance(lbl, dict)}
    kind = "signal" if LABEL_SIGNAL in labels else "usage"
    fields = parse_issue_form(issue.get("body") or "")
    raw = {key: fields.get(label, "") for label, key in FORM_KEYS.items()}
    created = normalise_date((issue.get("created_at") or "")[:10])
    return make_entry(raw, f"issue#{issue.get('number')}", kind, fallback_date=created)


def fetch_issue_usage(repo: str, token: str, timeout: float = 20, max_pages: int = 5) -> list[dict[str, Any]]:
    """Read issues (open and closed) carrying the usage / signal labels via the GitHub REST API."""
    out: list[dict[str, Any]] = []
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    for label in (LABEL_USAGE, LABEL_SIGNAL):
        for page in range(1, max_pages + 1):
            resp = requests.get(
                f"https://api.github.com/repos/{repo}/issues",
                params={"labels": label, "state": "all", "per_page": 100, "page": page},
                headers=headers,
                timeout=timeout,
            )
            resp.raise_for_status()
            items = [i for i in resp.json() if "pull_request" not in i]
            out += [e for e in (issue_to_entry(i) for i in items) if e]
            if len(items) < 100:
                break
    # an issue carrying both labels is counted once
    seen: set[str] = set()
    return [e for e in out if not (e["origin"] in seen or seen.add(e["origin"]))]


def load_usage(cfg: Config) -> list[dict[str, Any]]:
    """All usage records (manual file + GitHub issues, cached)."""
    cache_path = cfg.data_dir / USAGE_CACHE_FILE
    cached = read_json(cache_path, {"entries": []})
    issues = cached.get("entries", [])
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if token and repo and os.environ.get("VEILLE_OFFLINE") != "1":
        try:
            issues = fetch_issue_usage(repo, token)
            write_json(cache_path, {"fetched": iso(utcnow()), "entries": issues})
            log.info("Journal d'usage : %d issue(s) lue(s)", len(issues))
        except Exception as exc:
            log.warning("Issues d'usage illisibles (%s) : utilisation du cache", exc)
    entries = read_yaml_usage(cfg) + issues
    log.info("Journal d'usage : %d entrée(s) au total", len(entries))
    return entries
