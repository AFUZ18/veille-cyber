"""Generate docs/KPI.md (one SMART sheet per KPI) from config/kpi.yaml.

python scripts/kpi_doc.py            # rewrite docs/KPI.md
python scripts/kpi_doc.py --check    # exit 1 if docs/KPI.md is out of date (used by the tests)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.common import load_config  # noqa: E402

FAMILIES = {
    "A": "Pertinence par rapport aux objectifs",
    "B": "Qualité des sources",
    "C": "Intérêt : signaux faibles",
    "D": "Utilité",
    "E": "Risque de double traduction",
    "F": "Biais et diversité",
}
DATA_SOURCES = {
    "A": "data/articles.json (pertinence calculée par src/score.py) ; data/usage.yaml et issues GitHub pour A3",
    "B": "data/articles.json, data/feeds_status.json, config/sources_quality.yaml",
    "C": "data/articles.json + config/glossary.yaml (détection dans src/signals.py)",
    "D": "data/usage.yaml + issues GitHub « usage » / « signal-transforme » ; historique des signaux",
    "E": "data/articles.json (langue source, étapes de traduction, rattachement par le glossaire)",
    "F": "data/articles.json + config/sources_quality.yaml (type et pays des sources)",
}
SENS = {"hausse": "plus haut = mieux", "baisse": "plus bas = mieux", "info": "indicateur d'observation"}


def render(cfg) -> str:
    q = cfg.settings.get("quality", {})
    w = q.get("sqs_weights", {})
    c = q.get("credibility_weights", {})
    lines = [
        "# Fiches KPI de la veille (format SMART)",
        "",
        "> Fichier généré par `python scripts/kpi_doc.py` à partir de `config/kpi.yaml` : ne pas modifier à la main.",
        "> **Cibles, seuils et poids = valeurs initiales à valider** après 4 à 8 semaines d'observation.",
        "",
        "## Principes communs",
        "",
        "- **Calcul** : à chaque exécution du pipeline (toutes les 6 heures), par `src/kpi.py`.",
        "- **Historique** : un instantané par exécution dans `data/kpi_history.jsonl`, conservé sans limite ; "
        "export CSV : `python scripts/export_kpi.py` ou bouton « Exporter les KPI (CSV) » de la page KPI.",
        "- **Statut** : vert = cible atteinte ; orange = entre la cible et le seuil d'alerte ; rouge = seuil franchi ; "
        "« non disponible » = données insuffisantes (n'interrompt jamais le pipeline).",
        "- **Amélioration continue (SLA)** : quand un KPI reste orange ou rouge pendant le nombre de périodes consécutives indiqué, "
        "une action est ajoutée à `data/improvement_actions.md` et une issue GitHub « Action d'amélioration » unique est ouverte ; "
        "elle est fermée automatiquement quand le KPI revient au vert.",
        f"- **Source Quality Score (SQS)** = {w.get('pertinence', 0.3):.0%} pertinence + {w.get('credibilite', 0.25):.0%} crédibilité "
        f"+ {w.get('nouveaute', 0.25):.0%} nouveauté + {w.get('efficacite', 0.2):.0%} efficacité (`settings.yaml > quality`).",
        f"- **Crédibilité** = {c.get('ae', 0.3):.0%} AE (expertise des auteurs) + {c.get('ir', 0.4):.0%} IR (réputation de l'institution) "
        f"+ {c.get('pr', 0.3):.0%} PR (rigueur éditoriale) ; notes dans `config/sources_quality.yaml`.",
        "- **Nouveauté** : part des informations qu'une source publie en premier. **Efficacité** : rapidité (délai médian de réception, TTRI) "
        "et part d'articles utiles. **Source Authority Index** : crédibilité, taux de reprise par d'autres organisations et nouveauté.",
        f"- **Mode apprentissage** : pendant les {cfg.kpi.get('mode_apprentissage_semaines', 4)} premières semaines, les objectifs sont provisoires, "
        "aucune issue n'est ouverte et le bloc santé de l'e-mail reste informatif ; ensuite `data/kpi_calibration.md` propose des objectifs recalés (à valider).",
        "- **« Pas encore de données »** : un indicateur qui exige une saisie humaine ou un historique minimal (champ `disponibilite`) n'est jamais orange ni rouge "
        "et ne déclenche aucune action tant qu'il n'est pas mesurable.",
        "- **Alerte unique** : une seule issue « Revue de la veille » liste les cartes en « Problème » (remplace les issues par action du chantier 2).",
        "",
        "## Les 9 cartes de la vue « Santé de la veille »",
        "",
        "| # | Question | Indicateurs utilisés | Pourquoi | Que faire | Estimation |",
        "|---|---|---|---|---|---|",
        *[
            f"| {c['ordre']} | {c['question']} | {', '.join(c['kpis'])} | {c['pourquoi']} | {c['que_faire']} | {'oui' if c.get('estimation') else 'non'} |"
            for c in sorted(cfg.kpi.get("cartes", []), key=lambda c: c["ordre"])
        ],
        "",
        "## Référentiel complet des 22 indicateurs",
        "",
    ]
    by_family: dict[str, list[dict]] = {}
    for k in cfg.kpi.get("kpis", []):
        by_family.setdefault(k["famille"], []).append(k)
    for fam, title in FAMILIES.items():
        lines += [f"## {fam}. {title}", ""]
        for k in by_family.get(fam, []):
            smart = k.get("smart", {})
            unit = k.get("unite") or ""
            target = "—" if k.get("cible") is None else f"{'≤' if k['sens'] == 'baisse' else '≥'} {k['cible']} {unit}".strip()
            alert = (
                "—"
                if k.get("seuil_alerte") is None
                else f"{'>' if k['sens'] == 'baisse' else '<'} {k['seuil_alerte']} {unit}".strip()
            )
            per = {"axe": " (par axe H1 à H4)", "source": " (par source)", "langue": " (par langue)", "type": " (par type de source)",
                   "pays": " (par pays)"}.get(k.get("par") or "", "")  # fmt: skip
            dispo = k.get("disponibilite") or {}
            dispo_txt = (
                ", ".join(
                    x
                    for x in (
                        "saisie humaine requise" if dispo.get("saisie_requise") else "",
                        f"{dispo['historique_min_jours']} jour(s) d'historique minimum"
                        if dispo.get("historique_min_jours")
                        else "",
                    )
                    if x
                )
                or "toujours mesurable"
            )
            lines += [
                f"### {k['id']} · {k['nom']}{per}",
                "",
                "| Champ | Valeur |",
                "|---|---|",
                f"| **Version simple** | {k.get('question', '')} — « {k.get('phrase_resultat', '')} » ({k.get('affichage', '')}) |",
                f"| Pourquoi (simple) | {k.get('pourquoi', '')} |",
                f"| Que faire (simple) | {k.get('que_faire', '')} |",
                f"| Disponibilité | {dispo_txt} ; sinon : « {k.get('message_sans_donnees', '')} » |",
                f"| Objectif (spécifique) | {smart.get('specifique', '')} |",
                f"| Définition (mesurable) | {smart.get('mesurable', '')} |",
                f"| Atteignable | {smart.get('atteignable', '')} |",
                f"| Réaliste | {smart.get('realiste', '')} |",
                f"| Temporel | {smart.get('temporel', '')} |",
                f"| Formule | {k.get('formule', '')} |",
                f"| Unité / sens | {unit or '—'} · {SENS.get(k.get('sens'), '')} |",
                f"| Source des données | {DATA_SOURCES[fam]} |",
                f"| Fréquence | calcul à chaque exécution ; période d'évaluation : {k.get('periode')} |",
                f"| Cible | {target} |",
                f"| Seuil d'alerte | {alert} |",
                f"| Responsable | {k.get('responsable', '')} |",
                f"| Action corrective (SLA) | {(k.get('action') or '—').replace('{sujet}', '<élément concerné>')}"
                + (
                    f" — après {k['periodes_consecutives']} période(s) consécutive(s) hors cible"
                    if k.get("periodes_consecutives")
                    else ""
                )
                + " |",
                "",
            ]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = render(load_config())
    path = ROOT / "docs" / "KPI.md"
    if args.check:
        ok = path.exists() and path.read_text("utf-8") == text
        print("docs/KPI.md à jour" if ok else "docs/KPI.md obsolète : lancez python scripts/kpi_doc.py")
        return 0 if ok else 1
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, "utf-8")
    print(f"{path} écrit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
