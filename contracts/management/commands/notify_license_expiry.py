from django.core.management.base import BaseCommand

from contracts.notifications import notify_expiring_licenses


class Command(BaseCommand):
    help = ("Prévient le client ESN, le client final et les managers des licences qui expirent "
            "(5 mois, 3 mois puis 1 mois avant). À planifier une fois par jour.")

    def handle(self, *args, **options):
        emails, solutions = notify_expiring_licenses()
        self.stdout.write(self.style.SUCCESS(f"{emails} email(s) envoyé(s) pour {solutions} licence(s)."))
