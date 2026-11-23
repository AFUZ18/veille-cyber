"""One GitHub issue « Action d'amélioration » per open SLA action, without duplicates.

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


def maybe_sync(actions: dict[str, dict[str, Any]], site_url: str) -> None:
    """Called by the pipeline: only in GitHub Actions with ISSUES_SYNC=1 and a token."""
    token, repo = os.environ.get("GITHUB_TOKEN", ""), os.environ.get("GITHUB_REPOSITORY", "")
    if os.environ.get("ISSUES_SYNC") != "1" or not token or not repo:
        return
    try:
        gh = GitHub(repo, token)
        gh.ensure_usage_labels()
        stats = sync_actions(actions, gh, site_url)
        log.info("Issues d'amélioration : %s", stats)
    except Exception as exc:  # never break the pipeline for this
        log.warning("Synchronisation des issues impossible : %s", exc)
