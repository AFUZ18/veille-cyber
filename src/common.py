"""Shared helpers: configuration, logging, JSON storage, HTTP with retries, text utils."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("VEILLE_CONFIG_DIR", ROOT / "config"))
DATA_DIR = Path(os.environ.get("VEILLE_DATA_DIR", ROOT / "data"))

ARTICLES_FILE = "articles.json"
SUMMARIES_FILE = "summaries_cache.json"
CVE_CACHE_FILE = "cache/cve_cache.json"
KEV_CACHE_FILE = "cache/kev.json"
FEEDS_STATUS_FILE = "feeds_status.json"
ROBOTS_CACHE_FILE = "cache/robots.json"

THEME_IDS = ("H1", "H2", "H3", "H4")
EVENTS_THEME = "EVENTS"


def setup_logging(level: str | None = None) -> logging.Logger:
    """Configure a clear, timestamped log format for CI logs."""
    logging.basicConfig(
        level=getattr(logging, (level or os.environ.get("LOG_LEVEL", "INFO")).upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("veille")


log = logging.getLogger("veille")


# --------------------------------------------------------------------------- config


@dataclass
class Config:
    """All YAML configuration loaded once."""

    settings: dict[str, Any]
    feeds: list[dict[str, Any]]
    themes: dict[str, Any]
    events: list[dict[str, Any]]
    data_dir: Path = field(default_factory=lambda: DATA_DIR)
    # Quality / KPI layer (optional files: an absent file yields an empty dict)
    kpi: dict[str, Any] = field(default_factory=dict)
    glossary: dict[str, Any] = field(default_factory=dict)
    sources_quality: dict[str, Any] = field(default_factory=dict)
    checklist: dict[str, Any] = field(default_factory=dict)
    bias: dict[str, Any] = field(default_factory=dict)

    @property
    def site_url(self) -> str:
        url = os.environ.get("SITE_URL") or self.settings["site"]["url"]
        return url if url.endswith("/") else url + "/"


def load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_optional_yaml(path: Path) -> dict[str, Any]:
    return load_yaml(path) if path.exists() else {}


def load_config(config_dir: Path | None = None, data_dir: Path | None = None) -> Config:
    cdir = Path(config_dir or CONFIG_DIR)
    feeds = load_yaml(cdir / "feeds.yaml").get("feeds", [])
    validate_feeds(feeds)
    return Config(
        settings=load_yaml(cdir / "settings.yaml"),
        feeds=feeds,
        themes=load_yaml(cdir / "themes.yaml"),
        events=load_yaml(cdir / "events.yaml").get("events", []),
        data_dir=Path(data_dir or DATA_DIR),
        kpi=load_optional_yaml(cdir / "kpi.yaml"),
        glossary=load_optional_yaml(cdir / "glossary.yaml"),
        sources_quality=load_optional_yaml(cdir / "sources_quality.yaml"),
        checklist=load_optional_yaml(cdir / "verification_checklist.yaml"),
        bias=load_optional_yaml(cdir / "bias.yaml"),
    )


def feed_themes(feed: dict[str, Any]) -> list[str]:
    raw = feed.get("theme", [])
    return [raw] if isinstance(raw, str) else list(raw)


def validate_feeds(feeds: list[dict[str, Any]]) -> None:
    """Fail fast with a readable message if feeds.yaml is malformed."""
    allowed = set(THEME_IDS) | {EVENTS_THEME}
    names: set[str] = set()
    for i, feed in enumerate(feeds):
        for key in ("name", "url", "theme", "language", "priority", "enabled"):
            if key not in feed:
                raise ValueError(f"feeds.yaml entrée #{i + 1}: champ obligatoire manquant « {key} »")
        if not str(feed["url"]).startswith(("http://", "https://")):
            raise ValueError(f"feeds.yaml « {feed['name']} »: URL invalide")
        bad = [t for t in feed_themes(feed) if t not in allowed]
        if bad:
            raise ValueError(f"feeds.yaml « {feed['name']} »: thème inconnu {bad}")
        if feed["priority"] not in (1, 2, 3):
            raise ValueError(f"feeds.yaml « {feed['name']} »: priority doit valoir 1, 2 ou 3")
        if feed["name"] in names:
            raise ValueError(f"feeds.yaml: nom en double « {feed['name']} »")
        names.add(feed["name"])


# --------------------------------------------------------------------------- JSON store


def read_json(path: Path, default: Any) -> Any:
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        log.warning("JSON illisible %s (%s) : valeur par défaut utilisée", path, exc)
        return default


def write_json(path: Path, data: Any) -> None:
    """Atomic write with stable formatting (small, readable git diffs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    tmp.replace(path)


# --------------------------------------------------------------------------- HTTP


def http_get(
    url: str,
    *,
    user_agent: str,
    timeout: float = 20,
    retries: int = 2,
    backoff: float = 2.0,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    session: requests.Session | None = None,
) -> requests.Response:
    """GET with timeout and exponential backoff on network errors, 429 and 5xx."""
    hdrs = {"User-Agent": user_agent}
    hdrs.update(headers or {})
    getter = session.get if session else requests.get
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = getter(url, params=params, headers=hdrs, timeout=timeout)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < retries:
                wait = backoff * (2**attempt)
                retry_after = getattr(getattr(exc, "response", None), "headers", {}) or {}
                if "Retry-After" in retry_after:
                    try:
                        wait = max(wait, float(retry_after["Retry-After"]))
                    except ValueError:
                        pass
                time.sleep(min(wait, 60))
    assert last_exc is not None
    raise last_exc


# --------------------------------------------------------------------------- text utils

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    """Remove markup and collapse whitespace. Output is still untrusted text."""
    import html

    text = _TAG_RE.sub(" ", text or "")
    return _WS_RE.sub(" ", html.unescape(text)).strip()


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:.") + "…"


def fold(text: str) -> str:
    """Lowercase and strip accents, for accent-insensitive keyword matching."""
    norm = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in norm if not unicodedata.combining(c)).lower()


@lru_cache(maxsize=4096)
def keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Regex for a keyword anchored on word boundaries; tolerates a plural suffix (s, es, x)."""
    k = re.escape(fold(keyword))
    return re.compile(rf"(?<![a-z0-9]){k}(?:s|es|x)?(?![a-z0-9])")


def find_keywords(text: str, keywords: list[str]) -> list[str]:
    """Return the keywords (original spelling) found in text, accent/case-insensitive."""
    folded = fold(text)
    return [kw for kw in keywords if keyword_pattern(kw).search(folded)]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
