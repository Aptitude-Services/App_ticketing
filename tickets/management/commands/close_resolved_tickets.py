"""Clôt les tickets résolus depuis plus d'un jour sans réouverture.

Lancée automatiquement toutes les heures par le planificateur intégré (service « scheduler »,
commande run_scheduler). Lancement manuel possible :
    docker compose exec -T web python manage.py close_resolved_tickets
"""
from django.core.management.base import BaseCommand

from tickets.services import auto_close


class Command(BaseCommand):
    help = "Clôture automatique des tickets résolus depuis plus d'un jour."

    def handle(self, *args, **options):
        n = auto_close()
        self.stdout.write(self.style.SUCCESS(f"{n} ticket(s) clôturé(s)."))
