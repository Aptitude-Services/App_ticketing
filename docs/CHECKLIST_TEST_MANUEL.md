# Checklist de test manuel de bout en bout — Aptitude Support

À dérouler dans l'ordre : chaque partie s'appuie sur ce qui a été créé avant.
Cocher `[x]` au fur et à mesure et noter les anomalies dans la dernière section.
Complète `PLAN_DEMONSTRATION.md` (parcours de démo) avec les contrôles négatifs.

> Astuce : utiliser une fenêtre de navigation privée par compte (ou plusieurs
> navigateurs) pour garder Admin, Ingénieur, Manager et Client connectés en parallèle.

---

## 0. Préparation de l'environnement

- [ ] Base propre (ou copie de sauvegarde de `db.sqlite3`) et `python manage.py migrate` sans erreur
- [ ] `python manage.py load_holidays` → jours fériés présents dans Administration → Jours fériés
- [ ] Un compte Super Admin existe (`create_test_user` ou `createsuperuser`)
- [ ] Une application d'authentification (Google/Microsoft Authenticator) sur le téléphone, pour la MFA
- [ ] 6 à 7 adresses email réellement lisibles (alias `+test1`, `+test2`… ou boîte de test) pour suivre les emails
- [ ] Préparer des fichiers de test : 1 PDF, 1 PNG, 1 `.exe` (refus attendu), 1 fichier > 10 Mo (refus attendu), 1 logo PNG/SVG

---

## 1. Ce qu'il faut créer (récapitulatif des données de test)

| # | Élément | Où | Valeurs suggérées |
|---|---|---|---|
| 1 | Messagerie | Configuration → Messagerie | SMTP ou Microsoft Graph, puis « Envoyer un test » |
| 2 | ESN A | Administration → Organisations | Type *Client ESN*, logo, domaine `esna.test` |
| 3 | ESN B (contrôle d'isolement) | idem | Type *Client ESN*, domaine `esnb.test` |
| 4 | Client final A1 | Fiche ESN A → « Nouveau client final » | Secteur *Banque* |
| 5 | Client final A2 | idem | Secteur *Santé* (sert à tester les droits par client) |
| 6 | Client final B1 | Fiche ESN B → « Nouveau client final » | n'importe quel secteur |
| 7 | Critères de service | Administration → Critères / Prestations | vérifier qu'ils existent (Support N3, Supervision, SOC…) |
| 8 | Formule 24x7 | Administration → Formules | ex. GOLD, SLA 24x7, critères cochés |
| 9 | Formule 8x5 | idem | ex. SILVER, SLA 8x5 (pour tester la couverture) |
| 10 | Contrat A-GOLD | Administration → Contrats | ESN A, client final A1, formule GOLD, solutions via **import Excel** |
| 11 | Contrat A-SILVER | idem | ESN A, client final A2, formule SILVER, solutions **saisies ligne par ligne** |
| 12 | Contrat B | idem | ESN B, client final B1 |
| 13 | Manager | Équipe interne → Nouvel utilisateur | profil *Manager* |
| 14 | Ingénieur | idem | profil *Engineer*, supérieur = le Manager |
| 15 | 2ᵉ Manager | idem | profil *Manager* (contrôle : ne doit pas valider les rapports d'un autre) |
| 16 | Admin ESN A | Clients → Nouvel utilisateur | organisation ESN A, *Client Admin* |
| 17 | Admin ESN B | idem | organisation ESN B, *Client Admin* |
| 18 | Client User A1 | (connecté en Admin ESN A) Utilisateurs → Nouveau | organisation A1, *Client User* |
| 19 | Client Viewer A1 | idem | organisation A1, *Client Viewer* |
| 20 | Client User A2 | idem | organisation A2, *Client User* |
| 21 | Client User B1 | (connecté en Admin ESN B) | organisation B1, *Client User* |

---

## 2. Référentiel (Super Admin)

### Connexion & sécurité
- [ ] Connexion Super Admin → MFA demandée (activation à la 1ʳᵉ connexion, puis code à chaque connexion)
- [ ] Mauvais mot de passe → refus + « Échec de connexion » dans le journal d'audit
- [ ] Déconnexion OK, retour à l'écran de connexion
- [ ] « Mot de passe oublié » → email reçu → lien → nouveau mot de passe fonctionne
- [ ] Changer son mot de passe depuis le profil
- [ ] Thème clair / sombre / système + langue FR/EN depuis le profil

### Messagerie
- [ ] Saisir la configuration, enregistrer → entrée « Messagerie modifiée » dans l'audit
- [ ] « Envoyer un test » → email reçu ; en cas d'échec, message d'erreur lisible
- [ ] Journal des emails envoyés : statut envoyé / échec visible

### Organisations
- [ ] Créer ESN A avec logo + domaines email ; le secteur d'activité n'est pas demandé pour une ESN
- [ ] Bouton « Nouveau client final » depuis la fiche ESN → client rattaché à l'ESN
- [ ] Secteur d'activité proposé pour un client final (liste alphabétique, « Autre » en dernier)
- [ ] Nom d'organisation en double → refus

### Formules et contrats
- [ ] Formule : SLA, critères de service par catégorie, forfait de tickets enregistrés
- [ ] Contrat : après choix du **Client ESN**, la liste **Client final** ne propose que ses clients finaux
- [ ] Référence attribuée à l'enregistrement au format `ESN-CLIENT-ANNÉE-NNN` ; 2ᵉ contrat → numéro suivant
- [ ] Critères ajoutés / exclus par rapport à la formule correctement affichés sur la fiche contrat
- [ ] **Import Excel** : télécharger le modèle `modele-import-solutions.xlsx`, le remplir, « Choisir un fichier » → tableau rempli
- [ ] Import d'un fichier non `.xlsx` ou mal formé → message d'erreur, rien n'est enregistré
- [ ] Solutions : saisie manuelle d'une ligne, suppression d'une ligne dans la zone du tableau, aide au survol des catégories
- [ ] Une solution avec fin de licence dans moins de 5 mois (servira en partie 8)
- [ ] Statuts du contrat : Brouillon / Actif / Expiré / Résilié

---

## 3. Équipe Aptitude & comptes clients (Super Admin)

- [ ] Créer Manager, Ingénieur (supérieur = Manager), 2ᵉ Manager → email d'invitation reçu
- [ ] Si la messagerie échoue : le lien d'invitation s'affiche à l'écran
- [ ] Le profil « Engineer (restricted) » n'est **pas** proposé (profil en réserve)
- [ ] Le champ « Supérieur hiérarchique » ne propose que des Super Admin / Manager
- [ ] Créer Admin ESN A et Admin ESN B → invitation reçue
- [ ] Chaque compte définit son mot de passe via le lien ; les comptes Aptitude doivent activer la MFA
- [ ] Journal d'audit : « Utilisateur créé », « MFA activée »
- [ ] Désactiver un utilisateur → il ne peut plus se connecter ; le réactiver

---

## 4. Admin ESN A

- [ ] Connexion (pas de MFA obligatoire pour un client)
- [ ] Contrats : voit A-GOLD et A-SILVER, **pas** le contrat B
- [ ] Crée Client User A1, Client Viewer A1, Client User A2
- [ ] Ne peut **pas** créer de compte dans B1 ni dans une organisation hors de son ESN
- [ ] Ne peut pas attribuer un profil Aptitude
- [ ] Limiter un utilisateur à certains contrats → il ne voit que ceux-là
- [ ] N'a pas accès à `/gestion/` (administration)

---

## 5. Tickets — côté client

Connecté en **Client User A1** :
- [ ] Contrats : ne voit que A-GOLD
- [ ] Nouveau ticket : contrat, solution(s) du contrat, titre, description, priorité
- [ ] Seules P4 et P3 proposées ; P1/P2 refusées
- [ ] Pièces jointes : PDF/PNG acceptés ; `.exe` refusé ; fichier > 10 Mo refusé
- [ ] Ticket créé avec référence de l'année, échéances SLA (prise en charge / résolution) affichées
- [ ] Emails : accusé de réception au client + alerte à l'équipe Aptitude
- [ ] Peut escalader P4 → P3 lui-même, pas au-delà

Contrôles d'accès :
- [ ] **Client Viewer A1** voit le ticket mais **ne peut pas** en créer ni commenter
- [ ] **Client User A2** ne voit pas le ticket de A1
- [ ] **Client User B1** / Admin ESN B ne voit pas le ticket (même en tapant l'URL `/tickets/<réf>/`)
- [ ] **Admin ESN A** voit les tickets de A1 et de A2
- [ ] Couverture 8x5 : ticket client sur A-SILVER le soir / week-end / jour férié → refus avec prochaine ouverture indiquée
- [ ] Même chose côté Aptitude → ticket accepté mais marqué « créé hors couverture »

---

## 6. Tickets — côté Aptitude (Ingénieur)

- [ ] File des tickets triée par urgence SLA ; filtres fonctionnels
- [ ] S'assigner le ticket → email à l'ingénieur assigné ; événement « Assignation »
- [ ] Statut Nouveau → Pris en charge → En cours (prise en charge horodatée, retard de réponse calculé)
- [ ] **Répondre au client** → visible par le client + email au client
- [ ] **Note interne** → invisible pour le client, **aucun** email
- [ ] **En attente client** → SLA en pause ; retour En cours → SLA reprend (échéance décalée)
- [ ] Le client répond → email à l'ingénieur
- [ ] Escalade P2 : justification < 10 caractères refusée ; ≥ 10 OK → email au client, échéances recalculées
- [ ] Escalade P1 : statut passe automatiquement « En attente de prérequis », échéance de résolution vidée
- [ ] Redescendre de P1 → retour « En cours »
- [ ] Transitions interdites non proposées (ex. depuis Clos)
- [ ] **Résolu** → email au client ; le client peut **réouvrir** (→ En cours)
- [ ] Re-résoudre, puis `python manage.py close_resolved_tickets` (après > 1 jour) → **Clos** automatiquement
- [ ] Ticket clos : plus aucune action possible (statut, priorité, commentaire)
- [ ] Chronologie complète : création, statuts, priorités, assignations, événements SLA
- [ ] Téléchargement d'une pièce jointe par un utilisateur autorisé ; refusé pour un client d'une autre ESN
- [ ] Dépassement SLA → indicateur de retard visible

---

## 7. Rapport curatif & validation hiérarchique

- [ ] Ingénieur : Rapports → Curatif → Nouveau → choisir le ticket ; contrat, ESN, client final, SLA, chronologie repris automatiquement
- [ ] Compléter (site, diagnostic, solution, tests…) et enregistrer en brouillon
- [ ] **Soumettre à validation** → email au Manager ; rapport plus modifiable par l'ingénieur
- [ ] L'ingénieur ne peut pas valider son propre rapport
- [ ] Le **2ᵉ Manager** ne peut pas le valider
- [ ] Manager : **Rejeter** avec commentaire → « À corriger », l'ingénieur corrige et resoumet
- [ ] Manager : **Valider** → rapport verrouillé, empreinte SHA-256 renseignée
- [ ] Manager : **Envoyer au client** → email au client
- [ ] Un client ne voit pas le rapport tant qu'il n'est pas envoyé
- [ ] Client (Admin ESN A ou Client User A1) : rapport avec **logo de l'ESN** ; **Imprimer / PDF** correct
- [ ] **Confirmer la réception** → horodatage et nom affichés
- [ ] Client Viewer : peut lire ; vérifier s'il peut confirmer selon la règle attendue
- [ ] Client de l'ESN B : ne voit pas le rapport

---

## 8. Préventif, trimestriel, licences

- [ ] Rapport **préventif** sur A-GOLD : équipements et contrôles types proposés ; résultats + recommandations ; soumettre → valider → envoyer
- [ ] Rapport **trimestriel** : année + trimestre ; chiffres tickets, causes curatifs, recommandations préventifs consolidés automatiquement
- [ ] Références des rapports `CUR`, `PRV`, `TRI` qui s'incrémentent
- [ ] Licences : Administration → Solutions → filtre « Fin de licence » → action **« Notifier l'ESN »** → email reçu
- [ ] `python manage.py notify_license_expiry` → alerte au seuil atteint (5 mois, 3 mois ou 1 mois avant la fin) ; relancée aussitôt → **pas** de doublon
- [ ] Destinataires de l'alerte : client ESN, administrateurs du client final du contrat et managers Aptitude
- [ ] Paramètres des alertes de licence : passer les seuils à « 6, 2 » → aperçu « 2 rappel(s) » ; une saisie invalide est refusée ; « Dernier passage du planificateur » renseigné
- [ ] Service `scheduler` démarré (`docker compose ps scheduler`) ; ses journaux montrent les tâches lancées
- [ ] Un envoi manuel n'empêche pas l'alerte automatique suivante

---

## 9. Transverse

- [ ] Tableau de bord : compteurs cohérents pour chaque profil (Admin, Ingénieur, Manager, Client)
- [ ] Interface en anglais : libellés traduits (tickets, rapports, emails)
- [ ] Mode sombre lisible sur toutes les pages (tickets, rapports, administration)
- [ ] Affichage mobile : menu, liste et détail ticket utilisables
- [ ] PWA : installation possible, page « hors ligne » quand le réseau est coupé
- [ ] URL protégée sans être connecté → redirection vers la connexion
- [ ] Journal d'audit complet : connexions, échecs, créations/modifications d'utilisateurs, MFA, messagerie

---

## 10. Anomalies relevées

| # | Étape | Compte utilisé | Constaté | Attendu | Gravité |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |
