"""Planificateur intégré : lance seul les tâches périodiques, sans cron à configurer.

Démarré par le service « scheduler » de docker-compose (même image que le site) :
    python manage.py run_scheduler

Tâches, vérifiées chaque minute et lancées au plus une fois par heure :
- clôture automatique des tickets résolus depuis plus d'un jour ;
- alertes d'expiration de licence (5, 3 et 1 mois avant), de LICENSE_ALERT_HOUR à 19 h
  pour ne pas envoyer d'email la nuit.

Les deux tâches sont sans risque de doublon : une alerte déjà envoyée à un seuil ne repart
pas, et un email en échec est retenté à l'heure suivante. Une erreur dans une tâche est
journalisée sans arrêter le planificateur.
"""
import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

log = logging.getLogger("scheduler")

LAST_ALERT_HOUR = 19


def _close_tickets():
    from tickets.services import auto_close
    return f"{auto_close()} ticket(s) clôturé(s)"


def _license_alerts():
    from contracts.notifications import notify_expiring_licenses
    emails, solutions = notify_expiring_licenses()
    return f"{emails} email(s) d'alerte pour {solutions} licence(s)"


def jobs_due(now, last_runs):
    """Tâches à lancer à `now` (heure locale) : chacune au plus une fois par heure."""
    slot = now.strftime("%Y-%m-%d %H")
    first_hour = getattr(settings, "LICENSE_ALERT_HOUR", 7)
    due = []
    if last_runs.get("close_tickets") != slot:
        due.append(("close_tickets", _close_tickets))
    if first_hour <= now.hour <= LAST_ALERT_HOUR and last_runs.get("license_alerts") != slot:
        due.append(("license_alerts", _license_alerts))
    return slot, due


def run_due_jobs(now, last_runs):
    """Lance les tâches dues ; une tâche en erreur est retentée à la minute suivante."""
    slot, due = jobs_due(now, last_runs)
    for name, job in due:
        close_old_connections()
        try:
            result = job()
        except Exception:
            log.exception("Tâche %s en échec", name)
            continue
        last_runs[name] = slot
        log.info("%s : %s", name, result)
    return [name for name, _job in due]


class Command(BaseCommand):
    help = "Planificateur intégré : clôture des tickets et alertes de licence, sans cron."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Lance les tâches dues une fois puis s'arrête.")
        parser.add_argument("--interval", type=int, default=60, help="Secondes entre deux vérifications.")

    def handle(self, *args, **options):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
        last_runs = {}
        self.stdout.write("Planificateur démarré.")
        while True:
            try:
                run_due_jobs(timezone.localtime(), last_runs)
            except Exception:  # base de données indisponible au démarrage, etc.
                log.exception("Vérification impossible, nouvel essai dans %s s", options["interval"])
            if options["once"]:
                return
            time.sleep(options["interval"])
