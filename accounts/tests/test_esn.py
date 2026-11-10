"""ESN et clients finaux : une ESN voit ses clients finaux, un client final peut
depuis être partagé entre plusieurs ESN qui interviennent sur leurs solutions."""
import datetime

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from accounts.models import Organisation, Profile, User
from accounts.permissions import manageable_organisations, manageable_users, visible_contracts
from contracts.models import Contract, ContractType
from tickets import services as S
from tickets.models import Ticket

pytestmark = pytest.mark.django_db
SECTOR = Organisation.ActivitySector.OTHER


@pytest.fixture
def esn():
    Organisation.objects.create(name="Aptitude Services", kind=Organisation.Kind.APTITUDE)
    partner = Organisation.objects.create(name="ESN Partenaire", kind=Organisation.Kind.CLIENT, activity_sector=SECTOR)
    partner2 = Organisation.objects.create(name="ESN Autre", kind=Organisation.Kind.CLIENT, activity_sector=SECTOR)
    end = Organisation.objects.create(name="Client final", kind=Organisation.Kind.END_CLIENT, activity_sector=SECTOR)
    partner.end_clients.add(end)
    other = Organisation.objects.create(name="Autre client", kind=Organisation.Kind.CLIENT, activity_sector=SECTOR)
    t = ContractType.objects.get(name="Standard 24x7")

    def contract(ref, org, **kw):
        return Contract.objects.create(reference=ref, title=ref, client=org, start_date=datetime.date(2026, 1, 1),
                                       contract_type=t, **kw)

    def user(email, org, profile):
        return User.objects.create_user(email, "Motdepasse-tres-long-1", organisation=org, profile=profile)

    return {
        "partner": partner, "partner2": partner2, "end": end, "other": other,
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


def test_end_client_can_be_shared_between_esns(esn):
    """Deux ESN peuvent intervenir sur le même client final, sur leurs solutions."""
    esn["partner2"].end_clients.add(esn["end"])
    esn["partner2"].refresh_from_db()
    assert esn["end"] in esn["partner2"].end_clients.all()
    assert sorted(o.name for o in esn["end"].partner_esns.all()) == ["ESN Autre", "ESN Partenaire"]


def test_only_end_clients_can_be_attached(esn):
    esn["partner"].end_clients.add(esn["other"])
    esn["partner"].refresh_from_db()
    with pytest.raises(ValidationError):
        esn["partner"].full_clean()


def test_only_esns_can_have_end_clients(esn):
    esn["end"].end_clients.add(esn["partner2"])
    esn["end"].refresh_from_db()
    with pytest.raises(ValidationError):
        esn["end"].full_clean()


def test_end_client_cannot_be_attached_to_itself_or_aptitude(esn):
    apt = Organisation.objects.get(kind=Organisation.Kind.APTITUDE)
    esn["partner"].end_clients.add(esn["end"], apt)
    esn["partner"].refresh_from_db()
    with pytest.raises(ValidationError):
        esn["partner"].full_clean()


def test_contract_end_clients_limited_to_esn(esn):
    """Le formulaire de contrat refuse un client final non rattaché à l'ESN choisie."""
    from contracts.admin import ContractForm

    stray = Organisation.objects.create(name="Client final isolé", kind=Organisation.Kind.END_CLIENT,
                                         activity_sector=SECTOR)
    ct = ContractType.objects.get(name="Standard 24x7")
    base = {
        "reference": "ESN-9", "title": "Contrat", "client": esn["partner"].pk,
        "contract_type": ct.pk, "status": "active", "start_date": "2026-01-01",
        "end_date": "", "allowance_tickets": "",
    }
    form = ContractForm({**base, "end_clients": esn["end"].pk})
    assert form.is_valid(), form.errors
    assert form.cleaned_data["end_clients"] == [esn["end"]]

    form = ContractForm({**base, "end_clients": stray.pk})
    assert not form.is_valid()
    assert "end_clients" in form.errors
