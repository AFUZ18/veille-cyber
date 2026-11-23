"""KPI engine: computation, target evaluation, history, continuous-improvement actions (SLA).

Every KPI is declared in config/kpi.yaml. Its `calcul` field names a function of the
CALCULATORS registry below. A KPI that cannot be computed (missing data, error) is
reported as « non disponible » and never stops the pipeline.

Outputs (data/):
- kpi_history.jsonl        one snapshot per run, kept forever
- kpi_latest.json          last report (used by the site and the Monday e-mail)
- improvement_actions.json state of the SLA actions (open / resolved)
- improvement_actions.md   human-readable improvement plan
"""

from __future__ import annotations

import csv
import io
import json
import logging
import statistics
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .common import THEME_IDS, Config, iso, parse_iso, read_json, write_json
from .quality import ttri_delays
from .usage import OFFTOPIC_TYPE

log = logging.getLogger("veille.kpi")

HISTORY_FILE = "kpi_history.jsonl"
LATEST_FILE = "kpi_latest.json"
ACTIONS_FILE = "improvement_actions.json"
ACTIONS_MD = "improvement_actions.md"

STATUS_LABELS = {
    "vert": "Dans la cible",
    "orange": "À surveiller",
    "rouge": "Hors seuil",
    "info": "Observation",
    "na": "Non disponible",
}
OFF_TARGET = ("orange", "rouge")
PERIOD_DAYS = {"execution": 7, "jour": 1, "semaine": 7, "mois": 30}

Value = float | None


@dataclass
class KpiContext:
    """Everything a KPI calculator may need."""

    articles: list[dict[str, Any]]
    cfg: Config
    now: datetime
    feeds_status: list[dict[str, Any]] = field(default_factory=list)
    usage: list[dict[str, Any]] = field(default_factory=list)
    signals: list[dict[str, Any]] = field(default_factory=list)
    source_scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)  # extra info shown on the KPI page
    signals_warmup: str | None = None  # set while the reference history is too short

    @property
    def params(self) -> dict[str, Any]:
        return (self.cfg.kpi or {}).get("parametres", {}) or {}

    @property
    def threshold(self) -> float:
        return float(self.params.get("seuil_pertinence", 35))

    def recent(self, days: int) -> list[dict[str, Any]]:
        limit = self.now - timedelta(days=days)
        return [a for a in self.articles if parse_iso(a["published"]) >= limit]

    def recent_usage(self) -> list[dict[str, Any]]:
        days = int(self.params.get("fenetre_usage_jours", 30))
        limit = (self.now - timedelta(days=days)).date().isoformat()
        return [u for u in self.usage if (u.get("date") or "") >= limit]


def pct(part: float, total: float) -> Value:
    return round(100 * part / total, 1) if total else None


def result(value: Value, subs: dict[str, Value] | None = None) -> dict[str, Any]:
    return {"value": value, "subs": subs}


# --------------------------------------------------------------------------- A. relevance


def relevance_share_by_axis(ctx: KpiContext) -> dict[str, Any]:
    arts = ctx.recent(7)
    subs = {}
    for axis in THEME_IDS:
        in_axis = [a for a in arts if axis in a.get("themes", [])]
        subs[axis] = pct(sum(a.get("relevance", 0) >= ctx.threshold for a in in_axis), len(in_axis))
    return result(pct(sum(a.get("relevance", 0) >= ctx.threshold for a in arts), len(arts)), subs)


def weekly_coverage_by_axis(ctx: KpiContext) -> dict[str, Any]:
    arts = ctx.recent(7)
    subs, counts = {}, {}
    for axis in THEME_IDS:
        target = ((ctx.cfg.themes.get("themes", {}).get(axis, {}) or {}).get("objectifs") or {}).get("cible_hebdo")
        n = sum(axis in a.get("themes", []) and a.get("relevance", 0) >= ctx.threshold for a in arts)
        counts[axis] = {"articles_pertinents": n, "cible_hebdo": target}
        subs[axis] = round(100 * n / target, 1) if target else None
    ctx.details["A2_couverture_axe"] = counts
    vals = [v for v in subs.values() if v is not None]
    return result(round(min(vals), 1) if vals else None, subs)


def offtopic_time_share(ctx: KpiContext) -> dict[str, Any]:
    entries = [u for u in ctx.recent_usage() if u["kind"] == "usage"]
    return result(pct(sum(u["type"] == OFFTOPIC_TYPE for u in entries), len(entries)))


# --------------------------------------------------------------------------- B. source quality


def average_source_quality(ctx: KpiContext) -> dict[str, Any]:
    vals = [s["sqs"] for s in ctx.source_scores.values() if s.get("sqs") is not None]
    return result(round(statistics.mean(vals), 1) if vals else None)


def source_quality_by_source(ctx: KpiContext) -> dict[str, Any]:
    subs = {name: s.get("sqs") for name, s in ctx.source_scores.items()}
    vals = [v for v in subs.values() if v is not None]
    return result(round(min(vals), 1) if vals else None, subs)


def corroboration_rate(ctx: KpiContext) -> dict[str, Any]:
    min_orgs = ctx.cfg.settings.get("quality", {}).get("min_independent_sources", 2)
    important = [a for a in ctx.recent(7) if a.get("level") in ("Élevé", "Critique")]
    return result(pct(sum(len(a.get("corroboration_orgs") or []) >= min_orgs for a in important), len(important)))


def unreferenced_articles(ctx: KpiContext) -> dict[str, Any]:
    arts = ctx.recent(7)
    bad = [a for a in arts if a.get("reliability") == "Source non référencée"]
    ctx.details["B4_sources_non_referencees"] = sorted({a.get("domain", "") for a in bad})
    return result(float(len(bad)) if arts else None)


def time_to_receive(ctx: KpiContext) -> dict[str, Any]:
    delays = [d for values in ttri_delays(ctx.recent(7), ctx.cfg).values() for d in values]
    return result(round(statistics.median(delays), 1) if delays else None)


def feed_availability(ctx: KpiContext) -> dict[str, Any]:
    st = ctx.feeds_status
    return result(pct(sum(bool(s.get("ok")) for s in st), len(st)))


def feed_availability_by_source(ctx: KpiContext) -> dict[str, Any]:
    subs = {s["name"]: (100.0 if s.get("ok") else 0.0) for s in ctx.feeds_status}
    return result(pct(sum(v == 100 for v in subs.values()), len(subs)), subs)


# --------------------------------------------------------------------------- C. weak signals


def weak_signals_count(ctx: KpiContext) -> dict[str, Any]:
    if ctx.signals_warmup:
        ctx.details["C1_signaux_faibles"] = {"apprentissage": ctx.signals_warmup}
        return result(None)
    subs = {axis: float(sum(s.get("axis") == axis for s in ctx.signals)) for axis in THEME_IDS}
    return result(float(len(ctx.signals)), subs)


# --------------------------------------------------------------------------- D. utility


def usage_count(ctx: KpiContext) -> dict[str, Any]:
    entries = [u for u in ctx.recent_usage() if u["kind"] == "usage" and u["type"] != OFFTOPIC_TYPE]
    by_type = Counter(u["type"] for u in entries)
    ctx.details["D1_utilisations"] = dict(by_type)
    return result(float(len(entries)))


def transformed_signals_count(ctx: KpiContext) -> dict[str, Any]:
    return result(float(sum(u["kind"] == "signal" for u in ctx.recent_usage())))


def detected_signals_window(ctx: KpiContext) -> set[str]:
    """Distinct weak-signal keys detected over the usage window (history + current run)."""
    days = int(ctx.params.get("fenetre_usage_jours", 30))
    limit = ctx.now - timedelta(days=days)
    keys = {s["key"] for s in ctx.signals}
    for snap in ctx.history:
        if parse_iso(snap["ts"]) >= limit:
            keys.update(snap.get("signals", []))
    return keys


def transformation_rate(ctx: KpiContext) -> dict[str, Any]:
    detected = detected_signals_window(ctx)
    transformed = sum(u["kind"] == "signal" for u in ctx.recent_usage())
    ctx.details["D3_taux_transformation"] = {"detectes": len(detected), "transformes": transformed}
    if not detected:
        return result(None)
    return result(round(min(100.0, 100 * transformed / len(detected)), 1))


# --------------------------------------------------------------------------- E. double translation


def language_distribution(ctx: KpiContext) -> dict[str, Any]:
    arts = ctx.recent(7)
    langs = Counter(a.get("source_language") or a.get("language", "en") for a in arts)
    subs = {lang: pct(n, len(arts)) for lang, n in sorted(langs.items())}
    return result(pct(sum(n for lang, n in langs.items() if lang != "fr"), len(arts)), subs)


def single_translation_share(ctx: KpiContext) -> dict[str, Any]:
    arts = ctx.recent(7)
    ok = sum(a.get("translation_steps", 0) <= 1 and a.get("summary_from", "original") == "original" for a in arts)
    return result(pct(ok, len(arts)))


def glossary_assisted_share(ctx: KpiContext) -> dict[str, Any]:
    arts = ctx.recent(7)
    return result(pct(sum(bool(a.get("glossary_axes_added")) for a in arts), len(arts)))


# --------------------------------------------------------------------------- F. bias & diversity


def _source_shares(ctx: KpiContext) -> dict[str, float]:
    arts = ctx.recent(7)
    counts = Counter(a["source"] for a in arts)
    return {s: 100 * n / len(arts) for s, n in counts.items()} if arts else {}


def max_source_share(ctx: KpiContext) -> dict[str, Any]:
    shares = _source_shares(ctx)
    if not shares:
        return result(None)
    top = max(shares, key=lambda s: shares[s])
    ctx.details["F1_part_max_source"] = {"source": top}
    return result(round(shares[top], 1))


def herfindahl_index(ctx: KpiContext) -> dict[str, Any]:
    shares = _source_shares(ctx)
    return result(round(sum(v * v for v in shares.values())) if shares else None)


def _distribution(ctx: KpiContext, key: str) -> dict[str, Value]:
    arts = ctx.recent(7)
    counts = Counter(a.get(key) or "inconnu" for a in arts)
    return {k: pct(n, len(arts)) for k, n in counts.most_common()}


def source_type_distribution(ctx: KpiContext) -> dict[str, Any]:
    subs = _distribution(ctx, "source_type")
    return result(subs.get("éditeur", 0.0) if subs else None, subs)  # main value: commercial-source share


def geo_distribution(ctx: KpiContext) -> dict[str, Any]:
    subs = _distribution(ctx, "source_country")
    return result(max(subs.values()) if subs else None, subs)


def french_share(ctx: KpiContext) -> dict[str, Any]:
    arts = ctx.recent(7)
    return result(pct(sum(a.get("source_country") == "FR" for a in arts), len(arts)))


CALCULATORS: dict[str, Callable[[KpiContext], dict[str, Any]]] = {
    f.__name__: f
    for f in (
        relevance_share_by_axis,
        weekly_coverage_by_axis,
        offtopic_time_share,
        average_source_quality,
        source_quality_by_source,
        corroboration_rate,
        unreferenced_articles,
        time_to_receive,
        feed_availability,
        feed_availability_by_source,
        weak_signals_count,
        usage_count,
        transformed_signals_count,
        transformation_rate,
        language_distribution,
        single_translation_share,
        glossary_assisted_share,
        max_source_share,
        herfindahl_index,
        source_type_distribution,
        geo_distribution,
        french_share,
    )
}


# --------------------------------------------------------------------------- evaluation


def evaluate(value: Value, kdef: dict[str, Any]) -> str:
    """vert / orange / rouge / info / na."""
    if value is None:
        return "na"
    direction = kdef.get("sens", "info")
    target, alert = kdef.get("cible"), kdef.get("seuil_alerte")
    if direction == "info" or target is None:
        return "info"
    if direction == "hausse":
        if value >= target:
            return "vert"
        return "rouge" if alert is not None and value < alert else "orange"
    if value <= target:
        return "vert"
    return "rouge" if alert is not None and value > alert else "orange"


def compute_all(ctx: KpiContext) -> dict[str, dict[str, Any]]:
    """Run every KPI of config/kpi.yaml. Errors => « non disponible », never an exception."""
    out: dict[str, dict[str, Any]] = {}
    for kdef in (ctx.cfg.kpi or {}).get("kpis", []) or []:
        fn = CALCULATORS.get(kdef.get("calcul", ""))
        try:
            res = fn(ctx) if fn else result(None)
            if fn is None:
                log.warning("KPI %s : fonction de calcul inconnue « %s »", kdef["id"], kdef.get("calcul"))
        except Exception as exc:
            log.warning("KPI %s non calculable : %s", kdef["id"], exc)
            res = result(None)
        subs = res.get("subs")
        out[kdef["id"]] = {
            "value": res["value"],
            "status": evaluate(res["value"], kdef),
            "subs": {k: {"value": v, "status": evaluate(v, kdef)} for k, v in subs.items()} if subs else None,
        }
    return out


# --------------------------------------------------------------------------- history


def load_history(cfg: Config) -> list[dict[str, Any]]:
    path = cfg.data_dir / HISTORY_FILE
    if not path.exists():
        return []
    out = []
    for line in path.read_text("utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def append_history(cfg: Config, snapshot: dict[str, Any]) -> None:
    path = cfg.data_dir / HISTORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def bucket_key(ts: str, period: str, index: int) -> str:
    dt = parse_iso(ts)
    if period == "execution":
        return str(index)
    if period == "jour":
        return dt.date().isoformat()
    if period == "mois":
        return dt.strftime("%Y-%m")
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def status_series(history: list[dict[str, Any]], kpi_id: str, sub: str | None, period: str) -> list[str]:
    """Status of the last snapshot of each period bucket, oldest first."""
    buckets: dict[str, str] = {}
    for i, snap in enumerate(history):
        k = snap.get("kpis", {}).get(kpi_id)
        if not k:
            continue
        if sub is not None:
            k = (k.get("subs") or {}).get(sub)
            if not k:
                continue
        buckets[bucket_key(snap["ts"], period, i)] = k.get("status", "na")
    return list(buckets.values())


def consecutive_off_target(statuses: list[str]) -> int:
    """Number of trailing periods out of target (« non disponible » periods are skipped)."""
    count = 0
    for st in reversed(statuses):
        if st == "na":
            continue
        if st in OFF_TARGET:
            count += 1
        else:
            break
    return count


# --------------------------------------------------------------------------- SLA actions


def update_actions(cfg: Config, history: list[dict[str, Any]], now: datetime) -> dict[str, dict[str, Any]]:
    """Open an action when a KPI stays off target N consecutive periods; resolve it when back on target."""
    state = read_json(cfg.data_dir / ACTIONS_FILE, {}).get("actions", {})
    latest = history[-1]["kpis"] if history else {}
    for kdef in (cfg.kpi or {}).get("kpis", []) or []:
        needed = int(kdef.get("periodes_consecutives") or 0)
        if needed <= 0 or not kdef.get("action"):
            continue
        current = latest.get(kdef["id"]) or {}
        targets: list[tuple[str | None, str]] = (
            [(sub, v.get("status", "na")) for sub, v in (current.get("subs") or {}).items()]
            if kdef.get("par")
            else [(None, current.get("status", "na"))]
        )
        for sub, status in targets:
            key = f"{kdef['id']}|{sub or ''}"
            n = consecutive_off_target(status_series(history, kdef["id"], sub, kdef.get("periode", "semaine")))
            action = state.get(key)
            if n >= needed:
                text = kdef["action"].replace("{sujet}", sub or "")
                if action is None or action.get("status") != "ouverte":
                    action = {"key": key, "kpi": kdef["id"], "kpi_nom": kdef["nom"], "sujet": sub,
                              "first_seen": iso(now), "status": "ouverte"}  # fmt: skip
                action.update(action=text, last_seen=iso(now), periods=n, kpi_status=status)
                state[key] = action
            elif action and action.get("status") == "ouverte" and status == "vert":
                action.update(status="résolue", resolved=iso(now))
    write_json(cfg.data_dir / ACTIONS_FILE, {"updated": iso(now), "actions": state})
    return state


def render_actions_md(actions: dict[str, dict[str, Any]], now: datetime) -> str:
    open_ = sorted((a for a in actions.values() if a["status"] == "ouverte"), key=lambda a: a["first_seen"])
    closed = sorted(
        (a for a in actions.values() if a["status"] == "résolue" and parse_iso(a["resolved"]) >= now - timedelta(days=60)),
        key=lambda a: a["resolved"],
        reverse=True,
    )
    lines = [
        "# Plan d'amélioration continue de la veille",
        "",
        f"_Mis à jour automatiquement le {now.strftime('%d/%m/%Y %H:%M')} UTC à partir des KPI (config/kpi.yaml)._",
        "",
        f"## Actions ouvertes ({len(open_)})",
        "",
    ]
    if open_:
        lines += ["| Depuis | KPI | Concerne | Action | Périodes hors cible |", "|---|---|---|---|---|"]
        for a in open_:
            sujet = (a.get("sujet") or "—").replace("|", "/")
            act = a["action"].replace("|", "/")
            lines.append(f"| {a['first_seen'][:10]} | {a['kpi_nom']} | {sujet} | {act} | {a.get('periods', '')} |")
    else:
        lines.append("_Aucune action ouverte : tous les KPI suivis sont dans leur cible ou en observation._")
    lines += ["", "## Actions résolues (60 derniers jours)", ""]
    lines += [f"- {a['resolved'][:10]} · {a['kpi_nom']} · {a.get('sujet') or '—'}" for a in closed] or ["_Aucune._"]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- report for the site / e-mail


def daily_series(history: list[dict[str, Any]], kpi_id: str, sub: str | None = None, days: int = 366) -> list[list[Any]]:
    """[[date, value], …] last value of each day (used for 4/12/52-week trend charts)."""
    by_day: dict[str, Any] = {}
    for snap in history:
        k = snap.get("kpis", {}).get(kpi_id) or {}
        if sub is not None:
            k = (k.get("subs") or {}).get(sub) or {}
        by_day[snap["ts"][:10]] = k.get("value")
    return [[d, v] for d, v in sorted(by_day.items())][-days:]


def build_report(
    ctx: KpiContext, values: dict[str, dict[str, Any]], history: list[dict[str, Any]], actions: dict
) -> dict[str, Any]:
    kpis = []
    for kdef in (ctx.cfg.kpi or {}).get("kpis", []) or []:
        v = values.get(kdef["id"], {"value": None, "status": "na", "subs": None})
        entry = {k: kdef.get(k) for k in ("id", "nom", "famille", "smart", "formule", "unite", "periode", "sens",
                                          "cible", "seuil_alerte", "par", "responsable", "action")}  # fmt: skip
        entry.update(v, status_label=STATUS_LABELS[v["status"]], details=ctx.details.get(kdef["id"]),
                     trend=daily_series(history, kdef["id"]))  # fmt: skip
        if kdef.get("par") == "axe":
            entry["sub_trends"] = {ax: daily_series(history, kdef["id"], ax) for ax in THEME_IDS}
        kpis.append(entry)
    return {
        "generated_at": iso(ctx.now),
        "kpis": kpis,
        "sources": sorted(ctx.source_scores.values(), key=lambda s: (s["sqs"] is None, -(s["sqs"] or 0))),
        "signals": ctx.signals,
        "actions": sorted(actions.values(), key=lambda a: (a["status"] != "ouverte", a.get("first_seen", ""))),
        "usage_total": len(ctx.usage),
    }


def history_csv(history: list[dict[str, Any]], cfg: Config) -> str:
    """Flatten the KPI history for Excel / Power BI (separator « ; », UTF-8 with BOM)."""
    defs = {k["id"]: k for k in (cfg.kpi or {}).get("kpis", []) or []}
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["horodatage", "kpi_id", "kpi_nom", "famille", "element", "valeur", "unite", "cible", "seuil_alerte", "statut"])
    for snap in history:
        for kid, k in sorted(snap.get("kpis", {}).items()):
            d = defs.get(kid, {})
            rows = [("", k)] + sorted((k.get("subs") or {}).items())
            for sub, item in rows:
                val = item.get("value")
                w.writerow(
                    [
                        snap["ts"],
                        kid,
                        d.get("nom", kid),
                        d.get("famille", ""),
                        sub,
                        "" if val is None else str(val).replace(".", ","),
                        d.get("unite", ""),
                        d.get("cible", ""),
                        d.get("seuil_alerte", ""),
                        STATUS_LABELS.get(item.get("status"), ""),
                    ]
                )
    return "﻿" + buf.getvalue()


def run(ctx: KpiContext) -> dict[str, Any]:
    """Compute, historise, evaluate SLA and return the report (written to data/kpi_latest.json)."""
    ctx.history = load_history(ctx.cfg)
    values = compute_all(ctx)
    snapshot = {"ts": iso(ctx.now), "kpis": values, "signals": [s["key"] for s in ctx.signals]}
    append_history(ctx.cfg, snapshot)
    history = ctx.history + [snapshot]
    actions = update_actions(ctx.cfg, history, ctx.now)
    (ctx.cfg.data_dir / ACTIONS_MD).write_text(render_actions_md(actions, ctx.now), "utf-8")
    report = build_report(ctx, values, history, actions)
    write_json(ctx.cfg.data_dir / LATEST_FILE, report)
    counts = Counter(v["status"] for v in values.values())
    log.info("KPI : %s ; %d action(s) ouverte(s)", ", ".join(f"{STATUS_LABELS[k]}={n}" for k, n in counts.items()),
             sum(a["status"] == "ouverte" for a in actions.values()))  # fmt: skip
    return report
