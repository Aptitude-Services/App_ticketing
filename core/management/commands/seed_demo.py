"""Données de démonstration (développement uniquement).

    python manage.py seed_demo
"""
import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Organisation, Profile, User
from contracts.models import Contract, ContractAccess, ContractType, Solution

PASSWORD = "Demo-Aptitude-2026"


class Command(BaseCommand):
    help = "Crée des organisations, contrats et comptes de démonstration."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Réservé au développement (DJANGO_DEBUG=1).")
        apt, _ = Organisation.objects.get_or_create(name="Aptitude Services", defaults={"kind": "aptitude"})
        a, _ = Organisation.objects.get_or_create(name="Banque Lagune", defaults={"email_domains": "banque-lagune.ci"})
        b, _ = Organisation.objects.get_or_create(name="Clinique Riviera", defaults={"email_domains": "clinique-riviera.ci"})
        d = datetime.date(2026, 1, 1)
        t24 = ContractType.objects.get(name="Standard 24x7")
        t85 = ContractType.objects.get(name="Standard 8x5")
        c1, _ = Contract.objects.get_or_create(reference="BL-2026-01", defaults={"title": "Infogérance réseau", "client": a, "start_date": d, "contract_type": t24})
        c2, _ = Contract.objects.get_or_create(reference="BL-2026-02", defaults={"title": "SOC managé", "client": a, "start_date": d, "contract_type": t24})
        c3, _ = Contract.objects.get_or_create(reference="CR-2026-01", defaults={"title": "Maintenance serveurs", "client": b, "start_date": d, "contract_type": t85})
        solutions = [
            (c1, "network", "Pare-feu périmétrique", "Fortinet", "FortiGate 100F", "Siège, Plateau"),
            (c1, "network", "Cœur de réseau", "Cisco", "Catalyst 9300", "Siège, Plateau"),
            (c2, "security", "SIEM", "Wazuh", "4.9", "Datacenter Aptitude"),
            (c2, "vm", "Collecteur de journaux", "", "Ubuntu 24.04", "Datacenter Aptitude"),
            (c3, "hardware", "Serveur de fichiers", "Dell", "PowerEdge R650", "Clinique, salle serveur"),
            (c3, "software", "Sauvegarde", "Veeam", "12.2", "Clinique, salle serveur"),
        ]
        for contract, cat, name, vendor, version, loc in solutions:
            Solution.objects.get_or_create(contract=contract, name=name, defaults={
                "category": cat, "vendor": vendor, "serial_or_version": version, "location": loc})
        accounts = [
            ("admin@aptitudes.net", "Arnaud", "Kouadio", apt, Profile.APTITUDE_ADMIN, True),
            ("tech@aptitudes.net", "Moussa", "Traoré", apt, Profile.TECH_ALL, True),
            ("admin@banque-lagune.ci", "Aïcha", "Koné", a, Profile.CLIENT_ADMIN, True),
            ("dsi@banque-lagune.ci", "Serge", "N'Guessan", a, Profile.CLIENT_RW, True),
            ("compta@banque-lagune.ci", "Mariam", "Ouattara", a, Profile.CLIENT_RO, False),
            ("admin@clinique-riviera.ci", "Yao", "Kouassi", b, Profile.CLIENT_ADMIN, True),
        ]
        for email, first, last, org, profile, all_contracts in accounts:
            if not User.objects.filter(email=email).exists():
                User.objects.create_user(email, PASSWORD, organisation=org, profile=profile, first_name=first,
                                         last_name=last, all_contracts=all_contracts,
                                         is_superuser=profile == Profile.APTITUDE_ADMIN)
        ContractAccess.objects.get_or_create(user=User.objects.get(email="compta@banque-lagune.ci"), contract=c2)
        self._tickets(c1, c2, c3)
        self.stdout.write(self.style.SUCCESS(f"Démo prête. Mot de passe de tous les comptes : {PASSWORD}"))

    def _tickets(self, c1, c2, c3):
        """Tickets d'exemple dans différents états SLA, datés par rapport à maintenant."""
        from datetime import timedelta as td

        from django.utils import timezone

        from sla import engine
        from tickets import services as S
        from tickets.models import Status, Ticket

        if Ticket.objects.exists():
            return
        now = timezone.now()
        arnaud = User.objects.get(email="admin@aptitudes.net")
        moussa = User.objects.get(email="tech@aptitudes.net")
        aicha = User.objects.get(email="admin@banque-lagune.ci")
        serge = User.objects.get(email="dsi@banque-lagune.ci")
        yao = User.objects.get(email="admin@clinique-riviera.ci")
        sol = {s.name: s for s in Solution.objects.all()}

        def covered_before(contract, when):
            """Dernier instant couvert avant `when` (pour un client sur un contrat 8x5)."""
            sla = contract.sla
            while not engine.is_covered(sla, when):
                when -= td(minutes=30)
            return when

        # 8x5, dépassé
        t0 = covered_before(c3, now - td(days=6))
        t = S.create_ticket(yao, c3, "Sauvegarde nocturne en échec",
                            "Le job de sauvegarde de 2h00 s'arrête à 40 % avec une erreur d'espace disque sur le dépôt.",
                            [sol["Sauvegarde"]], priority=3, now=t0)
        S.assign(arnaud, t, moussa, now=t0 + td(minutes=5))
        S.add_comment(moussa, t, "Nous analysons le dépôt de sauvegarde. Pouvez-vous confirmer la rétention configurée ?", now=t0 + td(minutes=40))
        S.change_status(moussa, t, Status.IN_PROGRESS, now=t0 + td(hours=1))

        # 24x7, P2 à risque
        t0 = now - td(hours=10, minutes=40)
        t = S.create_ticket(aicha, c1, "Pare-feu périmétrique injoignable",
                            "Le FortiGate du siège ne répond plus en HTTPS ni en SSH. Les agences n'ont plus accès aux applications centrales.",
                            [sol["Pare-feu périmétrique"]], priority=3, now=t0)
        S.change_priority(arnaud, t, 2, "Interruption totale des accès des agences, aucun contournement.", now=t0 + td(minutes=10))
        S.assign(arnaud, t, moussa, now=t0 + td(minutes=5))
        S.add_comment(moussa, t, "Prise en charge : un technicien part au siège, accès console en cours.", now=t0 + td(minutes=25))
        S.change_status(moussa, t, Status.IN_PROGRESS, now=t0 + td(minutes=30))
        S.add_comment(moussa, t, "Le cluster HA a basculé deux fois cette nuit. Logs récupérés.", internal=True, now=t0 + td(hours=2))

        # 24x7, P3 à risque
        t0 = now - td(hours=19)
        t = S.create_ticket(serge, c1, "Lenteurs sur le cœur de réseau",
                            "Latence d'environ 300 ms entre le siège et l'agence du Plateau aux heures de pointe.",
                            [sol["Cœur de réseau"]], priority=3, now=t0)
        S.assign(arnaud, t, arnaud, now=t0 + td(minutes=5))
        S.add_comment(arnaud, t, "Nous lançons une capture sur le lien principal pendant le pic de 11h.", now=t0 + td(hours=1))

        # 24x7, P1 en attente de prérequis
        t0 = now - td(hours=2)
        t = S.create_ticket(aicha, c2, "Alerte SIEM : connexions suspectes",
                            "Le SIEM signale des connexions RDP répétées depuis une adresse étrangère vers deux serveurs internes.",
                            [sol["SIEM"]], priority=3, now=t0)
        S.change_priority(arnaud, t, 1, "Exfiltration de données suspectée sur deux serveurs, isolement réseau en cours.", now=t0 + td(minutes=15))
        S.assign(arnaud, t, arnaud, now=t0 + td(minutes=5))
        S.add_comment(arnaud, t, "Nous avons besoin d'une sauvegarde saine des deux serveurs et de la validation du devis d'intervention pour démarrer.", now=t0 + td(minutes=20))

        # 8x5, P4 nouveau, non assigné
        t0 = covered_before(c3, now - td(hours=1))
        S.create_ticket(yao, c3, "Ajout d'un utilisateur au partage RH",
                        "Merci de donner un accès en lecture au dossier RH à la nouvelle assistante de direction.",
                        [sol["Serveur de fichiers"]], now=t0)

        # 24x7, en attente du client
        t0 = now - td(days=2)
        t = S.create_ticket(serge, c1, "VPN lent pour l'agence de Cocody",
                            "Le débit VPN est limité à environ 2 Mb/s depuis la mise à jour du lien opérateur.", priority=3, now=t0)
        S.assign(arnaud, t, moussa, now=t0 + td(minutes=5))
        S.add_comment(moussa, t, "Pouvez-vous nous transmettre le compte rendu d'intervention de l'opérateur ?", now=t0 + td(hours=2))
        S.change_status(moussa, t, Status.WAITING_CLIENT, now=t0 + td(hours=2, minutes=5))

        # Résolu récemment, dans les délais
        t0 = now - td(hours=9)
        t = S.create_ticket(aicha, c2, "Mise à jour du SIEM vers la version 4.9.1",
                            "Intervention planifiée, fenêtre validée avec l'équipe sécurité.", [sol["SIEM"]], now=t0)
        S.assign(arnaud, t, arnaud, now=t0 + td(minutes=5))
        S.change_status(arnaud, t, Status.IN_PROGRESS, now=t0 + td(hours=1))
        S.add_comment(arnaud, t, "Mise à jour terminée, tous les agents remontent correctement.", now=t0 + td(hours=6))
        S.change_status(arnaud, t, Status.RESOLVED, now=t0 + td(hours=6))

        # Clos il y a quelques jours
        t0 = now - td(days=5)
        t = S.create_ticket(serge, c1, "Renouvellement du certificat VPN",
                            "Le certificat du portail VPN expire la semaine prochaine.", now=t0)
        S.change_status(arnaud, t, Status.IN_PROGRESS, now=t0 + td(hours=2))
        S.change_status(arnaud, t, Status.RESOLVED, now=t0 + td(hours=6))
        S.auto_close(now=now)
