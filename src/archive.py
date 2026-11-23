"""Light long-term article archive: data/archive/AAAA-MM.jsonl (no full text).

The site keeps 90 days; the archive keeps a light record of every article forever,
for multi-month trends. Files older than N months are gzip-compressed to keep the
repository small.
"""

from __future__ import annotations

import gzip
import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .common import Config

log = logging.getLogger("veille.archive")

ARCHIVE_DIR = "archive"
ARCHIVE_FIELDS = (
    "id", "title", "url", "source", "published", "themes", "level", "criticality", "relevance",
    "language", "source_language", "reliability", "cves", "kev",
)  # fmt: skip


def light(article: dict[str, Any]) -> dict[str, Any]:
    return {k: article.get(k) for k in ARCHIVE_FIELDS}


def _read_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    for line in path.read_text("utf-8").splitlines():
        try:
            rec = json.loads(line)
            out[rec["id"]] = rec
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return out


def months_between(a: str, b: str) -> int:
    """Number of months from month a (AAAA-MM) to month b."""
    ya, ma = map(int, a.split("-"))
    yb, mb = map(int, b.split("-"))
    return (yb - ya) * 12 + (mb - ma)


def update_archive(articles: list[dict[str, Any]], cfg: Config, now: datetime) -> int:
    """Upsert articles into their month file; compress old months. Returns records written."""
    folder = cfg.data_dir / ARCHIVE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in articles:
        by_month[a["published"][:7]].append(a)
    compress_after = int(cfg.settings.get("quality", {}).get("archive_compress_after_months", 12))
    current = now.strftime("%Y-%m")
    written = 0
    for month, arts in by_month.items():
        if months_between(month, current) > compress_after:
            continue  # never reopen a compressed month
        path = folder / f"{month}.jsonl"
        records = _read_jsonl(path)
        for a in arts:
            records[a["id"]] = light(a)
        lines = [
            json.dumps(r, ensure_ascii=False, sort_keys=True)
            for r in sorted(records.values(), key=lambda r: (r["published"], r["id"]))
        ]
        path.write_text("\n".join(lines) + "\n", "utf-8")
        written += len(records)
    for path in folder.glob("*.jsonl"):
        if months_between(path.stem, current) > compress_after:
            with path.open("rb") as src, gzip.open(path.with_suffix(".jsonl.gz"), "wb") as dst:
                dst.write(src.read())
            path.unlink()
            log.info("Archive compressée : %s.gz", path.name)
    return written
