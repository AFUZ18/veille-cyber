# Veille cyber automatisée

Site de veille cybersécurité **100 % statique**, mis à jour **toutes les 6 heures** par GitHub Actions et publié sur GitHub Pages, avec :

- une collecte de ~35 flux RSS/Atom classés en 4 axes : **H1 Cloud**, **H2 Forensique & DFIR**, **H3 Sécurité de l'IA** et **H4 Général / Entreprises**, plus un thème transversal « sectoriel » et un onglet **Salons & événements** ;
- une **criticité** de 0 à 100 (Critique / Élevé / Moyen / Info), calculée à partir de CISA KEV, CVSS (NVD), EPSS (FIRST), de mots-clés et des sources officielles, et une **pertinence** pour vos entreprises ;
- des **résumés en français par IA** avec « Pourquoi c'est important » et l'action recommandée. Le site fonctionne aussi sans clé d'IA ;
- une **synthèse hebdomadaire par e-mail**, le lundi à 07:00 (heure de Paris), archivée en Markdown dans `data/weekly/` ;
- votre propre **flux RSS** (`feed.xml`), à suivre dans Feedly ou Outlook, et l'**export CSV / Markdown** des articles filtrés ;
- un **pilotage de la qualité de la veille** : 22 KPI SMART historisés, un onglet **« KPI & qualité »**, un score de qualité par source, la détection des signaux faibles, un badge de fiabilité sur chaque article, un glossaire bilingue contre le risque de double traduction et un plan d'amélioration continue automatique (§ 12).

Il n'y a aucun serveur, aucune base de données et aucun service tiers appelé depuis le navigateur.

```
 Flux RSS ──► collect.py ──► classify.py ──► score.py ──► summarize.py ──► build_site.py ──► GitHub Pages
                  │               │              │  ▲            │  ▲
                  ▼               ▼              │  └ CISA KEV,  │  └ API LLM (LLM_API_KEY)
            data/articles.json (état versionné)  │    NVD, EPSS  ▼
                                                 └──────────► data/summaries_cache.json
 Lundi 07:00 ──► newsletter.py ──► data/weekly/AAAA-Wxx.md + e-mail (SMTP Gmail)

 Après les résumés : quality.py (fiabilité, recoupement, qualité des sources) ──► signals.py (signaux faibles)
                     ──► kpi.py (KPI, historique, SLA) ──► archive.py ──► issues.py (issues « Action d'amélioration »)
```

---

## 1. Démarrage rapide (10 minutes)

1. **Créez un dépôt** GitHub, par exemple `veille-cyber`. Il peut être public, puisque aucun secret n'est versionné.
2. **Poussez ce dossier** (depuis le dossier décompressé) :
   ```bash
   git init -b main
   git add .
   git commit -m "Veille cyber : version initiale"
   git remote add origin https://github.com/VOTRE-COMPTE/veille-cyber.git
   git push -u origin main
   ```
3. **Activez GitHub Pages** : *Settings → Pages → Build and deployment → Source : **GitHub Actions***.
4. **Ajoutez les secrets** dans *Settings → Secrets and variables → Actions*, comme indiqué au § 2. Tous sont facultatifs pour un premier test.
5. **Lancez la première mise à jour** : onglet *Actions → « Mise à jour de la veille » → Run workflow*.
   Après 2 à 5 minutes, le site est en ligne à l'adresse `https://VOTRE-COMPTE.github.io/veille-cyber/`.

Ensuite, tout est automatique : mise à jour toutes les 6 heures, synthèse chaque lundi, et reconstruction du site dès que vous modifiez un fichier de `config/`.

---

## 2. Secrets et variables GitHub

*Settings → Secrets and variables → Actions*. Les **secrets** sont chiffrés et ne s'affichent jamais dans les logs. Les **variables** sont des paramètres non sensibles.

| Nom | Type | Obligatoire ? | Valeur |
|---|---|---|---|
| `LLM_API_KEY` | secret | non (sans elle : pas de résumés IA) | Clé API Anthropic (console.anthropic.com → API Keys) |
| `SMTP_USER` | secret | pour l'e-mail | Adresse Gmail qui envoie, ex. `votre.adresse@gmail.com` |
| `SMTP_PASSWORD` | secret | pour l'e-mail | **Mot de passe d'application** Gmail (§ 3), pas votre mot de passe habituel |
| `SMTP_FROM` | secret | pour l'e-mail | Adresse d'expédition affichée (en général la même que `SMTP_USER`) |
| `NEWSLETTER_RECIPIENTS_INTERNE` | secret | pour l'e-mail | Vos adresses, séparées par des virgules |
| `NEWSLETTER_RECIPIENTS_CLIENTS` | secret | non | Adresses des clients, séparées par des virgules (groupe désactivé par défaut) |
| `NVD_API_KEY` | secret | non | Clé NVD gratuite (nvd.nist.gov/developers) : enrichissement CVSS plus rapide |
| `SITE_URL` | variable | non | URL publique du site si ce n'est pas l'URL GitHub Pages par défaut |
| `SMTP_HOST` / `SMTP_PORT` | variables | non | Pour changer de fournisseur SMTP (par défaut `smtp.gmail.com` / `587`) |

> **Ne collez jamais une clé ou un mot de passe dans un fichier du dépôt, dans une issue ou dans un chat.** Saisissez-les uniquement dans l'écran des secrets GitHub.

---

## 3. Créer le mot de passe d'application Gmail (pas à pas)

Gmail refuse votre mot de passe habituel pour l'envoi SMTP : il faut un **mot de passe d'application** de 16 caractères.

1. Connectez-vous au compte Gmail expéditeur, puis ouvrez **myaccount.google.com**.
2. Menu **Sécurité** → section « Comment vous connecter à Google » → **Validation en deux étapes** → activez-la (SMS ou application d'authentification). *Elle est obligatoire pour l'étape suivante.*
3. Revenez dans **Sécurité**, tapez « **Mots de passe des applications** » dans la barre de recherche du compte, ou ouvrez directement myaccount.google.com/apppasswords.
4. Donnez un nom à l'application, par exemple `veille-cyber-github`, puis cliquez sur **Créer**.
5. Google affiche un code de 16 lettres, de la forme `abcd efgh ijkl mnop`. **Copiez-le sans les espaces.**
6. Dans GitHub, créez le secret `SMTP_PASSWORD` avec ce code, puis `SMTP_USER` et `SMTP_FROM` avec l'adresse Gmail.
7. Testez : *Actions → « Synthèse hebdomadaire » → Run workflow → mode **test***. Seul le groupe « interne » reçoit l'e-mail, avec `[TEST]` dans l'objet.

Si le mot de passe fuit un jour, supprimez-le sur la même page Google : cela n'affecte pas votre mot de passe principal.

**Changer de fournisseur plus tard**, par exemple pour une adresse dédiée `veille@votre-domaine.fr` : créez les variables `SMTP_HOST` et `SMTP_PORT` (port 587 avec STARTTLS) et mettez à jour les trois secrets `SMTP_*`. Aucun code n'est à modifier.

---

## 4. Personnaliser la veille (uniquement des fichiers YAML)

Toute modification poussée sur `main` dans `config/` déclenche automatiquement la reconstruction du site.

### Ajouter un flux : `config/feeds.yaml`
```yaml
  - name: "Nom affiché"
    url: "https://exemple.fr/feed/"
    theme: H4            # H1, H2, H3, H4, EVENTS ou une liste : [H1, H4]
    language: fr         # fr ou en
    priority: 2          # 1 = prioritaire, 3 = secondaire (influence la pertinence)
    enabled: true        # false pour couper un flux sans le supprimer
```
Ajoutez aussi la source dans `config/sources_quality.yaml` (notes AE/IR/PR, organisation, type, pays et domaines des liens) : sans cela, elle reçoit des notes par défaut et ses articles sont marqués « Source non référencée » (un test le signale).

Pour vérifier les flux : *Actions → « Tests » → Run workflow* (case « Vérifier aussi que chaque flux RSS répond »), ou en local `python scripts/check_feeds.py`. L'état de chaque flux s'affiche aussi en bas du site (« Santé des sources »).

**Chaîne YouTube** : ouvrez la chaîne, affichez le code source de la page et cherchez `channel_id` ou `"externalId"`, une chaîne qui commence par `UC…`. Le flux est alors `https://www.youtube.com/feeds/videos.xml?channel_id=UC…`.
**Releases GitHub** : `https://github.com/ORG/PROJET/releases.atom`.

### Ajouter un mot-clé ou un secteur : `config/themes.yaml`
- Mots-clés d'un axe : liste `themes.H1.keywords`, etc. La recherche ignore les majuscules et les accents, et tolère le pluriel.
- Secteurs, technologies, fournisseurs cloud et sujets prioritaires de **vos entreprises** : section `sectoral`. Chaque correspondance augmente la pertinence et s'affiche en badge.
  ```yaml
  sectoral:
    technologies:
      Palo Alto: [Palo Alto, PAN-OS, GlobalProtect]
  ```
- Bruit à écarter (webinaires, contenu sponsorisé…) : `exclusions.title_patterns`.

### Ajouter un destinataire
Modifiez le secret `NEWSLETTER_RECIPIENTS_INTERNE` ou `NEWSLETTER_RECIPIENTS_CLIENTS` (adresses séparées par des virgules). Pour **activer l'envoi aux clients**, passez `newsletter.recipients.clients.enabled` à `true` dans `config/settings.yaml`. Chaque destinataire reçoit **son propre e-mail** : personne ne voit les adresses des autres.

### Mettre à jour les salons : `config/events.yaml`
Modifiez les dates (`start` et `end` au format AAAA-MM-JJ) et mettez `confirmed: true` dès qu'elles sont officielles.

### Cadence de l'axe H3 (IA)
Dans `config/settings.yaml`, le paramètre `newsletter.cadence_h3` vaut `"mensuelle"` (par défaut) ou `"hebdomadaire"`. En mode mensuel, la synthèse ne donne que les titres H3 les lundis ordinaires, puis un bloc détaillé couvrant 30 jours le premier lundi du mois.

---

## 5. Comment sont calculés les scores

Tous les poids sont dans `config/settings.yaml` et peuvent être ajustés.

**Criticité (0-100)**, somme plafonnée à 100 :

| Composante | Points par défaut |
|---|---|
| Une CVE de l'article est au catalogue **CISA KEV** (exploitée activement) | +40 |
| **CVSS** maximal (NVD) | CVSS / 10 × 25 |
| **EPSS** maximal (probabilité d'exploitation à 30 jours) | EPSS × 20 |
| Mots-clés critiques (zero-day, ransomware, RCE, exploitée activement…) | +10 par mot-clé, plafond 25 |
| Source officielle (CERT-FR, CISA, ANSSI, Cybermalveillance) | +10 |

Niveaux : **Critique ≥ 75**, **Élevé ≥ 50**, **Moyen ≥ 25**, sinon **Info**. Survolez le badge sur le site pour voir le détail du calcul.

**Pertinence (0-100)** : 15 points par axe détecté (plafond 30), 10 points par secteur ou technologie de vos entreprises (plafond 30), la priorité du flux (1 → 20, 2 → 10, 3 → 5) et 20 % de la criticité. Seuls les articles dont la pertinence est d'au moins 30 sont résumés par l'IA, du plus pertinent au moins pertinent, dans la limite de 40 par exécution.

---

## 6. Synthèse hebdomadaire et changement d'heure

GitHub Actions ne raisonne qu'en **UTC**, alors que Paris est à UTC+1 en hiver et UTC+2 en été. Le workflow `weekly.yml` se déclenche donc **deux fois** le lundi :

| Déclenchement (UTC) | Heure à Paris en hiver | Heure à Paris en été |
|---|---|---|
| 05:03 | 06:03 → ignoré | **07:03 → envoi** |
| 06:03 | **07:03 → envoi** | 08:03 → ignoré |

Le script vérifie l'heure de Paris et n'envoie qu'à 7 h. Le fichier `data/weekly/sent.json` empêche tout double envoi dans la même semaine. GitHub peut retarder les tâches planifiées de quelques minutes en cas de forte charge.

Modes manuels (*Actions → Synthèse hebdomadaire → Run workflow*) :
- `test` : envoi au groupe interne seulement, avec `[TEST]` dans l'objet ;
- `envoi` : envoi réel à tous les groupes actifs ;
- `archive` : génération du Markdown seulement.

Un **aperçu HTML** de l'e-mail est téléchargeable en bas de chaque exécution (artefact `apercu-newsletter`). L'e-mail est construit pour Outlook : mise en page en tableaux, styles en ligne, largeur de 600 px, pas de JavaScript, couleurs lisibles en mode sombre et version texte de secours.

---

## 7. Sécurité et conformité

- **Secrets** : aucun dans le dépôt. Clés, mots de passe et adresses passent par les secrets GitHub, et les adresses n'apparaissent jamais dans les fichiers versionnés.
- **Moindre privilège** : `permissions: {}` par défaut, puis des droits accordés job par job (`contents: write` pour le commit des données, `pages`/`id-token` pour le déploiement, `issues: write` pour l'alerte d'échec). Une seule exécution à la fois (`concurrency`). Dependabot propose chaque mois les mises à jour des actions et des dépendances, qui sont épinglées.
- **XSS** : tout le contenu issu des flux est inséré dans la page avec `textContent`, jamais avec `innerHTML`. Les liens n'acceptent que `http(s)` et s'ouvrent avec `rel="noopener noreferrer"`. Une politique CSP stricte interdit tout appel externe. Le contenu est échappé dans `feed.xml` (XML) et dans l'e-mail (HTML), et l'export CSV est protégé contre l'injection de formules.
- **Injection de prompt** : le contenu des articles est transmis au LLM comme une donnée délimitée (`<article_non_fiable>`). Le prompt système interdit de suivre les consignes qu'il contient et d'inventer des faits. La réponse doit être un JSON strict, validé champ par champ ; en cas d'échec, le site affiche l'extrait brut.
- **Droit d'auteur** : seuls le titre, le lien et un extrait de 300 caractères au maximum sont stockés. Le texte intégral n'est jamais copié. `robots.txt` est respecté, et l'User-Agent est explicite.
- **Échec** : si un flux tombe, les autres continuent. Si le pipeline échoue, une issue « Échec du pipeline de veille » est ouverte automatiquement, et GitHub vous notifie par e-mail.

---

## 8. État de vérification des flux (à la livraison)

L'environnement de développement n'avait pas accès à ces sites. Les URL ont été vérifiées par recherche documentaire. **Lancez « Vérifier les flux » au premier déploiement** pour obtenir l'état réel, puis corrigez dans `feeds.yaml`.

| Statut | Flux |
|---|---|
| ❌ **Retiré** | ENISA : l'agence a supprimé ses flux RSS (« RSS feeds discontinued ») |
| 🔁 **Remplacé** | MITRE ATLAS (pas de flux d'actualités) → releases GitHub de `mitre-atlas/atlas-data` ; SANS DFIR (pas de flux dédié) → flux global SANS filtré par mots-clés ; ANSSI « IA générative » → flux d'actualités ANSSI filtré par l'axe H3 |
| ✅ **Confirmés par recherche** | ANSSI (version anglaise `cyber.gouv.fr/en/news/rss/`), Cybermalveillance (flux « bonnes pratiques »), Krebs on Security, Dark Reading, et les formats d'URL des releases GitHub et des chaînes YouTube |
| ⚠️ **À confirmer** | Version française du flux ANSSI, Cloud Security Alliance, HiddenLayer, NIST, CERT-FR « menaces et incidents », identifiant YouTube de 13Cubed, flux « actualités » de Cybermalveillance |
| ➖ **Standards** (URL usuelles, très probablement valides) | AWS, Microsoft, Google Cloud, Wiz, Sysdig, Unit 42, Orca, The DFIR Report, SANS ISC, Magnet, Velociraptor, Volatility, Trail of Bits, garak, PyRIT, OWASP GenAI, CERT-FR alertes et avis, BleepingComputer, The Hacker News, LeMagIT, ZATAZ, CISA |

Salons : les trois salons n'ont pas de flux RSS dédié. Ils sont suivis par `events.yaml` (agenda et compte à rebours) et par détection de leur nom dans les articles collectés. CyberShow Paris 2027 a lieu les 27 et 28 janvier 2027 (Espace Champerret). Les dates 2027 de Cloud & Cyber Security Expo et de l'European Cyber Week sont estimées et signalées « à confirmer ».

---

## 9. Développement local

```bash
python -m venv .venv && source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -q                                              # tests unitaires et de bout en bout (hors ligne)
ruff check . && ruff format --check .                  # qualité du code
python -m src.pipeline                                 # exécution réelle (réseau)
python -m src.pipeline --no-collect                    # recalcule KPI et site sans collecter (après un changement de config)
python scripts/export_kpi.py                           # historique des KPI en CSV (Excel, Power BI)
python scripts/kpi_doc.py                              # régénère docs/KPI.md après une modification de kpi.yaml
python -m src.newsletter                               # archive et aperçu build/newsletter_preview.html
cd public && python -m http.server 8000                # puis http://localhost:8000
```

Structure du dépôt :

```
config/      feeds.yaml · themes.yaml · events.yaml · settings.yaml
             kpi.yaml · sources_quality.yaml · glossary.yaml · verification_checklist.yaml · bias.yaml
src/         collect · classify · score · summarize · build_site · newsletter · pipeline · common
             quality · signals · kpi · usage · archive · issues
site/        index.html (modèle unique HTML/CSS/JS vanilla) · favicon.svg
data/        articles.json · summaries_cache.json · feeds_status.json · cache/ · weekly/
             kpi_history.jsonl · kpi_latest.json · improvement_actions.md/.json · weak_signals.md · usage.yaml · archive/
docs/        KPI.md (fiches SMART, générées depuis kpi.yaml)
scripts/     check_feeds.py · export_kpi.py · kpi_doc.py
tests/       test_units.py · test_pipeline.py · test_quality.py · conftest.py (flux synthétiques)
.github/     workflows/update.yml · weekly.yml · ci.yml · dependabot.yml · ISSUE_TEMPLATE/ (usage, signal transformé)
```

Le site généré est écrit dans `public/` (non versionné) puis publié par GitHub Pages : `index.html`, `articles.json`, `feed.xml`, `kpi.json` et `kpi_history.csv`.

**Ajouter un fournisseur LLM** : dans `src/summarize.py`, créez une classe qui hérite de `LLMProvider` et implémente `complete(system, user) -> str`, ajoutez-la à `PROVIDERS`, puis indiquez son nom dans `settings.yaml → llm.provider`.

---

## 10. Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| Le site affiche une erreur 404 | Pages n'est pas activé, ou pas encore déployé | *Settings → Pages → Source : GitHub Actions*, puis relancez le workflow |
| Le workflow échoue à l'étape « Enregistrer les données » | Le jeton n'a pas les droits d'écriture | *Settings → Actions → General → Workflow permissions* : « Read and write » |
| Le déploiement est refusé (environment protection) | La branche n'est pas autorisée | *Settings → Environments → github-pages* : autorisez `main` |
| `535 Authentication failed` (e-mail) | Mot de passe d'application absent ou erroné | Recréez-le (§ 3) ; vérifiez que la validation en 2 étapes est active |
| Aucun e-mail le lundi | Secrets de destinataires vides, ou synthèse déjà envoyée cette semaine | Consultez le log du run ; lancez le mode `test` |
| Pas de résumés IA | `LLM_API_KEY` absente, crédit épuisé ou modèle invalide | Vérifiez le secret et `llm.model` dans `settings.yaml` ; le site reste fonctionnel |
| Un flux est « Erreur » en bas du site | URL changée ou site indisponible | `python scripts/check_feeds.py`, puis corrigez ou passez `enabled: false` |
| Trop d'articles hors sujet | Mots-clés trop larges | Ajoutez des motifs dans `exclusions` ou retirez des mots-clés génériques |
| Exécution trop longue | Beaucoup de nouvelles CVE à enrichir (limite NVD) | Ajoutez le secret `NVD_API_KEY` ou baissez `nvd_max_lookups_per_run` |
| Un KPI affiche « n.d. » | Données insuffisantes (pas d'usage déclaré, pas d'article important, période d'apprentissage) | Normal au démarrage ; le pipeline continue ; voir § 12 |
| « Signaux faibles : période d'apprentissage » | Moins d'une semaine d'historique de collecte | Patientez ; la détection compare la semaine aux 4 précédentes |
| Les usages déclarés ne sont pas comptés | Issue sans étiquette `usage` / `signal-transforme`, ou champ « Identifiant » invalide | Créez l'issue via le lien « Signaler un usage » ; les étiquettes sont créées à la 1re exécution |
| Trop d'issues « Action d'amélioration » | Cibles trop ambitieuses pour vos sources | Ajustez `cible`, `seuil_alerte` ou `periodes_consecutives` dans `config/kpi.yaml` |

---

## 11. Hypothèses retenues

- La section « Mes entreprises » du cahier des charges n'étant pas remplie, les **valeurs d'exemple** ont été reprises : santé, industrie, finance et collectivités ; Microsoft 365, Fortinet, VMware, Veeam, Citrix et Ivanti ; Azure, AWS, GCP, OVHcloud et S3NS ; ransomware, NIS2 et souveraineté du cloud. Adaptez `themes.yaml → sectoral`.
- Le modèle LLM par défaut est un modèle **Haiku**, rapide et économique (`claude-haiku-5-5`). Vous pouvez le changer dans `settings.yaml`.
- Le site généré est publié depuis `public/`, et non `site/` qui contient le modèle. Le flux RSS est servi à l'adresse `…/feed.xml`.
- La période affichée par défaut sur le site est de 7 jours, et les données sont conservées 90 jours.

---

## 12. Qualité de la veille : KPI et pilotage

> **Toutes les cibles, tous les seuils, poids et notes de sources livrés sont des valeurs initiales à valider.** Observez 4 à 8 semaines, puis ajustez-les dans les fichiers YAML (aucun code à modifier).

### Comment ça marche
À chaque exécution (toutes les 6 heures), après les résumés :
1. **`quality.py`** contrôle chaque article (domaine approuvé, HTTPS, date plausible, CVE confirmées, recoupement par 2 organisations indépendantes, ton non sensationnaliste) et lui attribue un **badge de fiabilité** : ✔ Vérifié, ⚠ À recouper ou ✖ Source non référencée. Il calcule aussi le **Source Quality Score** et l'**indice d'autorité** de chaque source.
2. **`signals.py`** détecte les **signaux faibles** : termes (concepts du glossaire, noms de produits, familles de logiciels malveillants) en forte hausse sur la semaine par rapport aux 4 précédentes, mais encore rares. Pendant la première semaine de collecte, la détection est en **période d'apprentissage**.
3. **`kpi.py`** calcule les **22 KPI** de `config/kpi.yaml` (familles A à F), les compare à leurs cibles, enregistre un instantané dans `data/kpi_history.jsonl` (conservé sans limite) et applique le **SLA** : un KPI orange ou rouge pendant N périodes consécutives ouvre une action dans `data/improvement_actions.md` et **une seule** issue GitHub « Action d'amélioration » (étiquette `amelioration`), fermée automatiquement quand le KPI revient au vert.
4. **`archive.py`** conserve une archive légère de chaque article au-delà des 90 jours du site (`data/archive/AAAA-MM.jsonl`, sans texte intégral), compressée en `.gz` après 12 mois.

Les fiches SMART de chaque KPI (définition, formule, source des données, fréquence, cible, seuil, responsable, action corrective) sont dans **[docs/KPI.md](docs/KPI.md)**.

### Lire la page « KPI & qualité »
- **Vue d'ensemble** : chaque KPI avec sa valeur, sa cible et son statut. Le statut est indiqué par un symbole et un texte, pas seulement par une couleur : ✔ Dans la cible, ▲ À surveiller, ✖ Hors seuil, ● Observation, – Non disponible. Cliquez sur « Définition SMART » pour la fiche du KPI.
- **Tendances** : mini-graphiques sur 4, 12 ou 52 semaines (boutons en haut). Ils se remplissent au fil des exécutions.
- **Objectifs SMART par axe**, **plan d'amélioration continue**, **classement des sources** (qualité, pertinence, crédibilité, nouveauté, efficacité, délai, autorité), **signaux faibles de la semaine**, **biais** et **checklist de vérification**.
- **Exporter les KPI (CSV)** : historique complet pour Excel ou Power BI (séparateur `;`). Même fichier en local : `python scripts/export_kpi.py`.

Un KPI qui ne peut pas être calculé (pas encore d'usage déclaré, pas d'article important cette semaine…) s'affiche « non disponible » et ne bloque jamais le pipeline.

### Modifier les cibles, les seuils et les poids
| Je veux… | Fichier | Clé |
|---|---|---|
| Changer la cible ou le seuil d'un KPI | `config/kpi.yaml` | `cible`, `seuil_alerte` |
| Déclencher une action plus tôt ou plus tard | `config/kpi.yaml` | `periodes_consecutives` |
| Modifier le texte de l'action proposée | `config/kpi.yaml` | `action` (`{sujet}` = axe ou source) |
| Changer le seuil de pertinence | `config/kpi.yaml` | `parametres.seuil_pertinence` |
| Régler la détection des signaux faibles | `config/kpi.yaml` | `signaux_faibles` (croissance, rareté, mots ignorés) |
| Changer les poids du score de qualité ou de la crédibilité | `config/settings.yaml` | `quality.sqs_weights`, `quality.credibility_weights` |
| Corriger la note d'une source | `config/sources_quality.yaml` | `ae`, `ir`, `pr`, `type`, `country`, `org`, `domains` |
| Fixer l'objectif SMART d'un axe | `config/themes.yaml` | `themes.Hx.objectifs` (`smart`, `cible_hebdo`, `echeance`, `horizon`) |
| Modifier la checklist ou le badge | `config/verification_checklist.yaml` | `criteres`, `credibilite_suffisante`, `formulations_sensationnalistes` |
| Documenter un biais | `config/bias.yaml` | `biais` |

Après une modification de `kpi.yaml`, lancez `python scripts/kpi_doc.py` pour régénérer `docs/KPI.md` (un test vérifie que la documentation est à jour).

### Ajouter un terme au glossaire bilingue : `config/glossary.yaml`
```yaml
  - {id: double-extorsion, label: "Double extorsion", axes: [H4],
     fr: [double extorsion], en: [double extortion]}
```
Le terme sert au classement par axe et aux signaux faibles **dans les deux langues** : un article français et un article anglais sur le même sujet sont traités de la même façon. Le KPI E3 mesure la part d'articles rattachés à un axe grâce au glossaire.

### Risque de double traduction
Le titre et l'extrait d'origine sont toujours conservés. Le résumé français est produit **en une seule étape, directement depuis l'original**, jamais à partir d'un texte déjà traduit ou résumé. Chaque article enregistre sa langue source et son nombre d'étapes de traduction (KPI E1 et E2), et chaque carte affiche le titre d'origine à côté du résumé.

### Déclarer un usage ou un signal faible transformé
- **Le plus simple** : sur une carte d'article, cliquez sur **« Signaler un usage »**. Un formulaire GitHub s'ouvre, pré-rempli avec l'identifiant de l'article. Choisissez le type d'usage (alerte envoyée, correctif appliqué, note rédigée, sensibilisation, hypothèse de transformation, ou article écarté comme hors sujet) puis validez.
- **Signal faible transformé** : *Issues → New issue → « Signal faible transformé »*. La fiche d'hypothèse correspondante (signal, hypothèse, indicateurs, échéance, décision) est préparée automatiquement dans `data/weak_signals.md`.
- **Sans GitHub** : ajoutez une entrée dans `data/usage.yaml` (exemple dans le fichier).

Le pipeline lit les issues étiquetées `usage` et `signal-transforme` avec le jeton automatique de GitHub Actions, et ne garde que des champs validés (identifiant, type, date, entreprise). Les commentaires ne sont jamais repris sur le site. **Le dépôt étant public, ne saisissez aucune information confidentielle dans une issue.**

### Données produites (dans `data/`)
| Fichier | Contenu |
|---|---|
| `kpi_history.jsonl` | Un instantané des KPI par exécution, sans limite de durée |
| `kpi_latest.json` | Dernier rapport (site et e-mail) |
| `improvement_actions.md` / `.json` | Plan d'amélioration continue (actions ouvertes et résolues) |
| `weak_signals.md` | Fiches d'hypothèse de transformation des signaux faibles (vos ajouts sont conservés) |
| `usage.yaml` | Journal d'usage manuel |
| `archive/AAAA-MM.jsonl(.gz)` | Archive légère des articles au-delà de 90 jours |

La synthèse du lundi contient désormais un bloc **« Santé de la veille »** : les KPI hors cible, les signaux faibles de la semaine et les actions proposées.

