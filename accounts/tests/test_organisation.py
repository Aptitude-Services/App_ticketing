"""Type de client des organisations : obligatoire pour un client, interdit pour Aptitude."""
import pytest
from django.contrib.admin.sites import site
from django.core.exceptions import ValidationError

from accounts.models import Organisation

pytestmark = pytest.mark.django_db


def test_client_requires_client_type():
    org = Organisation(name="Banque X", kind=Organisation.Kind.CLIENT)
    with pytest.raises(ValidationError) as exc:
        org.full_clean()
    assert "client_type" in exc.value.message_dict


def test_client_with_type_is_valid():
    org = Organisation(name="Banque X", kind=Organisation.Kind.CLIENT,
                       client_type=Organisation.ClientType.CRITICAL_INFRA)
    org.full_clean()
    assert org.get_client_type_display() == "Banque, Telco, Infrastructure critique"


def test_aptitude_has_no_client_type():
    org = Organisation(name="Aptitude Services", kind=Organisation.Kind.APTITUDE,
                       client_type=Organisation.ClientType.SME)
    with pytest.raises(ValidationError) as exc:
        org.full_clean()
    assert "client_type" in exc.value.message_dict
    org.client_type = ""
    org.full_clean()


def test_admin_form_asks_for_client_type(rf):
    form_class = site._registry[Organisation].get_form(rf.get("/"))
    data = {"name": "PME Y", "kind": "client", "client_type": "", "email_domains": "", "is_active": "on"}
    form = form_class(data)
    assert not form.is_valid()
    assert "client_type" in form.errors

    form = form_class({**data, "client_type": "structured_sme"})
    assert form.is_valid(), form.errors
    assert form.save().client_type == "structured_sme"


def test_admin_lists_and_filters_by_client_type():
    admin = site._registry[Organisation]
    assert "client_type" in admin.list_display
    assert "client_type" in admin.list_filter
