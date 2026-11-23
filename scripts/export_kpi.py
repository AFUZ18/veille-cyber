"""Export the KPI history (data/kpi_history.jsonl) to CSV for Excel or Power BI.

  python scripts/export_kpi.py                       # writes kpi_historique.csv
  python scripts/export_kpi.py -o /chemin/export.csv
The same file is published on the site: <site>/kpi_history.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.common import load_config  # noqa: E402
from src.kpi import history_csv, load_history  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export CSV de l'historique des KPI")
    parser.add_argument("-o", "--output", type=Path, default=Path("kpi_historique.csv"))
    args = parser.parse_args()
    cfg = load_config()
    history = load_history(cfg)
    args.output.write_text(history_csv(history, cfg), encoding="utf-8")
    print(f"{len(history)} instantané(s) exporté(s) vers {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
