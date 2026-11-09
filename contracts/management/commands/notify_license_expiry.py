from django.core.management.base import BaseCommand

from contracts.notifications import notify_expiring_licenses


class Command(BaseCommand):
    help = ("Prévient les ESN des licences qui expirent (60, 30, 15, 7 jours avant, puis le jour même). "
            "À planifier une fois par jour.")

    def handle(self, *args, **options):
        emails, solutions = notify_expiring_licenses()
        self.stdout.write(self.style.SUCCESS(f"{emails} email(s) envoyé(s) pour {solutions} licence(s)."))
