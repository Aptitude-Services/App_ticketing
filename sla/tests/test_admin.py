"""Formulaire SLA de l'administration : jours ouvrés en cases à cocher, masqués en 24x7."""
import pytest

from sla.admin import SLAAdmin, SLAForm
from sla.models import SLA

pytestmark = pytest.mark.django_db

BASE = {"name": "SLA test", "day_start": "08:00", "day_end": "17:00"}


def test_checked_days_are_stored_in_engine_format():
    form = SLAForm({**BASE, "coverage": "8x5", "working_days": ["0", "2", "4"]})
    assert form.is_valid(), form.errors
    sla = form.save()
    assert sla.working_days == "0,2,4"
    assert sla.weekdays() == {0, 2, 4}


def test_8x5_requires_at_least_one_day():
    form = SLAForm({**BASE, "coverage": "8x5"})
    assert not form.is_valid()
    assert "working_days" in form.errors


def test_8x5_accepts_at_most_five_days():
    form = SLAForm({**BASE, "coverage": "8x5", "working_days": ["0", "1", "2", "3", "4", "5"]})
    assert not form.is_valid()
    assert "working_days" in form.errors
    form = SLAForm({**BASE, "coverage": "8x5", "working_days": ["1", "2", "3", "4", "5"]})
    assert form.is_valid(), form.errors


def test_24x7_needs_no_working_days():
    form = SLAForm({**BASE, "coverage": "24x7"})
    assert form.is_valid(), form.errors
    assert form.save().working_days == "0,1,2,3,4"


def test_existing_sla_shows_its_days_checked():
    sla = SLA.objects.get(name="SLA 8x5")
    assert SLAForm(instance=sla).initial["working_days"] == ["0", "1", "2", "3", "4"]


def test_list_shows_day_names():
    admin = SLAAdmin(SLA, None)
    assert admin.jours(SLA.objects.get(name="SLA 8x5")) == "Lun, Mar, Mer, Jeu, Ven"
    assert str(admin.jours(SLA.objects.get(name="SLA 24x7"))) == "7 j / 7"


def test_targets_show_reply_delay_first():
    from sla.admin import SLATargetInline
    assert SLATargetInline.fields[:2] == ("priority", "reply_minutes")


def test_reply_delay_is_optional_but_bounded():
    from django.core.exceptions import ValidationError
    from sla.models import SLATarget
    target = SLA.objects.get(name="SLA 8x5").targets.get(priority=4)
    target.full_clean()  # vide : accepté
    target.reply_minutes = target.resolution_minutes + 1
    with pytest.raises(ValidationError):
        target.full_clean()
    assert SLATarget._meta.get_field("reply_minutes").verbose_name == "délai de réponse (minutes)"
