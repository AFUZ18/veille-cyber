"""Weekly digest: Markdown archive (always) + Outlook-safe HTML e-mail with plain-text fallback.

Usage:
  python -m src.newsletter                 # build archive + preview only (no e-mail)
  python -m src.newsletter --send          # send to every enabled recipient group
  python -m src.newsletter --send --test   # send to the « interne » group only
  python -m src.newsletter --send --respect-schedule   # used by cron: only sends at 07:00 Europe/Paris
"""

from __future__ import annotations

import argparse
import html
import logging
import os
import smtplib
import ssl
import sys
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any
from zoneinfo import ZoneInfo

from .build_site import events_payload, safe_url
from .common import (
    ARTICLES_FILE,
    ROOT,
    THEME_IDS,
    Config,
    iso,
    load_config,
    parse_iso,
    read_json,
    setup_logging,
    utcnow,
    write_json,
)
from .score import load_kev

log = logging.getLogger("veille.newsletter")

LEVEL_COLORS = {  # (text, background) — readable in light AND dark e-mail clients
    "Critique": ("#ffffff", "#b3261e"),
    "Élevé": ("#ffffff", "#a04e00"),
    "Moyen": ("#1f1a00", "#f2d24b"),
    "Info": ("#ffffff", "#2f6b5b"),
}


# --------------------------------------------------------------------------- selection


def week_label(now_local: datetime) -> tuple[str, int, int]:
    """ISO week covered by the digest = the week that just ended (yesterday)."""
    ref = (now_local - timedelta(days=1)).date()
    year, week, _ = ref.isocalendar()
    return f"{year}-W{week:02d}", year, week


def _rank(a: dict[str, Any]) -> tuple:
    return (a.get("criticality", 0) + a.get("relevance", 0), a.get("kev", False), a["published"])


def select_content(articles: list[dict[str, Any]], cfg: Config, now: datetime) -> dict[str, Any]:
    nl = cfg.settings["newsletter"]
    tz = ZoneInfo(nl["timezone"])
    now_local = now.astimezone(tz)
    week_start = now - timedelta(days=7)
    recent = [a for a in articles if parse_iso(a["published"]) >= week_start]

    top = sorted(recent, key=_rank, reverse=True)[: nl["top_items"]]

    # H3 cadence: "mensuelle" => detailed block only on the first Monday of the month (30-day window)
    monthly = nl.get("cadence_h3", "mensuelle").startswith("mens")
    h3_full = (not monthly) or now_local.day <= 7
    blocks: dict[str, dict[str, Any]] = {}
    for theme in THEME_IDS:
        pool = recent
        if theme == "H3" and monthly and h3_full:
            pool = [a for a in articles if parse_iso(a["published"]) >= now - timedelta(days=30)]
        items = sorted((a for a in pool if theme in a.get("themes", [])), key=_rank, reverse=True)
        limit = nl["items_per_theme"] if (theme != "H3" or h3_full) else nl["min_items_per_theme"]
        blocks[theme] = {
            "label": cfg.themes["themes"][theme]["label"],
            "items": items[:limit],
            "detailed": theme != "H3" or h3_full,
            "note": (
                "Synthèse mensuelle détaillée (30 derniers jours)."
                if theme == "H3" and monthly and h3_full
                else "Cadence mensuelle : titres seulement cette semaine, synthèse détaillée le premier lundi du mois."
                if theme == "H3" and monthly
                else ""
            ),
        }

    kev_catalog = load_kev(cfg)
    kev_cves: dict[str, dict[str, Any]] = {}
    for a in sorted(recent, key=_rank, reverse=True):
        for cve in a.get("cves", []):
            if cve in kev_catalog and cve not in kev_cves:
                info = kev_catalog[cve]
                kev_cves[cve] = {
                    "product": f"{info.get('vendor', '')} {info.get('product', '')}".strip(),
                    "ransomware": info.get("ransomware", False),
                    "article": a,
                }

    actions, seen = [], set()
    for a in sorted(recent, key=_rank, reverse=True):
        act = a.get("action")
        if act and act.lower() not in seen:
            seen.add(act.lower())
            actions.append({"text": act, "type": a.get("action_type"), "article": a})
    events = [e for e in events_payload(cfg.events, now_local.date()) if not e["past"]][:3]

    label, year, week = week_label(now_local)
    return {
        "label": label,
        "year": year,
        "week": week,
        "now_local": now_local,
        "top": top,
        "blocks": blocks,
        "kev": kev_cves,
        "actions": actions[:8],
        "events": events,
        "total_week": len(recent),
        "health": health_summary(cfg),
    }


def health_summary(cfg: Config) -> dict[str, Any] | None:
    """« Santé de la veille » block from data/kpi_latest.json (None if KPI are not available)."""
    report = read_json(cfg.data_dir / "kpi_latest.json", None)
    if not report or not report.get("kpis"):
        return None
    order = {"rouge": 0, "orange": 1}
    off = sorted((k for k in report["kpis"] if k.get("status") in order), key=lambda k: (order[k["status"]], k["id"]))
    return {
        "off_target": [
            {
                "nom": k["nom"],
                "value": k["value"],
                "unite": k.get("unite") or "",
                "cible": k.get("cible"),
                "sens": k.get("sens"),
                "status": k["status_label"],
            }  # fmt: skip
            for k in off[:6]
        ],
        "off_count": len(off),
        "signals": [
            {"term": sg["term"], "axis": sg.get("axis"), "count": sg["count_week"]} for sg in report.get("signals", [])[:5]
        ],
        "actions": [a for a in report.get("actions", []) if a.get("status") == "ouverte"][:5],
    }


def _fmt_num(v: Any) -> str:
    return "n.d." if v is None else f"{v:g}".replace(".", ",")


def subject(content: dict[str, Any]) -> str:
    n = len(content["top"])
    return f"Veille cyber – semaine {content['week']} : {n} fait{'s' if n > 1 else ''} marquant{'s' if n > 1 else ''}"


def _fmt_date(iso_str: str) -> str:
    return date.fromisoformat(iso_str[:10]).strftime("%d/%m/%Y")


# --------------------------------------------------------------------------- Markdown


def _md(text: str) -> str:
    return "".join("\\" + c if c in "\\`*_[]<>|#" else c for c in (text or ""))


def render_markdown(c: dict[str, Any], site_url: str) -> str:
    out = [
        f"# Veille cyber – semaine {c['week']} ({c['label']})",
        "",
        f"*Générée le {c['now_local'].strftime('%d/%m/%Y à %H:%M')} – {c['total_week']} articles collectés sur 7 jours – [site]({site_url})*",
        "",
    ]

    def item(a: dict[str, Any], detailed: bool = True) -> list[str]:
        url = safe_url(a["url"]).replace(")", "%29")
        line = [
            f"- **[{_md(a['title'])}]({url})** — {_md(a['source'])}, {_fmt_date(a['published'])} · {a['level']}"
            + (" · KEV" if a.get("kev") else "")
        ]
        if detailed and a.get("summary"):
            line.append(f"  {_md(a['summary'])}")
        if detailed and a.get("why"):
            line.append(f"  *Pourquoi c'est important :* {_md(a['why'])}")
        return line

    out += ["## Les faits marquants", ""]
    for a in c["top"] or []:
        out += item(a)
    if not c["top"]:
        out.append("_Aucun article cette semaine._")
    for theme, block in c["blocks"].items():
        out += ["", f"## {theme} – {block['label']}", ""]
        if block["note"]:
            out += [f"_{block['note']}_", ""]
        for a in block["items"]:
            out += item(a, block["detailed"])
        if not block["items"]:
            out.append("_Rien de notable._")
    out += ["", "## CVE exploitées activement (CISA KEV) citées cette semaine", ""]
    for cve, info in c["kev"].items():
        out.append(f"- **{cve}** – {_md(info['product'])}" + (" – utilisée par des rançongiciels" if info["ransomware"] else ""))
    if not c["kev"]:
        out.append("_Aucune._")
    out += ["", "## Actions recommandées", ""]
    for act in c["actions"]:
        out.append(
            f"- {('[' + act['type'] + '] ') if act['type'] else ''}{_md(act['text'])} _(source : {_md(act['article']['source'])})_"
        )
    if not c["actions"]:
        out.append("_Aucune action spécifique (résumés IA indisponibles ou rien d'urgent)._")
    h = c.get("health")
    if h:
        out += ["", "## Santé de la veille", ""]
        if h["off_target"]:
            out.append(f"**KPI hors cible ({h['off_count']})** :")
            for k in h["off_target"]:
                comp = "≤" if k["sens"] == "baisse" else "≥"
                out.append(
                    f"- {_md(k['nom'])} : {_fmt_num(k['value'])} {k['unite']} (cible {comp} {_fmt_num(k['cible'])}) – {k['status']}"
                )
        else:
            out.append("_Tous les KPI suivis sont dans leur cible._")
        sig = ", ".join(f"{_md(x['term'])} ({x['axis'] or '—'}, {x['count']})" for x in h["signals"]) or "aucun"
        out += ["", f"**Signaux faibles de la semaine** : {sig}", ""]
        out.append("**Actions d'amélioration proposées** :")
        out += [f"- {_md(a['action'])}" for a in h["actions"]] or ["- _Aucune._"]
    out += ["", "## Prochains salons", ""]
    for e in c["events"]:
        out.append(
            f"- **{_md(e['name'])}** – {_fmt_date(e['start'])} au {_fmt_date(e['end'])}, {_md(e['location'])}"
            + ("" if e["confirmed"] else " (dates à confirmer)")
        )
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------- HTML e-mail (Outlook-safe)

FONT = "font-family:Segoe UI,Arial,Helvetica,sans-serif;"


def _e(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


def _badge(level: str) -> str:
    fg, bg = LEVEL_COLORS.get(level, LEVEL_COLORS["Info"])
    return (
        f'<span style="{FONT}font-size:11px;font-weight:bold;color:{fg};background-color:{bg};'
        f'padding:1px 6px;border-radius:3px;">{_e(level)}</span>'
    )


def _item_html(a: dict[str, Any], detailed: bool) -> str:
    url = _e(safe_url(a["url"]))
    kev = (
        (
            ' <span style="' + FONT + "font-size:11px;font-weight:bold;color:#ffffff;background-color:#7a0f5c;"
            'padding:1px 6px;border-radius:3px;">KEV</span>'
        )
        if a.get("kev")
        else ""
    )
    rows = [
        f'<tr><td style="padding:10px 0 2px 0;{FONT}font-size:15px;line-height:20px;">'
        f'<a href="{url}" style="color:#1b4fd6;text-decoration:underline;font-weight:bold;">{_e(a["title"])}</a></td></tr>',
        f'<tr><td style="padding:0 0 4px 0;{FONT}font-size:12px;color:#555555;">{_badge(a["level"])}{kev} '
        f"&nbsp;{_e(a['source'])} – {_fmt_date(a['published'])}</td></tr>",
    ]
    if detailed and a.get("summary"):
        rows.append(
            f'<tr><td style="padding:0 0 4px 0;{FONT}font-size:14px;line-height:20px;color:#222222;">{_e(a["summary"])}</td></tr>'
        )
    if detailed and a.get("why"):
        rows.append(
            f'<tr><td style="padding:0 0 6px 0;{FONT}font-size:13px;line-height:19px;color:#333333;">'
            f"<b>Pourquoi c'est important :</b> {_e(a['why'])}</td></tr>"
        )
    return "".join(rows)


def _section(title: str, inner: str) -> str:
    return (
        f'<tr><td style="padding:22px 24px 4px 24px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td style="{FONT}font-size:18px;font-weight:bold;color:#14171f;border-bottom:2px solid #1b4fd6;padding-bottom:4px;">{_e(title)}</td></tr>'
        f"{inner}</table></td></tr>"
    )


def _para(text: str, italic: bool = False) -> str:
    style = "font-style:italic;" if italic else ""
    return f'<tr><td style="padding:8px 0;{FONT}font-size:13px;color:#555555;{style}">{text}</td></tr>'


def render_html(c: dict[str, Any], site_url: str, unsubscribe: str) -> str:
    parts = []
    parts.append(
        _section(
            "Les faits marquants", "".join(_item_html(a, True) for a in c["top"]) or _para("Aucun article cette semaine.", True)
        )
    )
    for theme, block in c["blocks"].items():
        inner = _para(_e(block["note"]), True) if block["note"] else ""
        inner += "".join(_item_html(a, block["detailed"]) for a in block["items"]) or _para("Rien de notable.", True)
        parts.append(_section(f"{theme} – {block['label']}", inner))
    kev_rows = "".join(
        f'<tr><td style="padding:4px 0;{FONT}font-size:14px;color:#222222;"><b>{_e(cve)}</b> – {_e(i["product"])}'
        f"{' – <b>utilisée par des rançongiciels</b>' if i['ransomware'] else ''}</td></tr>"
        for cve, i in c["kev"].items()
    )
    parts.append(
        _section(
            "CVE exploitées activement (CISA KEV)", kev_rows or _para("Aucune CVE du catalogue KEV citée cette semaine.", True)
        )
    )
    act_rows = "".join(
        f'<tr><td style="padding:4px 0;{FONT}font-size:14px;line-height:20px;color:#222222;">• '
        f"{('<b>[' + _e(a['type']) + ']</b> ') if a['type'] else ''}{_e(a['text'])} "
        f'<span style="color:#666666;">({_e(a["article"]["source"])})</span></td></tr>'
        for a in c["actions"]
    )
    parts.append(_section("Actions recommandées", act_rows or _para("Aucune action spécifique cette semaine.", True)))
    ev_rows = "".join(
        f'<tr><td style="padding:4px 0;{FONT}font-size:14px;color:#222222;"><a href="{_e(e["url"])}" style="color:#1b4fd6;">{_e(e["name"])}</a>'
        f" – {_fmt_date(e['start'])} au {_fmt_date(e['end'])}, {_e(e['location'])}{'' if e['confirmed'] else ' (à confirmer)'}</td></tr>"
        for e in c["events"]
    )
    h = c.get("health")
    if h:
        rows = "".join(
            f'<tr><td style="padding:3px 0;{FONT}font-size:14px;color:#222222;">• {_e(k["nom"])} : <b>{_e(_fmt_num(k["value"]))} {_e(k["unite"])}</b>'
            f" (cible {'≤' if k['sens'] == 'baisse' else '≥'} {_e(_fmt_num(k['cible']))}) – {_e(k['status'])}</td></tr>"
            for k in h["off_target"]
        ) or _para("Tous les KPI suivis sont dans leur cible.", True)
        sig = ", ".join(f"{_e(x['term'])} ({_e(x['axis'] or '—')}, {x['count']})" for x in h["signals"]) or "aucun"
        rows += (
            f'<tr><td style="padding:8px 0 3px 0;{FONT}font-size:14px;color:#222222;"><b>Signaux faibles :</b> {sig}</td></tr>'
        )
        rows += "".join(
            f'<tr><td style="padding:3px 0;{FONT}font-size:14px;color:#222222;">→ {_e(a["action"])}</td></tr>'
            for a in h["actions"]
        )
        parts.append(_section("Santé de la veille", rows))
    parts.append(_section("Prochains salons", ev_rows or _para("Aucun salon programmé.", True)))

    return f"""<!DOCTYPE html>
<html lang="fr" xmlns="http://www.w3.org/1999/xhtml"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light only">
<title>{_e(subject(c))}</title></head>
<body style="margin:0;padding:0;background-color:#eef0f4;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#eef0f4" style="background-color:#eef0f4;"><tr><td align="center" style="padding:16px 8px;">
<!--[if mso]><table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#ffffff" style="max-width:600px;background-color:#ffffff;">
<tr><td bgcolor="#14213d" style="background-color:#14213d;padding:20px 24px;{FONT}">
<div style="font-size:22px;font-weight:bold;color:#ffffff;">Veille cyber – semaine {c["week"]}</div>
<div style="font-size:13px;color:#d6dcea;padding-top:4px;">{c["total_week"]} articles analysés sur 7 jours · Cloud · DFIR · IA · Entreprises</div></td></tr>
{"".join(parts)}
<tr><td style="padding:22px 24px;" align="center"><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
<td bgcolor="#1b4fd6" style="background-color:#1b4fd6;padding:10px 20px;{FONT}">
<a href="{_e(site_url)}" style="color:#ffffff;font-weight:bold;text-decoration:none;font-size:14px;">Ouvrir le site de veille</a></td></tr></table></td></tr>
<tr><td style="padding:12px 24px 22px 24px;{FONT}font-size:11px;line-height:16px;color:#666666;border-top:1px solid #dddddd;">
Résumés générés par IA à partir des titres et extraits publics : vérifiez la source avant d'agir.<br>{_e(unsubscribe)}</td></tr>
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr></table></body></html>"""


def render_text(markdown: str, site_url: str, unsubscribe: str) -> str:
    return f"{markdown}\n\nSite de veille : {site_url}\n\n{unsubscribe}\n"


# --------------------------------------------------------------------------- sending


def recipients(cfg: Config, test_mode: bool) -> list[str]:
    """Collect addresses from env vars of enabled groups. Test mode => « interne » only."""
    out: list[str] = []
    for name, group in cfg.settings["newsletter"]["recipients"].items():
        if test_mode and name != "interne":
            continue
        if not group.get("enabled", False):
            log.info("Groupe « %s » désactivé", name)
            continue
        raw = os.environ.get(group["env"], "")
        addrs = [a.strip() for a in raw.replace(";", ",").split(",") if "@" in a]
        if not addrs:
            log.warning("Groupe « %s » actif mais la variable %s est vide", name, group["env"])
        out += [a for a in addrs if a.lower() not in {x.lower() for x in out}]
    return out


def send(html_body: str, text_body: str, subj: str, to: list[str], cfg_smtp: dict[str, Any]) -> int:
    """One message per recipient: no recipient ever sees the others' addresses."""
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM", "") or user
    host = os.environ.get("SMTP_HOST") or cfg_smtp["host"]
    port = int(os.environ.get("SMTP_PORT") or cfg_smtp["port"])
    if not (user and password and sender):
        raise RuntimeError("SMTP_USER, SMTP_PASSWORD ou SMTP_FROM manquant : envoi impossible")
    ctx = ssl.create_default_context()
    sent = 0
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        if cfg_smtp.get("starttls", True):
            smtp.starttls(context=ctx)
        smtp.login(user, password)
        for addr in to:
            msg = EmailMessage()
            msg["Subject"] = subj
            msg["From"] = sender
            msg["To"] = addr
            msg["Date"] = formatdate(localtime=True)
            msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
            msg["List-Unsubscribe"] = f"<mailto:{sender}?subject=DESINSCRIPTION>"
            msg.set_content(text_body)
            msg.add_alternative(html_body, subtype="html")
            smtp.send_message(msg)
            sent += 1
    return sent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthèse hebdomadaire de la veille cyber")
    parser.add_argument("--send", action="store_true", help="envoyer l'e-mail (sinon : archive + aperçu seulement)")
    parser.add_argument("--test", action="store_true", help="mode test : groupe « interne » uniquement")
    parser.add_argument("--respect-schedule", action="store_true", help="n'agir qu'à l'heure locale configurée (cron)")
    parser.add_argument("--force", action="store_true", help="renvoyer même si la semaine a déjà été envoyée")
    args = parser.parse_args(argv)
    setup_logging()
    cfg = load_config()
    nl = cfg.settings["newsletter"]
    now = utcnow()
    local = now.astimezone(ZoneInfo(nl["timezone"]))
    if args.respect_schedule and local.hour != nl["send_hour_local"]:
        log.info(
            "Il est %s à Paris : ce déclenchement n'est pas celui de %02d:00, rien à faire.",
            local.strftime("%H:%M"),
            nl["send_hour_local"],
        )
        return 0

    articles = read_json(cfg.data_dir / ARTICLES_FILE, {}).get("articles", [])
    content = select_content(articles, cfg, now)
    md = render_markdown(content, cfg.site_url)
    archive = cfg.data_dir / "weekly" / f"{content['label']}.md"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text(md, "utf-8")
    log.info("Archive écrite : %s", archive.relative_to(ROOT) if archive.is_relative_to(ROOT) else archive)

    html_body = render_html(content, cfg.site_url, nl["unsubscribe_text"])
    preview = ROOT / "build" / "newsletter_preview.html"
    preview.parent.mkdir(exist_ok=True)
    preview.write_text(html_body, "utf-8")
    log.info("Aperçu HTML : %s", preview)

    if not args.send:
        log.info("Envoi non demandé (--send absent).")
        return 0
    sent_path = cfg.data_dir / "weekly" / "sent.json"
    sent_log = read_json(sent_path, {})
    if not args.test and not args.force and content["label"] in sent_log:
        log.info(
            "Synthèse %s déjà envoyée le %s : pas de doublon (--force pour renvoyer).",
            content["label"],
            sent_log[content["label"]],
        )
        return 0
    to = recipients(cfg, test_mode=args.test)
    if not to:
        log.warning("Aucun destinataire configuré : rien n'est envoyé (l'archive Markdown est bien créée).")
        return 0
    subj = subject(content) + (" [TEST]" if args.test else "")
    try:
        n = send(html_body, render_text(md, cfg.site_url, nl["unsubscribe_text"]), subj, to, nl["smtp"])
    except Exception as exc:
        log.error("Échec de l'envoi : %s", exc)
        return 1
    if not args.test:
        sent_log[content["label"]] = iso(utcnow())
        write_json(sent_path, sent_log)
    log.info("Synthèse envoyée à %d destinataire(s)%s", n, " (mode test)" if args.test else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
