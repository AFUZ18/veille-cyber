"""Propose recalibrated KPI targets from the observed values (median of the last N weeks).

python scripts/calibrate_kpi.py      # writes data/kpi_calibration.md (config/kpi.yaml is never modified)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.calibration import write  # noqa: E402
from src.common import load_config, utcnow  # noqa: E402
from src.kpi import load_history  # noqa: E402


def main() -> int:
    cfg = load_config()
    history = load_history(cfg)
    if not history:
        print("Aucun historique de KPI : lancez d'abord le pipeline.")
        return 1
    write(cfg, history, utcnow())
    print(f"Propositions écrites dans {cfg.data_dir / 'kpi_calibration.md'} ({len(history)} mesures). Rien n'a été modifié.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
