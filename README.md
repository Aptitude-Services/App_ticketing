# Aptitude Support — jalons 1 à 3

Application de gestion de tickets client d'Aptitude Services (Django 5.2 LTS, PostgreSQL 16, Docker).
Le jalon 1 pose le socle (comptes, profils, cloisonnement, MFA, audit) ; le jalon 2 ajoute le référentiel contractuel et le moteur SLA.

## Ce que contient le jalon 1

| Domaine | Contenu |
| --- | --- |
| Organisations | Aptitude et clients, domaines email, activation |
| Utilisateurs | Connexion par email, 7 profils, langue FR/EN, invitation par email |
| Cloisonnement | `accounts/permissions.py` : point unique qui décide de ce qu'un utilisateur voit |
| Affectations aux contrats | Engineer (restricted) et utilisateur client limité par son admin |
| Gestion par l'admin client | Création et modification des comptes de son organisation, limitation par contrat, protection du dernier admin |
| MFA | TOTP obligatoire pour Aptitude, optionnelle pour les clients (exigée dès qu'elle est activée) |
| Sécurité | Verrouillage après 5 échecs (30 min), sessions de 8 h, cookies sécurisés, HSTS, `/gestion` filtrable par IP |
| Audit | Connexions, échecs, créations et modifications de comptes, activation MFA (lecture seule dans l'admin) |
| Contrats | Référence, client, type de contrat, statut, champs de forfait prévus et inactifs |

## Ce que contient le jalon 2

| Domaine | Contenu |
| --- | --- |
| SLA | Couverture 24x7 ou 8x5 (plages et jours ouvrés paramétrables), objectifs de prise en charge et de résolution par priorité |
| Grille par défaut | « SLA 24x7 » et « SLA 8x5 » : P1 1 h / 8 h, P2 1 h / 12 h, P3 4 h / 24 h, P4 8 h / 48 h |
| Priorités | P1 à P4 et leurs définitions ; règles d'escalade (client jusqu'à P3, Aptitude seule en P2/P1) appliquées au jalon 3 |
| Jours fériés | Fériés ivoiriens 2026-2027 préchargés, report au lundi des fêtes concernées, commande `load_holidays` |
| Moteur SLA | `sla/engine.py` : échéance, temps écoulé, couverture à un instant donné, prochaine ouverture |
| Types de contrat | Chaque type porte un SLA (« Standard 24x7 », « Standard 8x5 » créés par défaut) |
| Solutions | Matériel, logiciel, VM, réseau, sécurité, cloud, service ; rattachées à un contrat, cloisonnées comme lui |
| Page contrat | Engagements de service, couverture en cours, prochains fériés, solutions couvertes |

## Ce que contient le jalon 3

| Domaine | Contenu |
| --- | --- |
| Tickets | Référence APT-AAAA-NNNNN, contrat, solutions du contrat, demandeur, assigné, canal |
| Règles | Toutes dans `tickets/services.py` : droits, couverture 8x5, priorités, SLA, historique |
| Couverture 8x5 | Client bloqué hors heures ouvrées ; Aptitude peut créer, le ticket est marqué « hors couverture » |
| Priorités | Création en P4 ; client jusqu'à P3 ; P2 et P1 par Aptitude avec justification ; une escalade ne recule jamais une échéance |
| P1 | Statut « En attente de prérequis » ; la résolution (8 h) démarre à la prise en charge actée |
| Délais | Prise en charge puis résolution, en heures calendaires (24x7) ou ouvrées (8x5) ; pause en attente client, reprise à la réponse |
| Suivis | Messages publics, notes internes Aptitude, pièces jointes (10 Mo, types contrôlés, téléchargement après contrôle d'accès) |
| Cycle de vie | Nouveau, pris en charge, en cours, en attente client, en attente de prérequis, résolu, clos ; réouverture par le client ; clôture automatique après 1 jour |
| Interface | Console pour l'équipe Aptitude, portail aéré pour les clients, thème clair ou sombre enregistré par utilisateur |
| Tableaux de bord | Console : tickets ouverts, SLA à risque et dépassés, délais tenus, courbe 30 jours, respect par couverture, clients, solutions, priorités, activité. Portail : demandes en cours, réponse attendue, contrats, résolues récemment |

### Tâches automatiques (planificateur intégré)

Le service `scheduler` de docker-compose (même image que le site) démarre et redémarre avec lui :
**aucun cron à configurer**. Il vérifie chaque minute et lance, au plus une fois par heure :

- la **clôture automatique** des tickets résolus depuis plus d'un jour ;
- les **alertes d'expiration de licence**, dans la plage d'envoi choisie.

Les alertes se règlent dans `/gestion` → Contrats et solutions → **Paramètres des alertes de licence**,
sans redéploiement (prise en compte au passage suivant, dans l'heure) :

- activation ou suspension de l'envoi automatique ;
- nombre et écart des rappels (par défaut « 5, 3, 1 » mois ; ex. « 6, 2 » ou, en jours, « 30, 7, 0 ») ;
- destinataires : client ESN (ses administrateurs, à défaut tous ses comptes actifs), administrateurs du
  client final du contrat, managers d'Aptitude ; un client final ne reçoit que ses propres licences ;
- plage d'envoi (par défaut 7 h – 19 h, heure d'Abidjan).

La fiche affiche aussi le dernier passage du planificateur. Une alerte déjà envoyée à un seuil ne repart
pas ; si l'email échoue, elle est retentée l'heure suivante. Les envois sont tracés dans
`/gestion` → Alertes d'expiration de licence. L'envoi manuel reste possible (Solutions ou Contrats →
action « Notifier l'ESN »).

Vérifier que le planificateur tourne et voir ce qu'il a fait :

```bash
docker compose ps scheduler
docker compose logs --tail 50 scheduler
```

Lancement manuel ponctuel (affiche le nombre d'emails envoyés) :

```bash
docker compose exec web python manage.py notify_license_expiry
docker compose exec web python manage.py close_resolved_tickets
```

### Jours fériés : entretien annuel

```bash
docker compose exec web python manage.py load_holidays 2028
```

Les fêtes fixes et celles liées à Pâques sont calculées. Les fêtes musulmanes (lendemain de la Nuit du Destin, Aïd el-Fitr, Tabaski, lendemain du Maouloud) et les éventuels lundis chômés qu'elles entraînent sont à saisir dans `/gestion` dès le communiqué officiel. Pour 2026, elles sont déjà chargées.

## Profils

| Profil | Contrats visibles | Gère les utilisateurs |
| --- | --- | --- |
| Super Admin | Tous | Tous |
| Manager | Tous | Comptes clients |
| Engineer | Tous | Non |
| Engineer (restricted) — en réserve, non proposé | Ceux affectés | Non |
| Client Admin | Tous ceux de son organisation | Son organisation |
| Client User | Ceux de son organisation, ou une sélection | Non |
| Client Viewer | Ceux de son organisation, ou une sélection | Non |

## Démarrer en local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export DJANGO_DEBUG=1
python manage.py migrate
python manage.py seed_demo          # comptes de démo, mot de passe : Demo-Aptitude-2026
python manage.py runserver
```

Comptes de démo : `admin@aptitudes.net` (admin Aptitude, MFA demandée à la première connexion), `admin@banque-lagune.ci` (admin client), `compta@banque-lagune.ci` (lecture seule limitée au contrat SOC).
En local, les emails (invitations) s'affichent dans la console.

## Messagerie

L'admin Aptitude règle l'envoi des emails dans **Configuration > Messagerie** (`/configuration/messagerie/`), sans redémarrer :

| Mode | Usage |
| --- | --- |
| Paramètres du serveur | Comportement du `.env` (`EMAIL_BACKEND` : console en dev, Microsoft Graph ou SMTP en production). Mode par défaut |
| Serveur SMTP | Tout serveur SMTP (hébergeur, relais interne, Microsoft 365 en SMTP AUTH) : hôte, port, STARTTLS ou SSL, identifiant |
| Microsoft 365 (API Graph) | Tenant, application et secret saisis dans l'application plutôt que dans le `.env` |
| Désactivé | Aucun envoi ; les messages sont seulement inscrits au journal |

La page propose un envoi de test et affiche les 50 derniers envois (statut, erreur). Le journal complet est dans `/gestion`. Les secrets (mot de passe SMTP, secret Graph) sont chiffrés en base avec une clé dérivée de `DJANGO_SECRET_KEY` : si cette clé change, il faut les ressaisir. Chaque modification est tracée dans l'audit, sans les secrets.

## Tests

```bash
pytest
```

92 tests couvrent le cloisonnement (contrats, solutions, utilisateurs, pages), les droits de l'admin client, la protection du dernier admin, l'invitation, l'audit, la MFA le moteur SLA (heures ouvrées, week-ends, fériés, cohérence échéance et temps écoulé), la messagerie (modes d'envoi, journal, secrets chiffrés, accès réservé à l'admin Aptitude) et les tickets (couverture 8x5, escalade, P1, pauses, pièces jointes, notes internes, isolation par le navigateur).
Toute nouvelle vue doit filtrer ses données via `accounts/permissions.py` et ajouter son test d'isolation.

## Déployer sur le VPS

Prérequis : Docker et Docker Compose, un nom DNS pointant vers le serveur (aujourd'hui `support.aptitudes.local` → `10.10.1.77`, site publié en HTTPS sur le port 8843).

```bash
cp .env.example .env
# éditer .env : SITE_DOMAIN, DJANGO_ALLOWED_HOSTS, DJANGO_CSRF_TRUSTED_ORIGINS, DJANGO_SECRET_KEY, POSTGRES_PASSWORD, ADMIN_ALLOWED_IPS
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # pour DJANGO_SECRET_KEY
sh docker/certs/creer-certificat.sh support.aptitudes.local 10.10.1.77   # voir « Certificat HTTPS »
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

Les migrations s'appliquent à chaque démarrage du conteneur `web`.
L'administration est à `https://support.aptitudes.local:8843/gestion/` ; restreignez `ADMIN_ALLOWED_IPS` aux IP ou au VPN d'Aptitude.

### Certificat HTTPS (autorité interne Aptitude)

Let's Encrypt ne délivre **pas** de certificat pour un nom en `.local`. Tant que le site s'appelle
`support.aptitudes.local`, le certificat est signé par une **autorité de certification interne** Aptitude.
Sans certificat valide, le navigateur affiche une alerte et **l'application (PWA) ne s'installe pas sur mobile**.

1. **Créer l'autorité et le certificat** (sur le serveur, depuis la racine du projet) :

   ```bash
   sh docker/certs/creer-certificat.sh support.aptitudes.local 10.10.1.77
   # noms supplémentaires possibles à la suite, ex. : ... 10.10.1.77 support.aptitudes.net
   ```

   Le script écrit dans `./certs` (jamais versionné) : `support.crt` / `support.key`, lus par Traefik
   (`docker/traefik/tls.yml`), et le certificat racine à distribuer `aptitude-ca.crt` (et `.cer` pour Windows).
   Il affiche l'empreinte SHA-256 de l'autorité : vérifiez-la sur chaque appareil lors de l'installation.
   **Copiez ensuite `certs/ca/aptitude-ca.key` hors du serveur** (coffre, clé USB chiffrée) et supprimez-le du serveur.
   L'autorité est limitée par construction aux noms `aptitudes.local`, `aptitudes.net` et aux IP privées.

2. **Faire confiance à l'autorité, une seule fois par appareil** :
   - **PC du domaine** : stratégie de groupe → Configuration ordinateur → Paramètres Windows → Paramètres de sécurité →
     Stratégies de clé publique → *Autorités de certification racines de confiance* → importer `aptitude-ca.cer`.
     Hors domaine : double-clic sur `aptitude-ca.cer` → Installer → Ordinateur local → *Autorités de certification racines de confiance*.
   - **Android** : Paramètres → Sécurité → Chiffrement et identifiants → Installer un certificat → *Certificat CA* → `aptitude-ca.crt`
     (libellés variables selon le fabricant). Ouvrir ensuite le site dans Chrome → menu → *Installer l'application*.
   - **iPhone / iPad** : envoyer `aptitude-ca.crt` (mail, AirDrop) → Réglages → *Profil téléchargé* → Installer, puis
     Réglages → Général → Informations → *Réglages des certificats* → activer la confiance totale.
     Ouvrir ensuite le site dans Safari → Partager → *Sur l'écran d'accueil*.

3. **Renouveler tous les ans** (le certificat du site vaut 397 jours, maximum accepté par les iPhone) : remettre la clé de
   l'autorité dans `certs/ca/`, relancer la même commande. Traefik recharge le certificat sans redémarrage, et rien n'est
   à réinstaller sur les appareils (même autorité). Le script refuse de créer une nouvelle autorité si la clé manque.

> **Mobiles et `.local`** : iPhone et Android résolvent souvent les noms en `.local` par multicast (Bonjour) et non par le DNS
> de l'entreprise ; le site peut alors être introuvable sur téléphone. Le certificat couvre aussi l'IP (`https://10.10.1.77:8843`).
> La solution durable est un nom en `aptitudes.net` (le DNS interne gère déjà cette zone) : ajoutez `support.aptitudes.net`
> au certificat et à `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS`.

**Passer à Let's Encrypt plus tard** : avec un nom public (ex. `support.aptitudes.net`) et `SITE_DOMAIN` mis à jour,
lancer `docker compose -f docker-compose.yml -f docker-compose.letsencrypt.yml up -d` (prérequis dans ce fichier).

Sauvegarde de la base (à planifier en cron, puis copier hors du VPS) :

```bash
docker compose exec -T db pg_dump -U aptitude aptitude_support | gzip > backup-$(date +%F).sql.gz
```

## Organisation du code

```
config/      paramètres, URLs (settings_test.py pour les tests)
accounts/    organisations, utilisateurs, profils, permissions, MFA, audit
contracts/   types de contrat, contrats, solutions, accès
sla/         SLA, objectifs, jours fériés, moteur de calcul
tickets/     tickets, suivis, pièces jointes, historique, règles métier (services.py)
core/        tableau de bord, commande seed_demo
templates/   gabarits (charte Aptitude : orange #F58436, brun #A85A25, bleu nuit #1F2D3D, Montserrat)
static/img/  logos Aptitude (version claire, version blanche pour fond sombre, icône, favicons)
docker/      script de démarrage du conteneur
```

## Points restant ouverts

- Traduction anglaise : les textes sont balisés pour la traduction ; le fichier `locale/en` sera rempli avec `makemessages` (outils gettext requis) avant la mise en production.
- La police Montserrat est chargée depuis Google Fonts ; elle pourra être auto-hébergée si vous souhaitez zéro appel externe.
