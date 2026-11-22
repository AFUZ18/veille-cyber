"""Check that every feed in config/feeds.yaml answers and contains valid entries.

python scripts/check_feeds.py                     # table in the terminal
python scripts/check_feeds.py --summary FILE      # also writes a Markdown report (GitHub step summary)
python scripts/check_feeds.py --strict            # exit code 1 if a feed is broken
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.collect import RobotsChecker, fetch_feed  # noqa: E402
from src.common import load_config, setup_logging, utcnow  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--all", action="store_true", help="inclure les flux désactivés")
    args = parser.parse_args()
    setup_logging("WARNING")
    cfg = load_config()
    robots = RobotsChecker(cfg)
    now = utcnow()
    feeds = [f for f in cfg.feeds if args.all or f.get("enabled", True)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda f: (f, fetch_feed(f, cfg, robots, now)[1]), feeds))

    lines = ["| Flux | Thème | État | Entrées | Dernier article |", "|---|---|---|---|---|"]
    broken = 0
    for feed, st in results:
        ok = st["ok"] and st["entries"] > 0
        broken += not ok
        state = "✅ OK" if ok else f"❌ {st.get('error') or 'aucune entrée'}"
        theme = feed["theme"] if isinstance(feed["theme"], str) else "/".join(feed["theme"])
        lines.append(f"| {feed['name']} | {theme} | {state} | {st['entries']} | {(st.get('latest') or '—')[:10]} |")
        print(f"{'OK ' if ok else 'KO '} {feed['name']:<42} {st['entries']:>3}  {st.get('error', '')}")
    report = "\n".join(["## Vérification des flux", "", f"{len(results) - broken}/{len(results)} flux valides.", "", *lines, ""])
    print(f"\n{len(results) - broken}/{len(results)} flux valides.")
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(report)
    return 1 if (args.strict and broken) else 0


if __name__ == "__main__":
    sys.exit(main())
