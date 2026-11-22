"""Feed collection and normalisation.

Each feed is fetched independently: a broken feed is logged and recorded in
data/feeds_status.json but never stops the others. Only the title, link,
a short excerpt (<= 300 chars) and metadata are stored — never the full text.
"""

from __future__ import annotations

import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from time import struct_time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import feedparser

from .common import (
    ROBOTS_CACHE_FILE,
    Config,
    feed_themes,
    fold,
    http_get,
    iso,
    parse_iso,
    read_json,
    strip_html,
    truncate,
    utcnow,
    write_json,
)

log = logging.getLogger("veille.collect")

TRACKING_PARAMS = re.compile(r"^(utm_[a-z_]+|fbclid|gclid|mc_cid|mc_eid|_hsenc|_hsmi|ref|cmpid|xtor)$", re.I)
CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.I)


# --------------------------------------------------------------------------- URL & ids


def canonical_url(url: str) -> str:
    """Normalise a URL: lowercase scheme/host, drop tracking params and fragment, trim trailing slash."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def article_id(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()[:16]


def normalise_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", fold(title)).strip()


def titles_similar(a: str, b: str, threshold: float) -> bool:
    na, nb = normalise_title(a), normalise_title(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    matcher = SequenceMatcher(None, na, nb)
    # quick_ratio is an upper bound: cheap rejection before the real ratio
    return matcher.quick_ratio() >= threshold and matcher.ratio() >= threshold


def extract_cves(text: str) -> list[str]:
    return sorted({m.upper() for m in CVE_RE.findall(text or "")})


# --------------------------------------------------------------------------- robots.txt


class RobotsChecker:
    """Caches robots.txt decisions per host (refreshed every 7 days)."""

    def __init__(self, cfg: Config, enabled: bool = True) -> None:
        self.cfg = cfg
        self.enabled = enabled
        self.ua = cfg.settings["collect"]["user_agent"]
        self.path = cfg.data_dir / ROBOTS_CACHE_FILE
        self.cache: dict[str, dict[str, Any]] = read_json(self.path, {})

    def allowed(self, url: str) -> bool:
        if not self.enabled:
            return True
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        entry = self.cache.get(host)
        fresh = entry and utcnow() - parse_iso(entry["fetched"]) < timedelta(days=7)
        if not fresh:
            body = ""
            try:
                resp = http_get(host + "/robots.txt", user_agent=self.ua, timeout=10, retries=0)
                if resp.status_code == 200:
                    body = resp.text[:200_000]
            except Exception as exc:  # unreachable robots.txt => allowed (standard behaviour)
                log.debug("robots.txt indisponible pour %s: %s", host, exc)
            entry = {"fetched": iso(utcnow()), "body": body}
            self.cache[host] = entry
        parser = RobotFileParser()
        parser.parse(entry["body"].splitlines())
        return parser.can_fetch(self.ua, url)

    def save(self) -> None:
        write_json(self.path, self.cache)


# --------------------------------------------------------------------------- feed parsing


def _entry_date(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value: struct_time | None = entry.get(key)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def normalise_entry(entry: Any, feed: dict[str, Any], excerpt_chars: int, now: datetime) -> dict[str, Any] | None:
    """Turn a feedparser entry into our article schema. Returns None if unusable."""
    link = (entry.get("link") or "").strip()
    title = strip_html(entry.get("title") or "")
    if not link.startswith(("http://", "https://")) or not title:
        return None
    raw_summary = entry.get("summary") or ""
    if not raw_summary and entry.get("content"):
        raw_summary = entry["content"][0].get("value", "")
    text = strip_html(raw_summary)
    published = _entry_date(entry) or now
    if published > now + timedelta(hours=1):  # clocks from the future
        published = now
    tags = [strip_html(t.get("term", "")) for t in entry.get("tags", []) if t.get("term")][:8]
    canon = canonical_url(link)
    return {
        "id": article_id(link),
        "title": truncate(title, 300),
        "url": canon,
        "source": feed["name"],
        "published": iso(published),
        "collected": iso(now),
        "excerpt": truncate(text, excerpt_chars),
        "language": feed.get("language", "en"),
        "feed_themes": feed_themes(feed),
        "feed_priority": int(feed.get("priority", 3)),
        "tags": tags,
        # CVEs detected in title + full summary (the full text itself is not stored)
        "cves": extract_cves(f"{title} {text}"),
    }


def fetch_feed(feed: dict[str, Any], cfg: Config, robots: RobotsChecker, now: datetime) -> tuple[list[dict], dict]:
    """Fetch and parse one feed. Never raises: errors are reported in the status dict."""
    c = cfg.settings["collect"]
    status: dict[str, Any] = {"name": feed["name"], "url": feed["url"], "checked": iso(now), "ok": False, "entries": 0}
    try:
        if not robots.allowed(feed["url"]):
            status["error"] = "interdit par robots.txt"
            log.warning("[%s] ignoré : robots.txt l'interdit", feed["name"])
            return [], status
        resp = http_get(
            feed["url"],
            user_agent=c["user_agent"],
            timeout=c["timeout_seconds"],
            retries=c["retries"],
            backoff=c["backoff_seconds"],
            headers={"Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.5"},
        )
        status["http_status"] = resp.status_code
        if resp.status_code != 200:
            status["error"] = f"HTTP {resp.status_code}"
            log.warning("[%s] HTTP %s", feed["name"], resp.status_code)
            return [], status
        parsed = feedparser.parse(resp.content)
        if parsed.bozo and not parsed.entries:
            status["error"] = f"flux mal formé : {type(parsed.bozo_exception).__name__}"
            log.warning("[%s] %s", feed["name"], status["error"])
            return [], status
        articles = []
        for entry in parsed.entries[: c["max_entries_per_feed"]]:
            art = normalise_entry(entry, feed, c["excerpt_max_chars"], now)
            if art:
                articles.append(art)
        status.update(ok=True, entries=len(articles))
        if articles:
            status["latest"] = max(a["published"] for a in articles)
        log.info("[%s] %d entrées", feed["name"], len(articles))
        return articles, status
    except Exception as exc:  # one broken feed must never stop the run
        status["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        log.warning("[%s] échec : %s", feed["name"], status["error"])
        return [], status


# --------------------------------------------------------------------------- merge & dedup


def deduplicate(existing: list[dict], incoming: list[dict], threshold: float, window_days: int) -> tuple[list[dict], int]:
    """Merge incoming into existing: same id => skip; similar title within window => skip.

    Existing articles keep their enrichment (summaries, scores). Returns (merged, added_count).
    """
    by_id = {a["id"]: a for a in existing}
    merged = list(existing)
    added = 0
    window = timedelta(days=window_days)
    for art in sorted(incoming, key=lambda a: (a["feed_priority"], a["published"])):
        if art["id"] in by_id:
            continue
        pub = parse_iso(art["published"])
        duplicate = next(
            (
                o
                for o in merged
                if abs(parse_iso(o["published"]) - pub) <= window and titles_similar(o["title"], art["title"], threshold)
            ),
            None,
        )
        if duplicate is not None:
            also = duplicate.setdefault("also_in", [])
            if art["source"] != duplicate["source"] and art["source"] not in also:
                also.append(art["source"])
            continue
        merged.append(art)
        by_id[art["id"]] = art
        added += 1
    return merged, added


def apply_retention(articles: list[dict], days: int, now: datetime) -> list[dict]:
    limit = now - timedelta(days=days)
    return [a for a in articles if parse_iso(a["published"]) >= limit]


def collect(cfg: Config, existing: list[dict], now: datetime | None = None) -> tuple[list[dict], list[dict], int]:
    """Fetch all enabled feeds in parallel and merge into the existing article list."""
    now = now or utcnow()
    c = cfg.settings["collect"]
    robots = RobotsChecker(cfg, enabled=c.get("respect_robots_txt", True))
    feeds = [f for f in cfg.feeds if f.get("enabled", True)]
    incoming: list[dict] = []
    statuses: list[dict] = []
    with ThreadPoolExecutor(max_workers=c["max_workers"]) as pool:
        futures = {pool.submit(fetch_feed, f, cfg, robots, now): f for f in feeds}
        for fut in as_completed(futures):
            arts, status = fut.result()
            incoming.extend(arts)
            statuses.append(status)
    robots.save()
    merged, added = deduplicate(existing, incoming, c["title_similarity_threshold"], c["dedup_window_days"])
    merged = apply_retention(merged, c["retention_days"], now)
    statuses.sort(key=lambda s: s["name"])
    ok = sum(1 for s in statuses if s["ok"])
    log.info("Collecte : %d/%d flux OK, %d nouveaux articles, %d au total", ok, len(statuses), added, len(merged))
    return merged, statuses, added
