"""Charge les jours fériés ivoiriens d'une ou plusieurs années.

    python manage.py load_holidays 2026 2027

Les fêtes fixes et celles liées à Pâques sont calculées ; les fêtes musulmanes
ne sont chargées que pour les années dont les dates officielles sont connues.
Les autres sont à saisir dans l'administration dès le communiqué du gouvernement.
"""
from django.core.management.base import BaseCommand

from sla.holidays import ANNOUNCED, holidays_for
from sla.models import Holiday


class Command(BaseCommand):
    help = "Charge les jours fériés ivoiriens."

    def add_arguments(self, parser):
        parser.add_argument("years", nargs="+", type=int)

    def handle(self, *args, years, **options):
        for year in years:
            created = 0
            for date, name, kind in holidays_for(year):
                _obj, new = Holiday.objects.get_or_create(date=date, defaults={"name": name, "kind": kind})
                created += new
            msg = f"{year} : {created} jour(s) férié(s) ajouté(s)."
            if year not in ANNOUNCED:
                msg += " Fêtes musulmanes à saisir à leur annonce officielle."
            self.stdout.write(self.style.SUCCESS(msg))
