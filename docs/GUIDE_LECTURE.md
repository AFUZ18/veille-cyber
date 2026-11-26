# Guide de lecture de la veille cyber

Ce guide explique, en français simple, comment lire le site : https://afuz18.github.io/veille-cyber/

Le site a trois pages, accessibles en haut : **Actualités**, **Santé de la veille** et **Aide**.

---

## 1. La page « Actualités » (page d'accueil)

### En 30 secondes
1. **Lisez la phrase en haut.** Elle résume la semaine, par exemple :
   > Cette semaine : aucune alerte urgente, 7 sujets importants.
2. **Lisez le bloc « À lire en priorité ».** Il contient 3 à 5 articles maximum. Chacun dit **pourquoi c'est important** et **que faire**, par exemple :
   > ● Important · ⚠ Déjà utilisée par des pirates
   > **China-Linked Hackers Exploit Critical VMware vCenter Zero-Day…**
   > Pourquoi c'est important : Cette faille est déjà utilisée par des pirates.
   > Que faire : Vérifiez si vous utilisez ce produit et appliquez le correctif sans attendre.
3. C'est tout pour l'essentiel. Le reste de la page sert à approfondir.

### Les niveaux
| Affiché | Signification | Quand agir |
|---|---|---|
| ⚠ **Urgent** | Faille grave, souvent déjà exploitée | Aujourd'hui |
| ● **Important** | Sujet sérieux pour les entreprises | Cette semaine |
| ◐ **À suivre** | Utile pour rester informé | Quand vous avez le temps |
| ○ **Pour info** | Contexte général | Aucune action attendue |

Le badge **« Déjà utilisée par des pirates »** signale une faille que les autorités américaines (CISA) ont constaté exploitée par des attaquants.

### Trier les articles
- **Onglets** : Tout, Cloud, Forensique (enquête après une attaque), IA, Général, Salons.
- **Trois réglages seulement** : la recherche, l'interrupteur « Urgent seulement » et la période (7 derniers jours par défaut).
- **« Plus de filtres »** : source, fiabilité, 24 heures ou 30 jours, niveau minimum, failles déjà utilisées par des pirates.

### Les « Détails » d'un article
Sous chaque article, **« Détails »** affiche les informations techniques : titre et extrait d'origine, sujets (avec leurs codes H1 à H4), failles citées (numéros CVE) avec leur gravité, scores, **fiabilité** (Vérifiée, À recouper, Source inconnue) et le lien **« Signaler un usage »**. Chaque sigle a un petit **?** qui en donne la définition.

> Les résumés en français sont rédigés par une IA à partir de l'article : vérifiez toujours la source avant d'agir. Tant que la clé d'IA n'est pas configurée, la carte affiche seulement le niveau, le titre et une phrase « Pourquoi / Que faire » fondée sur des règles simples.

---

## 2. La page « Santé de la veille »

Elle répond à une question : **la veille fonctionne-t-elle bien, et que faire sinon ?**

### En 2 minutes
1. **Le bandeau orange** rappelle que les objectifs sont provisoires pendant les 4 premières semaines : on observe d'abord la réalité.
2. **Le bilan** ne fait pas de moyenne trompeuse, il compte :
   > 3 points fonctionnent, 2 sont à surveiller, 2 posent problème, 2 ne sont pas encore mesurables.
3. **« À traiter en premier »** : 3 actions maximum, classées par importance, par exemple :
   > 1. ✖ Problème · Corriger ou désactiver les 11 sources en panne.
   > 2. ✖ Problème · Veille peu variée : ajouter des sources françaises.
   > 3. ▲ À surveiller · Vérifier que la mise à jour automatique tourne bien toutes les 6 heures.
4. **Les 9 cartes**, une question chacune.

### Les quatre réponses possibles
| Réponse | Signification |
|---|---|
| ✔ **Bon** | L'objectif est atteint. |
| ▲ **À surveiller** | Entre l'objectif et le seuil d'alerte. |
| ✖ **Problème** | Le seuil d'alerte est franchi : une action est proposée. |
| … **Pas encore de données** | Impossible à mesurer pour l'instant (pas assez d'historique, ou personne n'a encore rien déclaré). La carte dit pourquoi et à partir de quand ce sera mesurable. **Ce n'est jamais une erreur et cela ne déclenche aucune alerte.** |

L'étiquette **« Estimation »** signale une valeur fondée sur des notes saisies à la main (par exemple la fiabilité des sources), et non sur une mesure.

### Les 9 questions
| Question | Exemple de réponse (26 novembre 2026) |
|---|---|
| Mes sources fonctionnent-elles ? | ✖ Problème : 23 sources sur 34 répondent |
| Reçoit-on les informations assez vite ? | ▲ À surveiller : la moitié des articles arrive en moins de 7,2 heures |
| Les articles sont-ils utiles ? | ✔ Bon : 6 articles sur 10 correspondent à vos sujets |
| Chaque sujet est-il bien couvert ? | ✔ Bon : mini-barres Cloud, Forensique, IA, Général avec leur objectif (Forensique est le moins fourni, et c'est normal) |
| Les infos importantes sont-elles confirmées ? | ▲ À surveiller : 3 alertes importantes sur 10 confirmées par 2 sources |
| Les sources sont-elles fiables ? | ✔ Bon · Estimation : note moyenne 76 sur 100 |
| La veille est-elle variée ? | ✖ Problème : 87 % d'articles en anglais, 13 % de sources françaises |
| La veille sert-elle à quelque chose ? | … Pas encore de données : personne n'a encore déclaré d'usage |
| Repère-t-on des sujets émergents ? | … Pas encore de données : la détection démarre le 30/11/2026 |

### Faire passer « La veille sert-elle à quelque chose ? » au vert
Dès qu'un article vous sert (alerte envoyée à un client, correctif appliqué, note rédigée, sensibilisation), ouvrez ses **Détails** et cliquez sur **« Signaler un usage »**. Un formulaire GitHub pré-rempli s'ouvre : choisissez le type d'usage et validez. C'est tout.

### Pour les spécialistes
En bas de la page, **« Détails techniques »** donne accès aux 22 indicateurs complets, avec leurs tendances sur 4, 12 ou 52 semaines, le classement des sources, les sujets émergents, les biais, la grille de vérification, l'état de chaque source et l'export tableur. Les fiches détaillées sont dans [docs/KPI.md](KPI.md).

---

## 3. Les alertes

- **Pendant les 4 premières semaines**, aucune alerte automatique n'est créée.
- **Ensuite**, une **seule** demande GitHub « Revue de la veille » liste chaque semaine les points en « Problème », avec une action par ligne et la liste des sources en panne. Elle se ferme automatiquement quand plus rien ne pose problème.
- **L'e-mail du lundi** contient un bloc « Santé de la veille » de 3 lignes : le bilan, ce qu'il faut traiter en premier et ce qui n'est pas encore mesurable.
