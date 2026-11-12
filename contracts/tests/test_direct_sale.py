"""Vente directe : Aptitude, opératrice de la plateforme, vend aussi à ses propres clients finaux.

Règles métier :
- le vendeur d'un contrat est une ESN (vente indirecte) ou Aptitude (vente directe) ;
- un même client final peut avoir des contrats directs et des contrats via plusieurs ESN ;
- chacun ne voit que les contrats dont il est partie ;
- l'équipe Aptitude gère les comptes des clients finaux.
"""
import datetime
import importlib

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from accounts.models import Organisation, Profile, User
from accounts.permissions import manageable_organisations, manageable_users, visible_contracts
from contracts.models import Contract, ContractType

pytestmark = pytest.mark.django_db
BANK = Organisation.ActivitySector.BANK


def _contract(vendor, end, ref):
    c = Contract.objects.create(reference=ref, title=ref, client=vendor, start_date=datetime.date(2026, 1, 1),
                                contract_type=ContractType.objects.get(name="Standard 24x7"))
    c.end_clients.add(end)
    return c


def _user(email, org, profile):
    return User.objects.create_user(email, "Motdepasse-tres-long-1", organisation=org, profile=profile)


@pytest.fixture
def world():
    apt = Organisation.objects.create(name="Aptitude Services", kind=Organisation.Kind.CLIENT, is_operator=True)
    esn = Organisation.objects.create(name="ESN A", kind=Organisation.Kind.CLIENT)
    end = Organisation.objects.create(name="Banque Finale", kind=Organisation.Kind.END_CLIENT, activity_sector=BANK)
    apt.end_clients.add(end)
    esn.end_clients.add(end)
    return {
        "apt": apt, "esn": esn, "end": end,
        "direct": _contract(apt, end, "DIRECT-1"),
        "via_esn": _contract(esn, end, "ESN-1"),
        "manager": _user("manager@aptitudes.net", apt, Profile.APTITUDE_MANAGER),
        "esn_admin": _user("admin@esn-a.ci", esn, Profile.CLIENT_ADMIN),
        "end_user": _user("user@banque.ci", end, Profile.CLIENT_RW),
    }


def test_aptitude_is_a_vendor_and_the_operator(world):
    apt = world["apt"]
    assert apt.is_vendor and apt.is_operator and apt.is_aptitude
    assert not apt.is_partner_esn
    assert world["esn"].is_partner_esn and not world["esn"].is_aptitude


def test_direct_contract_is_valid_and_flagged(world):
    world["direct"].full_clean()
    assert world["direct"].is_direct
    assert not world["via_esn"].is_direct


def test_contract_vendor_cannot_be_an_end_client(world):
    c = Contract(reference="X", title="X", client=world["end"], start_date=datetime.date(2026, 1, 1),
                 contract_type=ContractType.objects.get(name="Standard 24x7"))
    with pytest.raises(ValidationError) as exc:
        c.full_clean()
    assert "client" in exc.value.message_dict


def test_esn_never_sees_aptitude_direct_contract(world):
    """Client final partagé : l'ESN ne voit que ses propres contrats."""
    assert set(visible_contracts(world["esn_admin"])) == {world["via_esn"]}


def test_end_client_sees_direct_and_esn_contracts(world):
    assert set(visible_contracts(world["end_user"])) == {world["direct"], world["via_esn"]}


def test_aptitude_team_manages_end_client_accounts(world):
    """Vente directe : l'équipe Aptitude gère les comptes du client final."""
    assert world["end_user"] in manageable_users(world["manager"])
    assert world["end"] in manageable_organisations(world["manager"])
    # Mais un Manager ne gère pas l'équipe interne.
    assert world["manager"] not in manageable_users(world["manager"])
    assert world["apt"] not in manageable_organisations(world["manager"])


def test_operator_users_keep_internal_profiles(world):
    with pytest.raises(ValidationError):
        User(email="x@aptitudes.net", organisation=world["apt"], profile=Profile.CLIENT_ADMIN).full_clean(
            exclude=["password"])


def test_operator_must_be_a_vendor(world):
    world["apt"].kind = Organisation.Kind.END_CLIENT
    world["apt"].activity_sector = BANK
    with pytest.raises(ValidationError) as exc:
        world["apt"].full_clean()
    assert "kind" in exc.value.message_dict


def test_only_one_operator(world):
    with pytest.raises(IntegrityError), transaction.atomic():
        Organisation.objects.create(name="Autre opérateur", kind=Organisation.Kind.CLIENT, is_operator=True)


def test_superuser_joins_existing_operator(world):
    admin = User.objects.create_superuser("root@aptitudes.net", "Motdepasse-tres-long-1")
    assert admin.organisation == world["apt"]


def test_migration_turns_old_aptitude_kind_into_operator():
    migration = importlib.import_module("accounts.migrations.0014_organisation_is_operator")
    old = Organisation.objects.create(name="Aptitude Services", kind="aptitude")
    migration.aptitude_to_operator(apps, None)
    old.refresh_from_db()
    assert old.kind == Organisation.Kind.CLIENT and old.is_operator
    migration.operator_to_aptitude(apps, None)
    old.refresh_from_db()
    assert old.kind == "aptitude" and not old.is_operator


def test_license_alert_for_direct_sale_does_not_mail_the_internal_team(world):
    from contracts.notifications import esn_recipients
    assert esn_recipients(world["apt"]) == []
    assert esn_recipients(world["esn"]) == ["admin@esn-a.ci"]
