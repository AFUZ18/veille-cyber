# Fiches KPI de la veille (format SMART)

> Fichier généré par `python scripts/kpi_doc.py` à partir de `config/kpi.yaml` : ne pas modifier à la main.
> **Cibles, seuils et poids = valeurs initiales à valider** après 4 à 8 semaines d'observation.

## Principes communs

- **Calcul** : à chaque exécution du pipeline (toutes les 6 heures), par `src/kpi.py`.
- **Historique** : un instantané par exécution dans `data/kpi_history.jsonl`, conservé sans limite ; export CSV : `python scripts/export_kpi.py` ou bouton « Exporter les KPI (CSV) » de la page KPI.
- **Statut** : vert = cible atteinte ; orange = entre la cible et le seuil d'alerte ; rouge = seuil franchi ; « non disponible » = données insuffisantes (n'interrompt jamais le pipeline).
- **Amélioration continue (SLA)** : quand un KPI reste orange ou rouge pendant le nombre de périodes consécutives indiqué, une action est ajoutée à `data/improvement_actions.md` et une issue GitHub « Action d'amélioration » unique est ouverte ; elle est fermée automatiquement quand le KPI revient au vert.
- **Source Quality Score (SQS)** = 30% pertinence + 25% crédibilité + 25% nouveauté + 20% efficacité (`settings.yaml > quality`).
- **Crédibilité** = 30% AE (expertise des auteurs) + 40% IR (réputation de l'institution) + 30% PR (rigueur éditoriale) ; notes dans `config/sources_quality.yaml`.
- **Nouveauté** : part des informations qu'une source publie en premier. **Efficacité** : rapidité (délai médian de réception, TTRI) et part d'articles utiles. **Source Authority Index** : crédibilité, taux de reprise par d'autres organisations et nouveauté.
- **Mode apprentissage** : pendant les 4 premières semaines, les objectifs sont provisoires, aucune issue n'est ouverte et le bloc santé de l'e-mail reste informatif ; ensuite `data/kpi_calibration.md` propose des objectifs recalés (à valider).
- **« Pas encore de données »** : un indicateur qui exige une saisie humaine ou un historique minimal (champ `disponibilite`) n'est jamais orange ni rouge et ne déclenche aucune action tant qu'il n'est pas mesurable.
- **Alerte unique** : une seule issue « Revue de la veille » liste les cartes en « Problème » (remplace les issues par action du chantier 2).

## Les 9 cartes de la vue « Santé de la veille »

| # | Question | Indicateurs utilisés | Pourquoi | Que faire | Estimation |
|---|---|---|---|---|---|
| 1 | Mes sources fonctionnent-elles ? | B6_disponibilite_flux, B7_flux_en_erreur | Une source en panne, ce sont des alertes que vous ne recevez pas. | Corriger l'adresse des sources en panne ou les désactiver dans la configuration. | non |
| 2 | Reçoit-on les informations assez vite ? | B5_delai_reception | Une alerte reçue tard laisse moins de temps pour réagir. | Vérifier que la mise à jour automatique tourne bien toutes les 6 heures. | non |
| 3 | Les articles sont-ils utiles ? | A1_pertinence_axe | Moins d'articles inutiles, c'est moins de temps perdu. | Retirer les sources ou mots-clés qui apportent surtout du bruit. | non |
| 4 | Chaque sujet est-il bien couvert ? | A2_couverture_axe | Un sujet peu couvert, ce sont des risques que l'on ne voit pas. | Ajouter une source spécialisée sur le sujet le moins couvert. | non |
| 5 | Les infos importantes sont-elles confirmées ? | B3_taux_recoupement | Une alerte confirmée par plusieurs sources est plus sûre. | Recouper les alertes isolées avec l'avis officiel (CERT-FR, éditeur). | non |
| 6 | Les sources sont-elles fiables ? | B1_qualite_moyenne, B2_qualite_source | Des sources fiables évitent de relayer de fausses alertes. | Remplacer les sources les moins bien notées si elles restent faibles. | oui |
| 7 | La veille est-elle variée ? | F1_part_max_source, F5_part_sources_francaises, E1_repartition_langues, F2_concentration_hhi, F4_repartition_geographique | Une veille peu variée voit moins bien les sujets français et européens. | Ajouter des sources françaises et européennes. | non |
| 8 | La veille sert-elle à quelque chose ? | D1_utilisations, D2_signaux_transformes, D3_taux_transformation, A3_temps_hors_sujet | Une veille qui ne sert pas doit être réorientée. | Cliquez sur « Signaler un usage » (dans les détails d'un article) dès qu'une information vous sert. | non |
| 9 | Repère-t-on des sujets émergents ? | C1_signaux_faibles | Repérer tôt un sujet laisse le temps de s'y préparer. | Lire les sujets émergents et noter une hypothèse pour chacun. | non |

## Référentiel complet des 22 indicateurs

## A. Pertinence par rapport aux objectifs

### A1_pertinence_axe · Part d'articles pertinents par axe (par axe H1 à H4)

| Champ | Valeur |
|---|---|
| **Version simple** | Les articles sont-ils utiles ? — « {dixiemes} articles sur 10 correspondent à vos sujets » (essentiel) |
| Pourquoi (simple) | Moins d'articles inutiles, c'est moins de temps perdu. |
| Que faire (simple) | Retirer les sources ou mots-clés qui apportent surtout du bruit. |
| Disponibilité | toujours mesurable ; sinon : « Pas encore assez d'articles cette semaine. » |
| Objectif (spécifique) | Mesurer la part des articles collectés qui servent réellement les objectifs de chaque axe. |
| Définition (mesurable) | Pourcentage d'articles dont la pertinence >= seuil_pertinence, sur 7 jours. |
| Atteignable | Ajustement des sources et des mots-clés. |
| Réaliste | 40 % : une partie de l'actualité générale reste du bruit utile au contexte. |
| Temporel | Calcul à chaque exécution, revue chaque semaine. |
| Formule | articles de l'axe avec pertinence >= seuil / articles de l'axe (7 jours) × 100 |
| Unité / sens | % · plus haut = mieux |
| Source des données | data/articles.json (pertinence calculée par src/score.py) ; data/usage.yaml et issues GitHub pour A3 |
| Fréquence | calcul à chaque exécution ; période d'évaluation : semaine |
| Cible | ≥ 40 % |
| Seuil d'alerte | < 20 % |
| Responsable | Analyste veille |
| Action corrective (SLA) | Axe <élément concerné> : revoir les mots-clés du thème et les sources peu pertinentes de l'axe. — après 2 période(s) consécutive(s) hors cible |

### A2_couverture_axe · Couverture hebdomadaire par axe (par axe H1 à H4)

| Champ | Valeur |
|---|---|
| **Version simple** | Chaque sujet est-il bien couvert ? — « Le sujet le moins couvert atteint {valeur} % de son objectif » (essentiel) |
| Pourquoi (simple) | Un sujet peu couvert, ce sont des risques que l'on ne voit pas. |
| Que faire (simple) | Ajouter une source spécialisée sur le sujet le moins couvert. |
| Disponibilité | toujours mesurable ; sinon : « Pas encore assez d'articles cette semaine. » |
| Objectif (spécifique) | Vérifier que chaque axe reçoit assez d'articles pertinents chaque semaine. |
| Définition (mesurable) | Articles pertinents de la semaine / cible hebdomadaire de l'axe (themes.yaml) × 100. |
| Atteignable | Cibles hebdomadaires réalistes par axe (themes.yaml > objectifs). |
| Réaliste | Fondé sur le volume observé des sources actuelles. |
| Temporel | Chaque semaine. |
| Formule | articles pertinents de l'axe sur 7 jours / objectifs.cible_hebdo × 100 |
| Unité / sens | % · plus haut = mieux |
| Source des données | data/articles.json (pertinence calculée par src/score.py) ; data/usage.yaml et issues GitHub pour A3 |
| Fréquence | calcul à chaque exécution ; période d'évaluation : semaine |
| Cible | ≥ 100 % |
| Seuil d'alerte | < 50 % |
| Responsable | Responsable veille |
| Action corrective (SLA) | Axe <élément concerné> sous-couvert : ajouter au moins une source spécialisée sur cet axe (feeds.yaml). — après 2 période(s) consécutive(s) hors cible |

### A3_temps_hors_sujet · Part du temps passé sur des articles hors sujet

| Champ | Valeur |
|---|---|
| **Version simple** | Perd-on du temps sur des articles hors sujet ? — « {valeur} % des articles consultés étaient hors sujet » (avance) |
| Pourquoi (simple) | Indique si le tri automatique laisse passer trop de bruit. |
| Que faire (simple) | Renforcer les exclusions de mots-clés. |
| Disponibilité | saisie humaine requise ; sinon : « Aucun usage déclaré pour l'instant : utilisez le lien « Signaler un usage ». » |
| Objectif (spécifique) | Limiter le temps perdu sur des articles finalement écartés. |
| Définition (mesurable) | Usages « article écarté (hors sujet) » / tous les usages déclarés (30 jours). |
| Atteignable | Dépend de la saisie du journal d'usage. |
| Réaliste | 10 % maximum. |
| Temporel | Mensuel. |
| Formule | usages de type « écarté » / usages déclarés × 100 (30 jours) |
| Unité / sens | % · plus bas = mieux |
| Source des données | data/articles.json (pertinence calculée par src/score.py) ; data/usage.yaml et issues GitHub pour A3 |
| Fréquence | calcul à chaque exécution ; période d'évaluation : mois |
| Cible | ≤ 10 % |
| Seuil d'alerte | > 25 % |
| Responsable | Analyste veille |
| Action corrective (SLA) | Trop d'articles hors sujet consultés : renforcer les exclusions (themes.yaml > exclusions). — après 1 période(s) consécutive(s) hors cible |

## B. Qualité des sources

### B1_qualite_moyenne · Score de qualité moyen des sources

| Champ | Valeur |
|---|---|
| **Version simple** | Les sources sont-elles fiables ? — « Note moyenne des sources : {valeur} sur 100 » (essentiel) |
| Pourquoi (simple) | Des sources fiables évitent de relayer de fausses alertes. |
| Que faire (simple) | Remplacer les sources les moins bien notées. |
| Disponibilité | toujours mesurable ; sinon : « Aucune source n'a publié sur la période. » |
| Objectif (spécifique) | Suivre la qualité globale du panel de sources. |
| Définition (mesurable) | Moyenne du Source Quality Score des sources actives ayant publié sur 30 jours. |
| Atteignable | Remplacement progressif des sources faibles. |
| Réaliste | 60 / 100. |
| Temporel | Chaque semaine. |
| Formule | moyenne(SQS) ; SQS = 30 % pertinence + 25 % crédibilité + 25 % nouveauté + 20 % efficacité |
| Unité / sens | /100 · plus haut = mieux |
| Source des données | data/articles.json, data/feeds_status.json, config/sources_quality.yaml |
| Fréquence | calcul à chaque exécution ; période d'évaluation : semaine |
| Cible | ≥ 60 /100 |
| Seuil d'alerte | < 50 /100 |
| Responsable | Responsable veille |
| Action corrective (SLA) | Qualité moyenne des sources insuffisante : revoir le panel de sources. — après 4 période(s) consécutive(s) hors cible |

### B2_qualite_source · Score de qualité par source (par source)

| Champ | Valeur |
|---|---|
| **Version simple** | Quelles sources sont les plus faibles ? — « La source la plus faible a {valeur} sur 100 » (avance) |
| Pourquoi (simple) | Une source faible durablement doit être remplacée. |
| Que faire (simple) | Remplacer ou désactiver les sources sous 50 depuis 4 semaines. |
| Disponibilité | toujours mesurable ; sinon : « Aucune source n'a publié sur la période. » |
| Objectif (spécifique) | Repérer les sources qui n'apportent pas assez de valeur. |
| Définition (mesurable) | Source Quality Score de chaque source (30 jours glissants). |
| Atteignable | Remplacer ou désactiver une source durablement faible. |
| Réaliste | Seuil 50 / 100. |
| Temporel | Décision après 4 semaines consécutives sous le seuil. |
| Formule | SQS = 30 % pertinence + 25 % crédibilité + 25 % nouveauté + 20 % efficacité |
| Unité / sens | /100 · plus haut = mieux |
| Source des données | data/articles.json, data/feeds_status.json, config/sources_quality.yaml |
| Fréquence | calcul à chaque exécution ; période d'évaluation : semaine |
| Cible | ≥ 60 /100 |
| Seuil d'alerte | < 50 /100 |
| Responsable | Responsable veille |
| Action corrective (SLA) | Source « <élément concerné> » sous le score de qualité cible depuis 4 semaines : la remplacer ou la désactiver (feeds.yaml). — après 4 période(s) consécutive(s) hors cible |

### B3_taux_recoupement · Taux de recoupement des informations importantes

| Champ | Valeur |
|---|---|
| **Version simple** | Les infos importantes sont-elles confirmées ? — « {dixiemes} alertes importantes sur 10 sont confirmées par au moins 2 sources » (essentiel) |
| Pourquoi (simple) | Une alerte confirmée par plusieurs sources est plus sûre. |
| Que faire (simple) | Ajouter une source officielle ou de presse indépendante. |
| Disponibilité | toujours mesurable ; sinon : « Aucune alerte importante cette semaine. » |
| Objectif (spécifique) | S'assurer que les informations Élevé/Critique sont confirmées. |
| Définition (mesurable) | Part des articles de criticité Élevé ou Critique confirmés par >= 2 sources indépendantes (7 jours). |
| Atteignable | Diversifier les sources H4. |
| Réaliste | 50 %. |
| Temporel | Chaque semaine. |
| Formule | articles Élevé/Critique recoupés par >= 2 organisations / articles Élevé/Critique × 100 |
| Unité / sens | % · plus haut = mieux |
| Source des données | data/articles.json, data/feeds_status.json, config/sources_quality.yaml |
| Fréquence | calcul à chaque exécution ; période d'évaluation : semaine |
| Cible | ≥ 50 % |
| Seuil d'alerte | < 25 % |
| Responsable | Analyste veille |
| Action corrective (SLA) | Trop d'informations importantes non recoupées : ajouter une source officielle ou de presse indépendante. — après 3 période(s) consécutive(s) hors cible |

### B4_sources_non_referencees · Articles de sources non référencées

| Champ | Valeur |
|---|---|
| **Version simple** | Des articles viennent-ils de sources inconnues ? — « {valeur} article(s) de source inconnue » (avance) |
| Pourquoi (simple) | Une source inconnue peut diffuser de fausses informations. |
| Que faire (simple) | Vérifier ces sites et les ajouter à la liste ou les écarter. |
| Disponibilité | toujours mesurable ; sinon : « Pas encore assez d'articles cette semaine. » |
| Objectif (spécifique) | Détecter les liens qui pointent hors des domaines approuvés. |
| Définition (mesurable) | Nombre d'articles dont le domaine n'est pas dans sources_quality.yaml (7 jours). |
| Atteignable | Compléter la liste des domaines approuvés. |
| Réaliste | 0 attendu. |
| Temporel | Chaque semaine. |
| Formule | nombre d'articles dont le domaine n'est couvert par aucune source approuvée |
| Unité / sens | articles · plus bas = mieux |
| Source des données | data/articles.json, data/feeds_status.json, config/sources_quality.yaml |
| Fréquence | calcul à chaque exécution ; période d'évaluation : semaine |
| Cible | ≤ 0 articles |
| Seuil d'alerte | > 5 articles |
| Responsable | Analyste veille |
| Action corrective (SLA) | Des articles pointent vers des domaines non approuvés : vérifier ces domaines et compléter sources_quality.yaml. — après 2 période(s) consécutive(s) hors cible |

### B5_delai_reception · Délai de réception de l'information (TTRI)

| Champ | Valeur |
|---|---|
| **Version simple** | Reçoit-on les informations assez vite ? — « La moitié des articles arrive en moins de {valeur} heures » (essentiel) |
| Pourquoi (simple) | Une alerte reçue tard laisse moins de temps pour réagir. |
| Que faire (simple) | Vérifier que la mise à jour automatique tourne bien toutes les 6 heures. |
| Disponibilité | 1 jour(s) d'historique minimum ; sinon : « Il faut au moins une journée de collecte. » |
| Objectif (spécifique) | Recevoir l'information rapidement après sa publication. |
| Définition (mesurable) | Médiane (en heures) de collecte - publication, sur 7 jours. |
| Atteignable | Collecte toutes les 6 heures. |
| Réaliste | 6 heures. |
| Temporel | Chaque semaine. |
| Formule | médiane(date de collecte - date de publication), en heures |
| Unité / sens | h · plus bas = mieux |
| Source des données | data/articles.json, data/feeds_status.json, config/sources_quality.yaml |
| Fréquence | calcul à chaque exécution ; période d'évaluation : semaine |
| Cible | ≤ 6 h |
| Seuil d'alerte | > 24 h |
| Responsable | Administrateur |
| Action corrective (SLA) | Délai de réception trop long : vérifier la fréquence d'exécution du workflow et les flux lents. — après 2 période(s) consécutive(s) hors cible |

### B6_disponibilite_flux · Disponibilité des flux

| Champ | Valeur |
|---|---|
| **Version simple** | Mes sources fonctionnent-elles ? — « {ok} sources sur {total} répondent » (essentiel) |
| Pourquoi (simple) | Une source en panne, ce sont des alertes que vous ne recevez pas. |
| Que faire (simple) | Corriger l'adresse des sources en panne ou les désactiver. |
| Disponibilité | toujours mesurable ; sinon : « Aucune collecte enregistrée. » |
| Objectif (spécifique) | S'assurer que les sources répondent. |
| Définition (mesurable) | Part des flux actifs collectés sans erreur lors de la dernière exécution. |
| Atteignable | Correction ou remplacement des flux en panne. |
| Réaliste | 90 %. |
| Temporel | À chaque exécution. |
| Formule | flux OK / flux actifs × 100 |
| Unité / sens | % · plus haut = mieux |
| Source des données | data/articles.json, data/feeds_status.json, config/sources_quality.yaml |
| Fréquence | calcul à chaque exécution ; période d'évaluation : jour |
| Cible | ≥ 90 % |
| Seuil d'alerte | < 75 % |
| Responsable | Administrateur |
| Action corrective (SLA) | Trop de flux en panne : lancer scripts/check_feeds.py et corriger feeds.yaml. — après 3 période(s) consécutive(s) hors cible |

### B7_flux_en_erreur · Disponibilité par flux (par source)

| Champ | Valeur |
|---|---|
| **Version simple** | Quelles sources sont en panne ? — « {valeur} % des sources répondent » (avance) |
| Pourquoi (simple) | Permet de savoir précisément quelle source corriger. |
| Que faire (simple) | Corriger ou désactiver chaque source en panne. |
| Disponibilité | toujours mesurable ; sinon : « Aucune collecte enregistrée. » |
| Objectif (spécifique) | Repérer chaque flux durablement en panne. |
| Définition (mesurable) | 100 si le flux répond, 0 sinon, à chaque exécution. |
| Atteignable | Corriger l'URL ou désactiver le flux. |
| Réaliste | Tolérance de 2 jours (8 exécutions). |
| Temporel | À chaque exécution. |
| Formule | 100 si collecte OK, 0 sinon |
| Unité / sens | % · plus haut = mieux |
| Source des données | data/articles.json, data/feeds_status.json, config/sources_quality.yaml |
| Fréquence | calcul à chaque exécution ; période d'évaluation : execution |
| Cible | ≥ 100 % |
| Seuil d'alerte | < 50 % |
| Responsable | Administrateur |
| Action corrective (SLA) | Le flux « <élément concerné> » est en erreur depuis 2 jours : corriger son URL, le remplacer ou le désactiver (feeds.yaml). — après 8 période(s) consécutive(s) hors cible |

## C. Intérêt : signaux faibles

### C1_signaux_faibles · Signaux faibles détectés (par axe H1 à H4)

| Champ | Valeur |
|---|---|
| **Version simple** | Repère-t-on des sujets émergents ? — « {valeur} sujet(s) émergent(s) repéré(s) cette semaine » (essentiel) |
| Pourquoi (simple) | Repérer tôt un sujet laisse le temps de s'y préparer. |
| Que faire (simple) | Lire les sujets émergents et noter une hypothèse pour chacun. |
| Disponibilité | 7 jour(s) d'historique minimum ; sinon : « La détection compare la semaine aux précédentes : il faut d'abord une semaine d'historique. » |
| Objectif (spécifique) | Repérer tôt les sujets émergents. |
| Définition (mesurable) | Nombre de termes en forte hausse mais encore rares (semaine vs 4 semaines). |
| Atteignable | Détection automatique, glossaire FR/EN. |
| Réaliste | Indicateur d'observation (pas de cible imposée). |
| Temporel | Chaque semaine. |
| Formule | nombre de termes respectant les seuils de signaux_faibles |
| Unité / sens | signaux · indicateur d'observation |
| Source des données | data/articles.json + config/glossary.yaml (détection dans src/signals.py) |
| Fréquence | calcul à chaque exécution ; période d'évaluation : semaine |
| Cible | — |
| Seuil d'alerte | — |
| Responsable | Analyste veille |
| Action corrective (SLA) | — |

## D. Utilité

### D1_utilisations · Utilisations de l'information collectée

| Champ | Valeur |
|---|---|
| **Version simple** | La veille sert-elle à quelque chose ? — « {valeur} utilisation(s) déclarée(s) en 30 jours » (essentiel) |
| Pourquoi (simple) | Une veille qui ne sert pas doit être réorientée. |
| Que faire (simple) | Déclarer chaque usage avec le lien « Signaler un usage ». |
| Disponibilité | saisie humaine requise ; sinon : « Aucun usage déclaré pour l'instant : utilisez le lien « Signaler un usage » sous un article. » |
| Objectif (spécifique) | Mesurer l'usage réel de la veille (alertes, correctifs, notes, sensibilisation). |
| Définition (mesurable) | Nombre d'usages déclarés (issues « Information utilisée » + data/usage.yaml) sur 30 jours. |
| Atteignable | Saisie d'un usage en 1 minute depuis chaque carte. |
| Réaliste | 4 par mois. |
| Temporel | Mensuel. |
| Formule | nombre d'usages déclarés (hors « écarté ») sur 30 jours |
| Unité / sens | usages · plus haut = mieux |
| Source des données | data/usage.yaml + issues GitHub « usage » / « signal-transforme » ; historique des signaux |
| Fréquence | calcul à chaque exécution ; période d'évaluation : mois |
| Cible | ≥ 4 usages |
| Seuil d'alerte | < 1 usages |
| Responsable | Responsable veille |
| Action corrective (SLA) | La veille est peu utilisée : présenter la synthèse aux équipes et rappeler le lien « Signaler un usage ». — après 1 période(s) consécutive(s) hors cible |

### D2_signaux_transformes · Signaux faibles transformés en action ou hypothèse

| Champ | Valeur |
|---|---|
| **Version simple** | Les sujets émergents mènent-ils à des actions ? — « {valeur} sujet(s) émergent(s) transformé(s) en action » (avance) |
| Pourquoi (simple) | Montre si la veille aide à anticiper. |
| Que faire (simple) | Faire une revue mensuelle des sujets émergents. |
| Disponibilité | saisie humaine requise ; sinon : « Aucune déclaration pour l'instant. » |
| Objectif (spécifique) | Suivre la transformation des signaux faibles en décisions. |
| Définition (mesurable) | Nombre d'issues « Signal faible transformé » sur 30 jours. |
| Atteignable | Revue mensuelle des signaux (data/weak_signals.md). |
| Réaliste | 1 par mois. |
| Temporel | Mensuel. |
| Formule | nombre de signaux transformés (30 jours) |
| Unité / sens | signaux · plus haut = mieux |
| Source des données | data/usage.yaml + issues GitHub « usage » / « signal-transforme » ; historique des signaux |
| Fréquence | calcul à chaque exécution ; période d'évaluation : mois |
| Cible | ≥ 1 signaux |
| Seuil d'alerte | < 0 signaux |
| Responsable | Responsable veille |
| Action corrective (SLA) | Aucun signal faible transformé : organiser la revue mensuelle des signaux (data/weak_signals.md). — après 2 période(s) consécutive(s) hors cible |

### D3_taux_transformation · Taux de transformation des signaux faibles

| Champ | Valeur |
|---|---|
| **Version simple** | Quelle part des sujets émergents est exploitée ? — « {valeur} % des sujets émergents ont mené à une action » (avance) |
| Pourquoi (simple) | Mesure l'intérêt réel des sujets repérés. |
| Que faire (simple) | Prioriser les sujets émergents lors de la revue. |
| Disponibilité | saisie humaine requise, 7 jour(s) d'historique minimum ; sinon : « Il faut des sujets émergents et des déclarations d'usage. » |
| Objectif (spécifique) | Mesurer la part des signaux faibles exploités. |
| Définition (mesurable) | Signaux transformés / signaux détectés sur 30 jours. |
| Atteignable | Revue mensuelle. |
| Réaliste | 20 %. |
| Temporel | Mensuel. |
| Formule | signaux transformés / signaux détectés × 100 (30 jours) |
| Unité / sens | % · plus haut = mieux |
| Source des données | data/usage.yaml + issues GitHub « usage » / « signal-transforme » ; historique des signaux |
| Fréquence | calcul à chaque exécution ; période d'évaluation : mois |
| Cible | ≥ 20 % |
| Seuil d'alerte | < 5 % |
| Responsable | Responsable veille |
| Action corrective (SLA) | Taux de transformation faible : prioriser les signaux faibles en revue et formuler des hypothèses. — après 2 période(s) consécutive(s) hors cible |

## E. Risque de double traduction

### E1_repartition_langues · Répartition des articles par langue source (par langue)

| Champ | Valeur |
|---|---|
| **Version simple** | Dans quelles langues sont les articles ? — « {valeur} % des articles sont en langue étrangère » (essentiel) |
| Pourquoi (simple) | Une veille très anglophone voit moins les sujets français. |
| Que faire (simple) | Ajouter des sources françaises. |
| Disponibilité | toujours mesurable ; sinon : « Pas encore assez d'articles cette semaine. » |
| Objectif (spécifique) | Connaître l'exposition au risque de traduction. |
| Définition (mesurable) | Part de chaque langue d'origine (7 jours). |
| Atteignable | Observation. |
| Réaliste | Indicateur d'observation. |
| Temporel | Chaque semaine. |
| Formule | articles de la langue / total × 100 ; valeur principale = part des articles non francophones |
| Unité / sens | % · indicateur d'observation |
| Source des données | data/articles.json (langue source, étapes de traduction, rattachement par le glossaire) |
| Fréquence | calcul à chaque exécution ; période d'évaluation : semaine |
| Cible | — |
| Seuil d'alerte | — |
| Responsable | Analyste veille |
| Action corrective (SLA) | — |

### E2_traduction_une_etape · Articles traités en une seule étape de traduction

| Champ | Valeur |
|---|---|
| **Version simple** | Les résumés sont-ils faits depuis l'original ? — « {valeur} % des articles résumés directement depuis l'original » (avance) |
| Pourquoi (simple) | Traduire plusieurs fois déforme le sens. |
| Que faire (simple) | Aucune action : garanti par le fonctionnement de l'outil. |
| Disponibilité | toujours mesurable ; sinon : « Pas encore assez d'articles cette semaine. » |
| Objectif (spécifique) | Éviter toute double traduction (résumé d'un texte déjà traduit ou résumé). |
| Définition (mesurable) | Part des articles avec <= 1 étape de traduction, résumé produit depuis l'original. |
| Atteignable | Garanti par conception du pipeline. |
| Réaliste | 100 %. |
| Temporel | À chaque exécution. |
| Formule | articles avec translation_steps <= 1 et summary_from = original / total × 100 |
| Unité / sens | % · plus haut = mieux |
| Source des données | data/articles.json (langue source, étapes de traduction, rattachement par le glossaire) |
| Fréquence | calcul à chaque exécution ; période d'évaluation : semaine |
| Cible | ≥ 100 % |
| Seuil d'alerte | < 95 % |
| Responsable | Administrateur |
| Action corrective (SLA) | Des articles ont subi plusieurs étapes de traduction : vérifier src/summarize.py. — après 1 période(s) consécutive(s) hors cible |

### E3_rattachement_glossaire · Articles rattachés à un axe grâce au glossaire

| Champ | Valeur |
|---|---|
| **Version simple** | Le dictionnaire français-anglais aide-t-il ? — « {valeur} % des articles classés grâce au dictionnaire » (avance) |
| Pourquoi (simple) | Montre les articles qui auraient été mal classés sans lui. |
| Que faire (simple) | Enrichir le dictionnaire (config/glossary.yaml). |
| Disponibilité | toujours mesurable ; sinon : « Pas encore assez d'articles cette semaine. » |
| Objectif (spécifique) | Mesurer les signaux qui auraient été manqués sans le glossaire bilingue. |
| Définition (mesurable) | Part des articles dont au moins un axe provient uniquement du glossaire. |
| Atteignable | Enrichir config/glossary.yaml. |
| Réaliste | Indicateur d'observation. |
| Temporel | Chaque semaine. |
| Formule | articles avec axe ajouté par le glossaire / total × 100 |
| Unité / sens | % · indicateur d'observation |
| Source des données | data/articles.json (langue source, étapes de traduction, rattachement par le glossaire) |
| Fréquence | calcul à chaque exécution ; période d'évaluation : semaine |
| Cible | — |
| Seuil d'alerte | — |
| Responsable | Analyste veille |
| Action corrective (SLA) | — |

## F. Biais et diversité

### F1_part_max_source · Part de la source la plus représentée

| Champ | Valeur |
|---|---|
| **Version simple** | Une source domine-t-elle ? — « La source la plus présente fournit {valeur} % des articles » (essentiel) |
| Pourquoi (simple) | Dépendre d'une seule source donne une vision partielle. |
| Que faire (simple) | Ajouter des sources sur les mêmes sujets. |
| Disponibilité | toujours mesurable ; sinon : « Pas encore assez d'articles cette semaine. » |
| Objectif (spécifique) | Éviter la dépendance à une seule source. |
| Définition (mesurable) | Part de la première source dans le total des articles (7 jours). |
| Atteignable | Plafonner ou compléter les sources. |
| Réaliste | 30 % maximum. |
| Temporel | Chaque semaine. |
| Formule | max(articles d'une source) / total × 100 |
| Unité / sens | % · plus bas = mieux |
| Source des données | data/articles.json + config/sources_quality.yaml (type et pays des sources) |
| Fréquence | calcul à chaque exécution ; période d'évaluation : semaine |
| Cible | ≤ 30 % |
| Seuil d'alerte | > 40 % |
| Responsable | Responsable veille |
| Action corrective (SLA) | Une source pèse trop dans la veille : réduire max_entries_per_feed ou ajouter des sources sur ses sujets. — après 2 période(s) consécutive(s) hors cible |

### F2_concentration_hhi · Indice de concentration des sources (Herfindahl)

| Champ | Valeur |
|---|---|
| **Version simple** | La veille dépend-elle de peu de sources ? — « Indice de concentration : {valeur} » (avance) |
| Pourquoi (simple) | Plus il est haut, plus la veille dépend de quelques sources. |
| Que faire (simple) | Diversifier les sources. |
| Disponibilité | toujours mesurable ; sinon : « Pas encore assez d'articles cette semaine. » |
| Objectif (spécifique) | Mesurer la diversité globale des sources. |
| Définition (mesurable) | Somme des carrés des parts (en %) de chaque source, 0-10 000 (7 jours). |
| Atteignable | Diversification des sources. |
| Réaliste | < 1 000 = diversifié ; > 1 800 = concentré. |
| Temporel | Chaque semaine. |
| Formule | Σ (part de la source en %)² |
| Unité / sens | points · plus bas = mieux |
| Source des données | data/articles.json + config/sources_quality.yaml (type et pays des sources) |
| Fréquence | calcul à chaque exécution ; période d'évaluation : semaine |
| Cible | ≤ 1000 points |
| Seuil d'alerte | > 1800 points |
| Responsable | Responsable veille |
| Action corrective (SLA) | Veille trop concentrée sur quelques sources : diversifier le panel. — après 2 période(s) consécutive(s) hors cible |

### F3_repartition_types · Répartition par type de source (par type de source)

| Champ | Valeur |
|---|---|
| **Version simple** | Quels types de sources lit-on ? — « {valeur} % des articles viennent de blogs d'éditeurs » (avance) |
| Pourquoi (simple) | Un éditeur met en avant les menaces que ses produits traitent. |
| Que faire (simple) | Recouper avec des sources officielles ou de presse. |
| Disponibilité | toujours mesurable ; sinon : « Pas encore assez d'articles cette semaine. » |
| Objectif (spécifique) | Équilibrer sources officielles, éditeurs, presse et communauté. |
| Définition (mesurable) | Part des articles par type de source (7 jours). |
| Atteignable | Observation. |
| Réaliste | Indicateur d'observation. |
| Temporel | Chaque semaine. |
| Formule | articles du type / total × 100 ; valeur principale = part des blogs d'éditeurs (biais commercial) |
| Unité / sens | % · indicateur d'observation |
| Source des données | data/articles.json + config/sources_quality.yaml (type et pays des sources) |
| Fréquence | calcul à chaque exécution ; période d'évaluation : semaine |
| Cible | — |
| Seuil d'alerte | — |
| Responsable | Analyste veille |
| Action corrective (SLA) | — |

### F4_repartition_geographique · Répartition par origine géographique (par pays)

| Champ | Valeur |
|---|---|
| **Version simple** | D'où viennent les sources ? — « {valeur} % des articles viennent du premier pays » (essentiel) |
| Pourquoi (simple) | Une veille dominée par un pays voit moins les autres contextes. |
| Que faire (simple) | Ajouter des sources européennes et françaises. |
| Disponibilité | toujours mesurable ; sinon : « Pas encore assez d'articles cette semaine. » |
| Objectif (spécifique) | Mesurer le biais géographique (sources américaines dominantes). |
| Définition (mesurable) | Part des articles par pays d'origine de la source (7 jours). |
| Atteignable | Observation. |
| Réaliste | Indicateur d'observation. |
| Temporel | Chaque semaine. |
| Formule | articles du pays / total × 100 ; valeur principale = part du premier pays |
| Unité / sens | % · indicateur d'observation |
| Source des données | data/articles.json + config/sources_quality.yaml (type et pays des sources) |
| Fréquence | calcul à chaque exécution ; période d'évaluation : semaine |
| Cible | — |
| Seuil d'alerte | — |
| Responsable | Analyste veille |
| Action corrective (SLA) | — |

### F5_part_sources_francaises · Part des sources françaises

| Champ | Valeur |
|---|---|
| **Version simple** | Lit-on assez de sources françaises ? — « {valeur} % des articles viennent de sources françaises » (essentiel) |
| Pourquoi (simple) | Les règles et alertes françaises (ANSSI) comptent pour vos clients. |
| Que faire (simple) | Ajouter des sources françaises. |
| Disponibilité | toujours mesurable ; sinon : « Pas encore assez d'articles cette semaine. » |
| Objectif (spécifique) | Garder une vision adaptée au contexte français (réglementation, ANSSI). |
| Définition (mesurable) | Part des articles issus de sources françaises (7 jours). |
| Atteignable | Ajout de sources FR. |
| Réaliste | 20 %. |
| Temporel | Chaque semaine. |
| Formule | articles de sources FR / total × 100 |
| Unité / sens | % · plus haut = mieux |
| Source des données | data/articles.json + config/sources_quality.yaml (type et pays des sources) |
| Fréquence | calcul à chaque exécution ; période d'évaluation : semaine |
| Cible | ≥ 20 % |
| Seuil d'alerte | < 10 % |
| Responsable | Responsable veille |
| Action corrective (SLA) | Biais géographique : ajouter des sources françaises (presse, CERT sectoriels, CLUSIF…). — après 3 période(s) consécutive(s) hors cible |
