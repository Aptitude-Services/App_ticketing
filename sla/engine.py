"""Moteur de temps SLA.

- 24x7 : temps calendaire.
- 8x5 : uniquement les plages ouvrées du SLA (8h–17h, lundi–vendredi par défaut),
  hors jours fériés.

Toutes les fonctions prennent et rendent des datetimes « aware » ; les calculs
se font dans le fuseau du site (Africa/Abidjan).
"""
import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from .models import SLA, Holiday

MAX_DAYS = 3 * 366  # garde-fou contre une configuration sans aucun jour ouvré


def _tz():
    return ZoneInfo(settings.TIME_ZONE)


def _local(dt):
    if timezone.is_naive(dt):
        raise ValueError("Datetime « aware » attendu.")
    return dt.astimezone(_tz())


def holiday_set(start: datetime.date, end: datetime.date) -> set:
    return set(Holiday.objects.filter(date__gte=start, date__lte=end).values_list("date", flat=True))


class _Calendar:
    def __init__(self, sla: SLA, around: datetime.date):
        self.sla = sla
        self.days = sla.weekdays()
        self.holidays = holiday_set(around - datetime.timedelta(days=MAX_DAYS), around + datetime.timedelta(days=MAX_DAYS))

    def is_working_day(self, d: datetime.date) -> bool:
        return d.weekday() in self.days and d not in self.holidays

    def window(self, d: datetime.date):
        tz = _tz()
        return (datetime.datetime.combine(d, self.sla.day_start, tz),
                datetime.datetime.combine(d, self.sla.day_end, tz))


def is_covered(sla: SLA, when: datetime.datetime) -> bool:
    """Vrai si l'instant est dans la couverture du SLA."""
    if sla.is_24x7:
        return True
    local = _local(when)
    cal = _Calendar(sla, local.date())
    if not cal.is_working_day(local.date()):
        return False
    start, end = cal.window(local.date())
    return start <= local < end


def add_minutes(sla: SLA, start: datetime.datetime, minutes: int) -> datetime.datetime:
    """Échéance : `start` + `minutes` de temps couvert par le SLA."""
    if minutes < 0:
        raise ValueError("Durée négative.")
    if sla.is_24x7:
        return start + datetime.timedelta(minutes=minutes)

    cursor = _local(start)
    remaining = datetime.timedelta(minutes=minutes)
    cal = _Calendar(sla, cursor.date())
    day = cursor.date()
    for _i in range(MAX_DAYS):
        if cal.is_working_day(day):
            open_, close = cal.window(day)
            begin = max(cursor, open_)
            if begin < close:
                available = close - begin
                if remaining <= available:
                    return begin + remaining
                remaining -= available
        day += datetime.timedelta(days=1)
        cursor = datetime.datetime.combine(day, datetime.time.min, _tz())
    raise ValueError("Aucun jour ouvré trouvé : vérifiez la configuration du SLA.")


def elapsed_minutes(sla: SLA, start: datetime.datetime, end: datetime.datetime) -> int:
    """Minutes de temps couvert entre deux instants (0 si `end` précède `start`)."""
    if end <= start:
        return 0
    if sla.is_24x7:
        return int((end - start).total_seconds() // 60)

    a, b = _local(start), _local(end)
    cal = _Calendar(sla, a.date())
    total = datetime.timedelta()
    day = a.date()
    while day <= b.date():
        if cal.is_working_day(day):
            open_, close = cal.window(day)
            lo, hi = max(a, open_), min(b, close)
            if hi > lo:
                total += hi - lo
        day += datetime.timedelta(days=1)
    return int(total.total_seconds() // 60)


def next_coverage_start(sla: SLA, when: datetime.datetime) -> datetime.datetime:
    """Prochain instant couvert (lui-même s'il l'est déjà). Sert à afficher les horaires."""
    if sla.is_24x7:
        return when
    cursor = _local(when)
    cal = _Calendar(sla, cursor.date())
    day = cursor.date()
    for _i in range(MAX_DAYS):
        if cal.is_working_day(day):
            open_, close = cal.window(day)
            if cursor < close:
                return max(cursor, open_)
        day += datetime.timedelta(days=1)
        cursor = datetime.datetime.combine(day, datetime.time.min, _tz())
    raise ValueError("Aucun jour ouvré trouvé : vérifiez la configuration du SLA.")
