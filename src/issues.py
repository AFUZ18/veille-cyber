"""GitHub issues of the quality layer.

Chantier 3: a SINGLE weekly issue « Revue de la veille » (created or updated, never
duplicated) lists the health cards in « Problème », with one action per line and the
failing sources grouped in one list. Nothing is opened during the learning period, and
cards without data never produce an action. The per-action issues of chantier 2
(label `amelioration`) are closed automatically, as they are replaced by the review.

Legacy (chantier 2) — one GitHub issue « Action d'amélioration » per open SLA action:

Same mechanism as the existing failure alert (one issue per problem, updated rather
than duplicated), but in Python so it is testable. Each issue carries a hidden marker
`<!-- action-key: … -->`; open actions create or update their issue, resolved actions
close it with a comment. Requires GITHUB_TOKEN with `issues: write` (workflow) and is
skipped silently otherwise.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import requests

log = logging.getLogger("veille.issues")

LABEL = "amelioration"
REVIEW_LABEL = "revue-veille"
REVIEW_TITLE = "Revue de la veille"
REVIEW_MARKER = "<!-- revue-veille -->"
MARKER_RE = re.compile(r"<!-- action-key: (.+?) -->")
API = "https://api.github.com"


class GitHub:
    def __init__(self, repo: str, token: str, session: requests.Session | None = None) -> None:
        self.repo = repo
        self.s = session or requests.Session()
        self.s.headers.update(
            {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        )

    def _url(self, path: str) -> str:
        return f"{API}/repos/{self.repo}{path}"

    def ensure_label(self) -> None:
        r = self.s.post(
            self._url("/labels"),
            json={"name": LABEL, "color": "1b4fd6", "description": "Action d'amélioration de la veille (SLA)"},
            timeout=20,
        )
        if r.status_code not in (201, 422):  # 422 = already exists
            r.raise_for_status()

    def list_issues(self, label: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for page in range(1, 6):
            r = self.s.get(
                self._url("/issues"), params={"labels": label, "state": "all", "per_page": 100, "page": page}, timeout=20
            )
            r.raise_for_status()
            items = [i for i in r.json() if "pull_request" not in i]
            out += items
            if len(items) < 100:
                break
        return out

    def create_labeled(self, title: str, body: str, label: str) -> None:
        self.s.post(self._url("/issues"), json={"title": title, "body": body, "labels": [label]}, timeout=20).raise_for_status()

    def list_action_issues(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for page in range(1, 6):
            r = self.s.get(
                self._url("/issues"), params={"labels": LABEL, "state": "all", "per_page": 100, "page": page}, timeout=20
            )
            r.raise_for_status()
            items = r.json()
            for it in items:
                m = MARKER_RE.search(it.get("body") or "")
                # keep the most recent issue per key (open first)
                if m and (m.group(1) not in out or it.get("state") == "open"):
                    out[m.group(1)] = it
            if len(items) < 100:
                break
        return out

    def create(self, title: str, body: str) -> None:
        self.s.post(self._url("/issues"), json={"title": title, "body": body, "labels": [LABEL]}, timeout=20).raise_for_status()

    def update(self, number: int, **fields: Any) -> None:
        self.s.patch(self._url(f"/issues/{number}"), json=fields, timeout=20).raise_for_status()

    def comment(self, number: int, body: str) -> None:
        self.s.post(self._url(f"/issues/{number}/comments"), json={"body": body}, timeout=20).raise_for_status()


def issue_title(action: dict[str, Any]) -> str:
    sujet = f" ({action['sujet']})" if action.get("sujet") else ""
    return f"Action d'amélioration : {action['kpi_nom']}{sujet}"[:250]


def issue_body(action: dict[str, Any], site_url: str) -> str:
    return (
        f"**Action proposée :** {action['action']}\n\n"
        f"- KPI : {action['kpi_nom']} (`{action['kpi']}`)\n"
        f"- Concerne : {action.get('sujet') or '—'}\n"
        f"- Hors cible depuis : {action['first_seen'][:10]} ({action.get('periods', '?')} période(s) consécutive(s))\n"
        f"- Dernière vérification : {action['last_seen'][:16].replace('T', ' ')} UTC\n\n"
        f"Page KPI : {site_url}#KPI — Plan complet : `data/improvement_actions.md`.\n\n"
        "Cette issue est mise à jour automatiquement et sera fermée quand le KPI reviendra dans sa cible.\n\n"
        f"<!-- action-key: {action['key']} -->"
    )


def sync_actions(actions: dict[str, dict[str, Any]], gh: GitHub, site_url: str) -> dict[str, int]:
    """Create/update/close issues so that each open action has exactly one open issue."""
    stats = {"created": 0, "updated": 0, "closed": 0}
    gh.ensure_label()
    existing = gh.list_action_issues()
    for key, action in actions.items():
        issue = existing.get(key)
        if action["status"] == "ouverte":
            body = issue_body(action, site_url)
            if issue is None:
                gh.create(issue_title(action), body)
                stats["created"] += 1
            elif issue.get("state") == "closed":
                gh.update(issue["number"], state="open", body=body)
                gh.comment(issue["number"], "Le KPI est de nouveau hors cible : issue rouverte.")
                stats["updated"] += 1
            elif (issue.get("body") or "") != body:
                gh.update(issue["number"], body=body)
                stats["updated"] += 1
        elif issue is not None and issue.get("state") == "open":
            gh.comment(issue["number"], f"KPI revenu dans la cible le {action.get('resolved', '')[:10]} : action résolue.")
            gh.update(issue["number"], state="closed")
            stats["closed"] += 1
    return stats


# --------------------------------------------------------------------------- chantier 3: weekly review


def review_body(health: dict[str, Any], week_label: str, site_url: str) -> str | None:
    """Markdown body of the review, or None when no card is in « Problème »."""
    problems = [c for c in health.get("cards", []) if c.get("answer") == "probleme"]
    if not problems:
        return None
    lines = [
        f"## Revue de la veille · semaine {week_label}",
        "",
        f"**Bilan :** {health.get('verdict', {}).get('sentence', '')}",
        "",
        "### Points en « Problème » (une action par ligne)",
        "",
    ]
    for c in sorted(problems, key=lambda c: c.get("importance", 9)):
        lines.append(f"- [ ] **{c['question']}** {c.get('chiffre') or ''} → {c.get('action') or c.get('que_faire', '')}")
    failing = sorted({s for c in problems for s in c.get("failing_sources", [])})
    if failing:
        lines += ["", "### Sources en panne", "", *[f"- {name}" for name in failing]]
    lines += [
        "",
        f"Vue complète : {site_url}#sante",
        "",
        "Cette issue est unique : elle est mise à jour automatiquement et fermée quand plus aucun point n'est en « Problème ».",
        "",
        REVIEW_MARKER,
    ]
    return "\n".join(lines)


def sync_review(health: dict[str, Any], gh: Any, site_url: str, week_label: str) -> str:
    """Create, update, reopen or close THE review issue. Returns what was done."""
    learning = (health.get("learning") or {}).get("active", False)
    existing = [i for i in gh.list_issues(REVIEW_LABEL) if REVIEW_MARKER in (i.get("body") or "")]
    issue = next((i for i in existing if i.get("state") == "open"), None) or (existing[0] if existing else None)
    body = None if learning else review_body(health, week_label, site_url)
    if body is None:
        if issue is not None and issue.get("state") == "open":
            gh.comment(issue["number"], "Plus aucun point en « Problème » (ou période d'observation) : revue close.")
            gh.update(issue["number"], state="closed")
            return "closed"
        return "none"
    if issue is None:
        gh.create_labeled(REVIEW_TITLE, body, REVIEW_LABEL)
        return "created"
    if issue.get("state") == "closed":
        gh.update(issue["number"], state="open", body=body)
        return "reopened"
    if (issue.get("body") or "") != body:
        gh.update(issue["number"], body=body)
        return "updated"
    return "unchanged"


def close_legacy_action_issues(gh: Any) -> int:
    """Close the per-action issues of chantier 2: they are replaced by the weekly review."""
    closed = 0
    for issue in gh.list_issues(LABEL):
        if issue.get("state") == "open" and MARKER_RE.search(issue.get("body") or ""):
            gh.comment(issue["number"], "Remplacée par l'issue unique « Revue de la veille » (une seule alerte hebdomadaire).")
            gh.update(issue["number"], state="closed")
            closed += 1
    return closed


def maybe_sync(health: dict[str, Any], site_url: str, week_label: str) -> None:
    """Called by the pipeline: only in GitHub Actions with ISSUES_SYNC=1 and a token."""
    token, repo = os.environ.get("GITHUB_TOKEN", ""), os.environ.get("GITHUB_REPOSITORY", "")
    if os.environ.get("ISSUES_SYNC") != "1" or not token or not repo:
        return
    try:
        gh = GitHub(repo, token)
        gh.ensure_usage_labels()
        gh.ensure_label(REVIEW_LABEL, "b3261e", "Revue hebdomadaire de la veille (issue unique)")
        legacy = close_legacy_action_issues(gh)
        result = sync_review(health, gh, site_url, week_label)
        log.info("Revue de la veille : %s ; anciennes issues fermées : %d", result, legacy)
    except Exception as exc:  # never break the pipeline for this
        log.warning("Synchronisation des issues impossible : %s", exc)
