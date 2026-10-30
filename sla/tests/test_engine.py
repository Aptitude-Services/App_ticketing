"""Moteur SLA : heures ouvrées 8x5, temps calendaire 24x7, jours fériés."""
import datetime
from zoneinfo import ZoneInfo

import pytest

from sla import engine
from sla.holidays import easter, holidays_for
from sla.models import SLA, Holiday

pytestmark = pytest.mark.django_db
TZ = ZoneInfo("Africa/Abidjan")


def at(y, m, d, h=0, mi=0):
    return datetime.datetime(y, m, d, h, mi, tzinfo=TZ)


@pytest.fixture
def s85():
    return SLA.objects.get(name="SLA 8x5")


@pytest.fixture
def s247():
    return SLA.objects.get(name="SLA 24x7")


# --- Données par défaut ---------------------------------------------------------------

def test_default_grid_is_loaded(s85, s247):
    for sla in (s85, s247):
        grid = {t.priority: (t.response_minutes // 60, t.resolution_minutes // 60) for t in sla.targets.all()}
        assert grid == {1: (1, 8), 2: (1, 12), 3: (4, 24), 4: (8, 48)}


def test_easter_dates():
    assert easter(2026) == datetime.date(2026, 4, 5)
    assert easter(2027) == datetime.date(2027, 3, 28)


def test_holidays_2026_match_official_dates():
    dates = {d for d, _n, _k in holidays_for(2026)}
    for expected in ["2026-04-06", "2026-05-14", "2026-05-25", "2026-03-16", "2026-03-20", "2026-05-27", "2026-08-25"]:
        assert datetime.date.fromisoformat(expected) in dates


def test_sunday_holiday_gets_substitute_monday():
    # 1er mai 2033 tombe un dimanche
    dates = {d: n for d, n, _k in holidays_for(2033)}
    assert datetime.date(2033, 5, 2) in dates


# --- 24x7 -------------------------------------------------------------------------------

def test_24x7_is_calendar_time(s247):
    start = at(2026, 12, 24, 22, 0)  # veille de Noël, 22h
    assert engine.add_minutes(s247, start, 8 * 60) == at(2026, 12, 25, 6, 0)
    assert engine.is_covered(s247, at(2026, 11, 1, 3, 0))


# --- 8x5 --------------------------------------------------------------------------------

def test_8x5_within_same_day(s85):
    # mardi 3 nov. 2026, 9h + 4 h -> 13h
    assert engine.add_minutes(s85, at(2026, 11, 3, 9), 4 * 60) == at(2026, 11, 3, 13)


def test_8x5_rolls_to_next_morning(s85):
    # mardi 15h + 4 h : 2 h mardi (jusqu'à 17h) + 2 h mercredi -> mercredi 10h
    assert engine.add_minutes(s85, at(2026, 11, 3, 15), 4 * 60) == at(2026, 11, 4, 10)


def test_8x5_skips_weekend(s85):
    # vendredi 6 nov. 16h + 2 h -> lundi 9 nov. 9h
    assert engine.add_minutes(s85, at(2026, 11, 6, 16), 2 * 60) == at(2026, 11, 9, 9)


def test_8x5_start_outside_hours_begins_next_opening(s85):
    # samedi 22h + 1 h -> lundi 9h
    assert engine.add_minutes(s85, at(2026, 11, 7, 22), 60) == at(2026, 11, 9, 9)


def test_8x5_skips_holiday(s85):
    # dimanche 15 nov. 2026 (Paix) ne change rien ; on ajoute un férié le lundi 16 pour le test
    Holiday.objects.create(date=datetime.date(2026, 11, 16), name="Test", kind="announced")
    # vendredi 13 nov. 16h + 2 h -> 1 h vendredi, lundi férié, mardi 9h
    assert engine.add_minutes(s85, at(2026, 11, 13, 16), 2 * 60) == at(2026, 11, 17, 9)


def test_8x5_p4_resolution_spans_more_than_five_days(s85):
    # P4 : 48 h ouvrées depuis lundi 2 nov. 8h (Toussaint le dimanche 1er, sans report)
    # 9 h/jour -> 5 jours pleins = 45 h, + 3 h le lundi suivant -> lundi 9 nov. 11h
    assert engine.add_minutes(s85, at(2026, 11, 2, 8), 48 * 60) == at(2026, 11, 9, 11)


def test_8x5_coverage(s85):
    assert engine.is_covered(s85, at(2026, 11, 3, 8, 0))
    assert not engine.is_covered(s85, at(2026, 11, 3, 17, 0))
    assert not engine.is_covered(s85, at(2026, 11, 3, 7, 59))
    assert not engine.is_covered(s85, at(2026, 11, 7, 10, 0))      # samedi
    assert not engine.is_covered(s85, at(2026, 12, 25, 10, 0))     # Noël


def test_8x5_elapsed_minutes(s85):
    # vendredi 16h -> lundi 10h = 1 h + 2 h
    assert engine.elapsed_minutes(s85, at(2026, 11, 6, 16), at(2026, 11, 9, 10)) == 180
    assert engine.elapsed_minutes(s85, at(2026, 11, 9, 10), at(2026, 11, 6, 16)) == 0


def test_elapsed_and_add_are_consistent(s85):
    start = at(2026, 11, 4, 11, 17)
    for minutes in (0, 1, 59, 540, 541, 2880, 5000):
        end = engine.add_minutes(s85, start, minutes)
        assert engine.elapsed_minutes(s85, start, end) == minutes


def test_next_coverage_start(s85, s247):
    assert engine.next_coverage_start(s85, at(2026, 11, 7, 12)) == at(2026, 11, 9, 8)
    assert engine.next_coverage_start(s85, at(2026, 11, 3, 10)) == at(2026, 11, 3, 10)
    assert engine.next_coverage_start(s247, at(2026, 11, 7, 12)) == at(2026, 11, 7, 12)


def test_naive_datetime_is_refused(s85):
    with pytest.raises(ValueError):
        engine.add_minutes(s85, datetime.datetime(2026, 11, 3, 9), 60)
