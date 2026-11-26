"""The 9 « question » cards of the « Santé de la veille » view (chantier 3).

Each card answers one plain-language question from one or more KPI of the full
referential (config/kpi.yaml > kpis). Four possible answers:
  bon (green) · surveiller (orange) · probleme (red) · sans_donnees (grey)
A card that cannot be measured is ALWAYS « sans_donnees »: never orange or red,
never an action. All texts come from config/kpi.yaml (cartes) and config/ui_texts.yaml.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from .common import THEME_IDS, parse_iso

log = logging.getLogger("veille.cards")

STATUS_TO_ANSWER = {"vert": "bon", "orange": "surveiller", "rouge": "probleme", "info": "bon", "na": "sans_donnees"}
ANSWER_RANK = {"probleme": 0, "surveiller": 1, "bon": 2, "sans_donnees": 3}


class SafeDict(dict):
    """str.format_map helper: unknown variables stay visible instead of crashing."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def fill(template: str, **values: Any) -> str:
    return (template or "").format_map(SafeDict(values))


def num(value: float | None, decimals: int = 0) -> str:
    """French number formatting: 7.25 -> « 7,3 », 12.0 -> « 12 »."""
    if value is None:
        return "?"
    text = f"{value:.{decimals}f}" if decimals else f"{round(value):d}"
    if decimals:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def worst(statuses: list[str]) -> str:
    """Most severe measurable answer, ignoring KPI without data or targets."""
    answers = [STATUS_TO_ANSWER[s] for s in statuses if s in ("vert", "orange", "rouge")]
    if not answers:
        return "sans_donnees" if all(s == "na" for s in statuses) else "bon"
    return min(answers, key=lambda a: ANSWER_RANK[a])


def value_week_ago(history: list[dict[str, Any]], kpi_id: str, now: datetime) -> float | None:
    """KPI value measured 5 to 9 days ago (closest to 7 days), or None."""
    best, best_gap = None, None
    for snap in history:
        age = now - parse_iso(snap["ts"])
        if timedelta(days=5) <= age <= timedelta(days=9):
            gap = abs(age - timedelta(days=7))
            val = (snap.get("kpis", {}).get(kpi_id) or {}).get("value")
            if val is not None and (best_gap is None or gap < best_gap):
                best, best_gap = val, gap
    return best


def trend(texts: dict[str, str], current: float | None, past: float | None, unit: str) -> str | None:
    """Comparison with last week, or None while the history does not allow it (nothing is shown then)."""
    if current is None or past is None:
        return None
    diff = current - past
    if abs(diff) < 0.5:
        return texts["tendance_stable"]
    suffix = " points" if unit == "%" else (" h" if unit == "h" else "")
    ecart = ("+" if diff > 0 else "−") + num(abs(diff), 1) + suffix
    return fill(texts["tendance_hausse" if diff > 0 else "tendance_baisse"], ecart=ecart)


# --------------------------------------------------------------------------- one builder per card


def _sources(ctx, v, card) -> dict[str, Any]:
    st = ctx.feeds_status
    if not st:
        return {"answer": "sans_donnees"}
    ko = [s for s in st if not s.get("ok")]
    names = [s["name"] for s in ko]
    return {
        "answer": STATUS_TO_ANSWER[v["B6_disponibilite_flux"]["status"]],
        "vars": {"ok": len(st) - len(ko), "total": len(st), "ko": len(ko), "liste": ", ".join(names)},
        "details": [f"{s['name']} : {s.get('error') or 'aucune réponse'}" for s in ko],
        "failing_sources": names,
    }


def _rapidite(ctx, v, card) -> dict[str, Any]:
    k = v["B5_delai_reception"]
    if k["value"] is None:
        return {"answer": "sans_donnees", "available_from": k.get("available_from")}
    return {"answer": STATUS_TO_ANSWER[k["status"]], "vars": {"heures": num(k["value"], 1)}}


def _utilite(ctx, v, card) -> dict[str, Any]:
    k = v["A1_pertinence_axe"]
    if k["value"] is None:
        return {"answer": "sans_donnees"}
    labels = ctx.ui.get("sujets", {})
    details = [
        f"{labels.get(ax, ax)} : {num(sub['value'] / 10)} sur 10"
        for ax, sub in (k.get("subs") or {}).items()
        if sub.get("value") is not None
    ]
    return {"answer": STATUS_TO_ANSWER[k["status"]], "vars": {"dixiemes": num(k["value"] / 10)}, "details": details}


def _couverture(ctx, v, card) -> dict[str, Any]:
    k = v["A2_couverture_axe"]
    counts = ctx.details.get("A2_couverture_axe") or {}
    if k["value"] is None or not counts:
        return {"answer": "sans_donnees"}
    labels = ctx.ui.get("sujets", {})
    bars = []
    for ax in THEME_IDS:
        c = counts.get(ax) or {}
        target = c.get("cible_hebdo")
        sub = (k.get("subs") or {}).get(ax) or {}
        answer = STATUS_TO_ANSWER.get(sub.get("status", "na"), "sans_donnees")
        n = c.get("articles_pertinents", 0)
        bars.append({"axe": ax, "nom": labels.get(ax, ax), "n": n, "cible": target, "pct": sub.get("value"), "reponse": answer})
    top = max([b["n"] for b in bars] + [b["cible"] or 0 for b in bars] + [1])
    for b in bars:  # bar length relative to the best-covered topic, so the weakest one stays visible
        b["width"] = round(100 * b["n"] / top)
        b["target_pos"] = round(100 * (b["cible"] or 0) / top)
    weakest = min((b for b in bars if b["pct"] is not None), key=lambda b: b["pct"], default=None)
    out = {"answer": STATUS_TO_ANSWER[k["status"]], "bars": bars}
    if weakest:
        out["vars"] = {"faible_nom": weakest["nom"], "faible_n": weakest["n"], "faible_cible": weakest["cible"]}
        if weakest["pct"] >= 100 and card.get("chiffre_ok"):
            out["chiffre"] = card["chiffre_ok"]
    return out


def _confirmation(ctx, v, card) -> dict[str, Any]:
    k = v["B3_taux_recoupement"]
    if k["value"] is None:
        return {"answer": "sans_donnees"}
    return {"answer": STATUS_TO_ANSWER[k["status"]], "vars": {"dixiemes": num(k["value"] / 10)}}


def _fiabilite(ctx, v, card) -> dict[str, Any]:
    k = v["B1_qualite_moyenne"]
    if k["value"] is None:
        return {"answer": "sans_donnees"}
    scored = sorted((s for s in ctx.source_scores.values() if s.get("sqs") is not None), key=lambda s: s["sqs"])
    weakest = [f"{s['source']} ({num(s['sqs'])}/100)" for s in scored[:3]]
    return {
        "answer": STATUS_TO_ANSWER[k["status"]],
        "vars": {"moyenne": num(k["value"]), "faibles": ", ".join(s["source"] for s in scored[:3])},
        "details": weakest,
    }


def _diversite(ctx, v, card) -> dict[str, Any]:
    f1, f5, e1, f4 = (
        v[i]
        for i in ("F1_part_max_source", "F5_part_sources_francaises", "E1_repartition_langues", "F4_repartition_geographique")
    )
    if f1["value"] is None:
        return {"answer": "sans_donnees"}
    top = (ctx.details.get("F1_part_max_source") or {}).get("source", "?")
    vars_ = {"anglais": num(e1["value"]), "francais": num(f5["value"]), "top": num(f1["value"]), "top_nom": top,
             "pays_top": num(f4["value"])}  # fmt: skip
    out = {"answer": worst([f1["status"], f5["status"], v["F2_concentration_hhi"]["status"]]), "vars": vars_}
    if (e1["value"] or 0) >= 70 or (f4["value"] or 0) >= 50:
        out["message"] = fill(card.get("message", ""), **vars_)
    langs = e1.get("subs") or {}
    out["details"] = [f"Langue {lang.upper()} : {num(s['value'])} %" for lang, s in langs.items() if s.get("value") is not None]
    return out


def _usage(ctx, v, card) -> dict[str, Any]:
    k = v["D1_utilisations"]
    if k["value"] is None:
        return {"answer": "sans_donnees"}
    return {"answer": STATUS_TO_ANSWER[k["status"]], "vars": {"n": num(k["value"])}}


def _emergents(ctx, v, card) -> dict[str, Any]:
    k = v["C1_signaux_faibles"]
    start = ctx.first_measure + timedelta(days=7)
    reliable = ctx.first_measure + timedelta(days=28)
    dates = {"debut": start.strftime("%d/%m/%Y"), "fiable": reliable.strftime("%d/%m/%Y")}
    if k["value"] is None:
        return {"answer": "sans_donnees", "vars": dates, "available_from": start.date().isoformat()}
    details = [f"{s['term']} ({s['count_week']} articles)" for s in ctx.signals[:5]]
    return {"answer": "bon", "vars": {"n": num(k["value"]), **dates}, "details": details}


BUILDERS: dict[str, Callable[..., dict[str, Any]]] = {
    "sources": _sources,
    "rapidite": _rapidite,
    "utilite_articles": _utilite,
    "couverture": _couverture,
    "confirmation": _confirmation,
    "fiabilite_sources": _fiabilite,
    "diversite": _diversite,
    "usage": _usage,
    "emergents": _emergents,
}


def build_cards(ctx, values: dict[str, dict[str, Any]], history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the (max 9) cards. A card that fails to compute becomes « sans_donnees »."""
    texts = (ctx.ui or {}).get("sante", {})
    answers = texts.get("reponses", {})
    kdefs = {k["id"]: k for k in (ctx.cfg.kpi or {}).get("kpis", []) or []}
    out = []
    for card in sorted((ctx.cfg.kpi or {}).get("cartes", []) or [], key=lambda c: c.get("ordre", 99))[:9]:
        try:
            res = BUILDERS[card["id"]](ctx, values, card)
        except Exception as exc:
            log.warning("Carte %s non calculable : %s", card.get("id"), exc)
            res = {"answer": "sans_donnees"}
        answer = res["answer"]
        vars_ = res.get("vars", {})
        main = card["kpis"][0]
        unit = kdefs.get(main, {}).get("unite", "")
        if answer == "sans_donnees":
            reason = fill(card.get("sans_donnees", ""), **vars_)
            avail = res.get("available_from") or (values.get(main) or {}).get("available_from")
            entry = {"chiffre": None, "trend": None, "reason": reason, "available_from": avail}
        else:
            current = (values.get(main) or {}).get("value")
            entry = {
                "chiffre": fill(res.get("chiffre") or card.get("chiffre", ""), **vars_),
                "trend": trend(texts, current, value_week_ago(history, main, ctx.now), unit) if texts else None,
                "reason": None,
                "available_from": None,
            }
        a = answers.get(answer, {})
        entry.update(
            id=card["id"],
            importance=card.get("importance", 9),
            question=card["question"],
            answer=answer,
            answer_label=a.get("libelle", answer),
            icon=a.get("icone", ""),
            color=a.get("couleur", "gris"),
            message=res.get("message"),
            pourquoi=card.get("pourquoi", ""),
            que_faire=card.get("que_faire", ""),
            estimation=bool(card.get("estimation")) and answer != "sans_donnees",
            details=res.get("details", []),
            bars=res.get("bars"),
            kpis=card["kpis"],
            action=fill(card.get("action_probleme", ""), **vars_) if answer == "probleme" else None,
            failing_sources=res.get("failing_sources", []),
        )
        out.append(entry)
    return out


def plural(texts: dict[str, str], key: str, n: int) -> str:
    return texts.get(f"{key}_1" if n == 1 else f"{key}_n", "")


def verdict(cards: list[dict[str, Any]], texts: dict[str, Any]) -> dict[str, Any]:
    """Honest global verdict: counts per answer, no misleading average."""
    groups = {k: [c["question"] for c in cards if c["answer"] == k] for k in ("bon", "surveiller", "probleme", "sans_donnees")}
    n = {k: len(v) for k, v in groups.items()}
    sentence = fill(
        texts.get("verdict", ""),
        bon=n["bon"], bon_txt=plural(texts, "verdict_bon", n["bon"]),
        surveiller=n["surveiller"], surveiller_txt=plural(texts, "verdict_surveiller", n["surveiller"]),
        probleme=n["probleme"], probleme_txt=plural(texts, "verdict_probleme", n["probleme"]),
        sans=n["sans_donnees"], sans_txt=plural(texts, "verdict_sans", n["sans_donnees"]),
    )  # fmt: skip
    return {"sentence": sentence, "counts": n, "groups": groups}


def priorities(cards: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    """« À traiter en premier »: problems first, then watch items, by importance. Never cards without data."""
    candidates = [c for c in cards if c["answer"] in ("probleme", "surveiller")]
    candidates.sort(key=lambda c: (ANSWER_RANK[c["answer"]], c["importance"]))
    out = []
    for c in candidates:
        text = c["action"] if c["answer"] == "probleme" and c.get("action") else c["que_faire"]
        if text:
            out.append({"card": c["id"], "question": c["question"], "answer": c["answer"], "answer_label": c["answer_label"],
                        "icon": c["icon"], "text": text})  # fmt: skip
        if len(out) >= limit:
            break
    return out
