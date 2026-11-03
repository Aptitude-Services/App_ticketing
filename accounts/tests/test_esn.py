"""ESN gérant des clients finaux : l'ESN voit ses clients finaux, un client final ne voit que lui-même."""
import datetime

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from accounts.models import Organisation, Profile, User
from accounts.permissions import manageable_organisations, manageable_users, visible_contracts
from contracts.models import Contract, ContractType
from tickets import services as S
from tickets.models import Ticket

pytestmark = pytest.mark.django_db
SME = Organisation.ClientType.SME


@pytest.fixture
def esn():
    Organisation.objects.create(name="Aptitude Services", kind=Organisation.Kind.APTITUDE)
    partner = Organisation.objects.create(name="ESN Partenaire", client_type=SME, manages_end_clients=True)
    end = Organisation.objects.create(name="Client final", client_type=SME, parent=partner)
    other = Organisation.objects.create(name="Autre client", client_type=SME)
    t = ContractType.objects.get(name="Standard 24x7")

    def contract(ref, org):
        return Contract.objects.create(reference=ref, title=ref, client=org, start_date=datetime.date(2026, 1, 1),
                                       contract_type=t)

    def user(email, org, profile):
        return User.objects.create_user(email, "Motdepasse-tres-long-1", organisation=org, profile=profile)

    return {
        "partner": partner, "end": end, "other": other,
        "c_partner": contract("ESN-1", partner), "c_end": contract("FIN-1", end), "c_other": contract("AUT-1", other),
        "esn_admin": user("admin@esn.ci", partner, Profile.CLIENT_ADMIN),
        "esn_user": user("tech@esn.ci", partner, Profile.CLIENT_RW),
        "end_admin": user("admin@final.ci", end, Profile.CLIENT_ADMIN),
        "other_admin": user("admin@autre.ci", other, Profile.CLIENT_ADMIN),
    }


def refs(qs):
    return sorted(qs.values_list("reference", flat=True))


def test_esn_sees_its_end_clients_but_not_others(esn):
    assert refs(visible_contracts(esn["esn_admin"])) == ["ESN-1", "FIN-1"]
    assert refs(visible_contracts(esn["esn_user"])) == ["ESN-1", "FIN-1"]


def test_end_client_sees_only_itself(esn):
    assert refs(visible_contracts(esn["end_admin"])) == ["FIN-1"]
    assert refs(visible_contracts(esn["other_admin"])) == ["AUT-1"]


def test_esn_admin_manages_end_client_accounts(esn):
    emails = sorted(manageable_users(esn["esn_admin"]).values_list("email", flat=True))
    assert emails == ["admin@esn.ci", "admin@final.ci", "tech@esn.ci"]
    assert sorted(o.name for o in manageable_organisations(esn["esn_admin"])) == ["Client final", "ESN Partenaire"]
    assert not manageable_users(esn["end_admin"]).filter(organisation=esn["partner"]).exists()


def test_esn_user_opens_ticket_for_end_client_only(esn):
    t = S.create_ticket(esn["esn_user"], esn["c_end"], "Panne", "Le serveur ne répond plus.")
    assert t.contract == esn["c_end"] and t.requester == esn["esn_user"]
    with pytest.raises(PermissionDenied):
        S.create_ticket(esn["esn_user"], esn["c_other"], "Panne", "Hors périmètre.")
    assert Ticket.objects.count() == 1


def test_parent_must_be_an_esn(esn):
    org = Organisation(name="Mal rattaché", client_type=SME, parent=esn["other"])
    with pytest.raises(ValidationError):
        org.full_clean()
    nested = Organisation(name="ESN imbriquée", client_type=SME, manages_end_clients=True, parent=esn["partner"])
    with pytest.raises(ValidationError):
        nested.full_clean()


def test_esn_with_end_clients_cannot_drop_the_flag(esn):
    esn["partner"].manages_end_clients = False
    with pytest.raises(ValidationError):
        esn["partner"].full_clean()
