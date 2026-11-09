"""Secteur d'activité des organisations : obligatoire pour un client, interdit pour Aptitude."""
import pytest
from django.contrib.admin.sites import site
from django.core.exceptions import ValidationError

from accounts.models import Organisation

pytestmark = pytest.mark.django_db

BANK = Organisation.ActivitySector.BANK


def test_client_requires_activity_sector():
    org = Organisation(name="Banque X", kind=Organisation.Kind.CLIENT)
    with pytest.raises(ValidationError) as exc:
        org.full_clean()
    assert "activity_sector" in exc.value.message_dict


def test_client_with_sector_is_valid():
    org = Organisation(name="Banque X", kind=Organisation.Kind.CLIENT, activity_sector=BANK)
    org.full_clean()
    assert org.get_activity_sector_display() == "Banque"


def test_end_client_requires_activity_sector():
    org = Organisation(name="Filiale", kind=Organisation.Kind.END_CLIENT)
    with pytest.raises(ValidationError) as exc:
        org.full_clean()
    assert "activity_sector" in exc.value.message_dict


def test_aptitude_has_no_activity_sector():
    org = Organisation(name="Aptitude Services", kind=Organisation.Kind.APTITUDE, activity_sector=BANK)
    with pytest.raises(ValidationError) as exc:
        org.full_clean()
    assert "activity_sector" in exc.value.message_dict
    org.activity_sector = ""
    org.full_clean()


def test_admin_form_asks_for_activity_sector(rf, admin_user):
    request = rf.get("/")
    request.user = admin_user
    form_class = site._registry[Organisation].get_form(request)
    data = {"name": "PME Y", "kind": "client", "activity_sector": "", "email_domains": "", "is_active": "on"}
    form = form_class(data)
    assert not form.is_valid()
    assert "activity_sector" in form.errors

    form = form_class({**data, "activity_sector": "bank"})
    assert form.is_valid(), form.errors
    assert form.save().activity_sector == "bank"


def test_admin_lists_and_filters_by_sector():
    admin = site._registry[Organisation]
    assert "sector" in admin.list_display
    assert "activity_sector" in admin.list_filter


def test_esn_kind_is_labelled_client_esn():
    assert dict(Organisation.Kind.choices)["client"] == "Client ESN"
