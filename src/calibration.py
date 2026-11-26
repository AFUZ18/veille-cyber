"""End of the learning period: propose recalibrated KPI targets (never applied automatically).

Proposal = median of the values really observed during the last N weeks of history
(one value per day: the last measurement of the day). The result is written to
data/kpi_calibration.md for a human to validate; config/kpi.yaml is NEVER modified.
"""

from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta
from typing import Any

from .common import Config, parse_iso

log = logging.getLogger("veille.calibration")

CALIBRATION_FILE = "kpi_calibration.md"


def daily_values(history: list[dict[str, Any]], kpi_id: str, since: datetime) -> list[float]:
    by_day: dict[str, float] = {}
    for snap in history:
        if parse_iso(snap["ts"]) < since:
            continue
        val = (snap.get("kpis", {}).get(kpi_id) or {}).get("value")
        if val is not None:
            by_day[snap["ts"][:10]] = float(val)
    return list(by_day.values())


def nice(value: float) -> float:
    """Round a proposal to a readable number (no false precision)."""
    if abs(value) >= 1000:
        return round(value, -2)
    if abs(value) >= 100:
        return round(value, -1)
    if abs(value) >= 10:
        return float(round(value))
    return round(value, 1)


def propose(cfg: Config, history: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    weeks = int((cfg.kpi or {}).get("mode_apprentissage_semaines", 4))
    since = now - timedelta(weeks=weeks)
    rows = []
    for k in (cfg.kpi or {}).get("kpis", []) or []:
        if k.get("sens") not in ("hausse", "baisse") or k.get("cible") is None:
            continue
        vals = daily_values(history, k["id"], since)
        row = {"id": k["id"], "nom": k["nom"], "unite": k.get("unite", ""), "sens": k["sens"], "cible": k["cible"],
               "seuil": k.get("seuil_alerte"), "n": len(vals)}  # fmt: skip
        if len(vals) >= 7:  # at least one week of daily values
            med = statistics.median(vals)
            row.update(mediane=round(med, 1), mini=round(min(vals), 1), maxi=round(max(vals), 1))
            if k["sens"] == "hausse":
                row.update(cible_proposee=nice(med), seuil_propose=nice(med * 0.75))
            else:
                row.update(cible_proposee=nice(med), seuil_propose=nice(med * 1.5 if med else 1))
        rows.append(row)
    return rows


def render(rows: list[dict[str, Any]], now: datetime, weeks: int) -> str:
    def fmt(v: Any) -> str:
        return "—" if v is None else str(v).replace(".", ",")

    lines = [
        "# Proposition de recalibrage des objectifs (à valider)",
        "",
        f"_Généré le {now.strftime('%d/%m/%Y')} à la fin de la période d'observation de {weeks} semaines._",
        "",
        "**Rien n'a été modifié automatiquement.** Pour adopter une proposition, recopiez la valeur dans "
        "`config/kpi.yaml` (`cible`, `seuil_alerte`), puis lancez `python scripts/kpi_doc.py`.",
        "",
        "Méthode : la cible proposée est la **médiane** des valeurs observées (une valeur par jour) ; "
        "le seuil d'alerte proposé est 25 % moins bon que la médiane (50 % pour les indicateurs « plus bas = mieux »). "
        "Ajustez selon vos ambitions : une cible égale à la médiane signifie « faire au moins aussi bien qu'aujourd'hui ».",
        "",
        "| Indicateur | Sens | Cible actuelle | Seuil actuel | Médiane observée | Min – max | Cible proposée | Seuil proposé | Jours mesurés |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        sens = "plus haut = mieux" if r["sens"] == "hausse" else "plus bas = mieux"
        if "mediane" in r:
            lines.append(
                f"| {r['nom']} ({r['unite']}) | {sens} | {fmt(r['cible'])} | {fmt(r['seuil'])} | {fmt(r['mediane'])} | "
                f"{fmt(r['mini'])} – {fmt(r['maxi'])} | **{fmt(r['cible_proposee'])}** | **{fmt(r['seuil_propose'])}** | {r['n']} |"
            )
        else:
            lines.append(
                f"| {r['nom']} ({r['unite']}) | {sens} | {fmt(r['cible'])} | {fmt(r['seuil'])} | pas assez de mesures | — | — | — | {r['n']} |"
            )
    return "\n".join(lines) + "\n"


def write(cfg: Config, history: list[dict[str, Any]], now: datetime) -> str:
    weeks = int((cfg.kpi or {}).get("mode_apprentissage_semaines", 4))
    text = render(propose(cfg, history, now), now, weeks)
    (cfg.data_dir / CALIBRATION_FILE).write_text(text, "utf-8")
    return text


def maybe_write(cfg: Config, learning: dict[str, Any], now: datetime) -> bool:
    """Write the proposal once, when the learning period is over (the file is never overwritten)."""
    path = cfg.data_dir / CALIBRATION_FILE
    if learning.get("active") or path.exists():
        return False
    from .kpi import load_history

    write(cfg, load_history(cfg), now)
    log.info("Fin de la période d'observation : propositions d'objectifs dans data/%s", CALIBRATION_FILE)
    return True
