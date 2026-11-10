# Plan de démonstration — Aptitude Support

Parcours complet, dans l'ordre où les éléments doivent être créés. Chaque étape
s'appuie sur la précédente. Ce même parcours est vérifié automatiquement par
`core/tests/test_parcours_complet.py`.

## Les acteurs

| Rôle | Profil | Organisation | Ce qu'il fait |
|---|---|---|---|
| Super Admin | Super Admin | Aptitude Services | Met tout en place : ESN, clients finaux, contrats, comptes Aptitude |
| Supérieur | Manager | Aptitude Services | Valide les rapports de ses ingénieurs, les envoie au client |
| Ingénieur | Engineer | Aptitude Services | Traite les tickets, rédige les rapports |
| Admin ESN | Client Admin | l'ESN | Crée les comptes de ses clients finaux, suit tickets et rapports |
| Utilisateur client | Client User | le client final | Ouvre et suit ses tickets, lit et confirme les rapports |
| Lecteur client | Client Viewer | le client final | Consulte seulement |

Les comptes Aptitude doivent activer la double authentification (application
d'authentification sur téléphone) à leur première connexion.

## Étape 1 — Super Admin : le référentiel

1. **Administration → Organisations → Ajouter** : l'ESN.
   Type « Client ESN », **logo** (PNG/SVG), domaines email. Pas de secteur d'activité.
2. Sur la fiche de l'ESN, bouton **« Nouveau client final »** : nom, **secteur d'activité**, domaines.
3. **Administration → Contrats → Ajouter** :
   intitulé, **Client ESN**, puis **Client final** dans la liste déroulante (seuls ceux de l'ESN),
   formule (ex. GOLD, couverte 24x7), dates.
   Solutions : **Choisir un fichier** (modèle Excel) remplit le tableau, ou saisie ligne par ligne.
   Enregistrer : la référence `ESN-CLIENT-ANNÉE-NNN` est attribuée.

## Étape 2 — Super Admin : l'équipe Aptitude

**Équipe interne → Nouvel utilisateur** :
1. le **Manager** (profil Manager) ;
2. l'**Ingénieur** (profil Engineer), avec **Supérieur hiérarchique = le Manager**.

Chaque personne reçoit un email d'invitation pour définir son mot de passe.
Si la messagerie ne fonctionne pas, le lien s'affiche à l'écran : le transmettre.

## Étape 3 — Super Admin : l'admin de l'ESN

**Clients → Nouvel utilisateur** : organisation = l'ESN, profil **Client Admin**.

## Étape 4 — Admin ESN : les comptes du client final

Se connecter avec l'admin de l'ESN. **Utilisateurs → Nouvel utilisateur** :
organisation = **le client final**, profil Client User (puis un Client Viewer).
À montrer : il ne peut pas créer de compte chez un client qui n'est pas le sien.

## Étape 5 — Utilisateur client : ouvrir un ticket

1. **Contrats** : il ne voit que le contrat qui le concerne.
2. **Nouveau ticket** : contrat, solution concernée, objet, description, priorité P3 ou P4
   (P1/P2 sont réservées à l'escalade par Aptitude).
3. Le ticket apparaît avec ses échéances SLA.

À montrer : le Client Viewer voit le ticket mais ne peut pas en créer ; un client
d'une autre ESN ne le voit pas.

## Étape 6 — Ingénieur : traiter le ticket

1. **Tickets** : le ticket est dans la file. **S'assigner**, statut **En cours**.
2. **Répondre au client** (message visible) et ajouter une **note interne** (invisible du client).
3. **Escalader** la priorité si besoin (P2 avec justification).
4. Le client voit la réponse et la nouvelle priorité, **pas la note interne**, et peut répondre.
5. Statut **Résolu**.

Emails envoyés au fil de l'eau (à montrer dans les boîtes de réception) :
accusé de réception au client et alerte à l'équipe Aptitude à l'ouverture ;
email à l'ingénieur quand on lui assigne le ticket ; au client à chaque étape
(prise en charge, en cours, attente, résolu, clos), à chaque réponse et à chaque
changement de priorité ; à l'ingénieur quand le client répond. Une note interne
ne déclenche jamais d'email.

## Étape 7 — Rapport curatif et validation hiérarchique

1. Ingénieur : **Rapports → Curatif → Nouveau rapport**, choisir le ticket.
   Contrat, ESN, client final, SLA, chronologie : repris automatiquement.
   Compléter (site, diagnostic, solution, tests…), **Soumettre à validation**.
2. Le Manager reçoit un email. À montrer : l'ingénieur ne peut pas valider son
   propre rapport ; un autre manager non plus.
3. Manager : ouvrir le rapport, **Valider le rapport** (il est verrouillé), puis **Envoyer au client**.
4. Client (admin ESN ou utilisateur client) : **Rapports** → le rapport, avec le
   **logo de l'ESN** ; **Imprimer / PDF** ; **Confirmer la réception**.

## Étape 8 — Préventif, trimestriel, licences

1. **Rapport préventif** sur le contrat : équipements et contrôles types proposés ;
   renseigner les résultats et recommandations ; soumettre ; faire valider.
2. **Rapport trimestriel** du trimestre : chiffres des tickets, causes des rapports
   curatifs et recommandations des préventifs, consolidés automatiquement.
3. **Licences** : une solution dont la licence expire sous 60 jours →
   Administration → Solutions → filtre « Fin de licence » → action **« Notifier l'ESN »**.
   En production, la tâche quotidienne `notify_license_expiry` le fait seule.
