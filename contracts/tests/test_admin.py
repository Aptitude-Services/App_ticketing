"""Création d'un contrat dans l'administration avec des accès contrats dans le même écran."""
import datetime

import pytest
from django.contrib.admin.sites import site

from accounts.models import Organisation, Profile, User
from contracts.models import Contract, ContractAccess, ContractType

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(rf):
    apt = Organisation.objects.create(name="Aptitude Services", kind=Organisation.Kind.APTITUDE)
    client = Organisation.objects.create(name="HUDSON", client_type=Organisation.ClientType.SME)
    other = Organisation.objects.create(name="Autre", client_type=Organisation.ClientType.SME)
    admin_user = User.objects.create_superuser("admin@aptitudes.net", "x" * 12)
    users = {
        "admin": admin_user,
        "engineer": User.objects.create_user("ing@aptitudes.net", organisation=apt, profile=Profile.TECH_ASSIGNED),
        "client": User.objects.create_user("rw@hudson.ci", organisation=client, profile=Profile.CLIENT_RW),
        "stranger": User.objects.create_user("rw@autre.ci", organisation=other, profile=Profile.CLIENT_RW),
    }
    request = rf.post("/")
    request.user = admin_user
    return client, users, request


def _post(client, user):
    """Données du formulaire d'ajout de contrat, avec une ligne d'accès pour `user`."""
    return {
        "reference": "HUD-001", "title": "Réseau HUDSON", "client": client.pk,
        "contract_type": ContractType.objects.get(name="Standard 8x5").pk,
        "status": Contract.Status.ACTIVE, "start_date": datetime.date(2026, 11, 1),
        "solutions-TOTAL_FORMS": "0", "solutions-INITIAL_FORMS": "0",
        "accesses-TOTAL_FORMS": "1", "accesses-INITIAL_FORMS": "0",
        "accesses-0-user": user.pk,
    }


def _validate(request, data):
    """Reproduit la validation de l'écran d'ajout : contrat + lignes d'accès."""
    admin = site._registry[Contract]
    form = admin.get_form(request)(data)
    assert form.is_valid(), form.errors
    contract = form.save(commit=False)
    formset_class = next(f for f in admin.get_formsets_with_inlines(request) if f[1].model is ContractAccess)[0]
    formset = formset_class(data, instance=contract, prefix="accesses")
    return contract, formset


@pytest.mark.parametrize("who", ["admin", "stranger"])
def test_forbidden_access_is_a_form_error_not_a_crash(setup, who):
    client, users, request = setup
    contract, formset = _validate(request, _post(client, users[who]))
    assert not formset.is_valid()
    assert formset.errors[0] or formset.non_form_errors()


@pytest.mark.parametrize("who", ["engineer", "client"])
def test_allowed_access_is_saved_with_the_new_contract(setup, who):
    client, users, request = setup
    contract, formset = _validate(request, _post(client, users[who]))
    assert formset.is_valid(), formset.errors
    contract.save()
    formset.instance = contract
    formset.save()
    assert ContractAccess.objects.filter(contract=contract, user=users[who]).exists()
