"""Tests de cloisonnement : un client ne doit jamais voir les données d'un autre."""
import datetime

import pytest
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.forms import UserManageForm
from accounts.models import AuditEvent, Organisation, Profile, User
from accounts.permissions import manageable_users, visible_contracts
from contracts.models import Contract, ContractAccess, ContractType, Solution

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    apt = Organisation.objects.create(name="Aptitude Services", kind=Organisation.Kind.APTITUDE)
    a = Organisation.objects.create(name="Client A")
    b = Organisation.objects.create(name="Client B")
    today = datetime.date(2026, 1, 1)
    t = ContractType.objects.get(name="Standard 8x5")
    ca1 = Contract.objects.create(reference="A-001", title="Réseau A", client=a, start_date=today, contract_type=t)
    ca2 = Contract.objects.create(reference="A-002", title="SOC A", client=a, start_date=today, contract_type=t)
    cb1 = Contract.objects.create(reference="B-001", title="Réseau B", client=b, start_date=today, contract_type=t)
    Solution.objects.create(contract=ca1, category="hardware", name="Pare-feu A")
    Solution.objects.create(contract=ca1, category="vm", name="VM retirée A", is_active=False)
    Solution.objects.create(contract=cb1, category="hardware", name="Pare-feu B")

    def mk(email, org, profile, **kw):
        return User.objects.create_user(email, "Motdepasse-tres-long-1", organisation=org, profile=profile, **kw)

    users = {
        "apt_admin": mk("admin@aptitudes.net", apt, Profile.APTITUDE_ADMIN),
        "apt_manager": mk("manager@aptitudes.net", apt, Profile.APTITUDE_MANAGER),
        "tech_all": mk("tech1@aptitudes.net", apt, Profile.TECH_ALL),
        "tech_assigned": mk("tech2@aptitudes.net", apt, Profile.TECH_ASSIGNED),
        "a_admin": mk("admin@a.ci", a, Profile.CLIENT_ADMIN),
        "a_rw": mk("rw@a.ci", a, Profile.CLIENT_RW),
        "a_restricted": mk("restreint@a.ci", a, Profile.CLIENT_RO, all_contracts=False),
        "b_admin": mk("admin@b.ci", b, Profile.CLIENT_ADMIN),
    }
    ContractAccess.objects.create(user=users["tech_assigned"], contract=cb1)
    ContractAccess.objects.create(user=users["a_restricted"], contract=ca2)
    return {"orgs": {"apt": apt, "a": a, "b": b}, "contracts": {"a1": ca1, "a2": ca2, "b1": cb1}, **users}


def refs(qs):
    return sorted(qs.values_list("reference", flat=True))


# --- Visibilité des contrats ------------------------------------------------------

def test_aptitude_global_profiles_see_everything(world):
    for key in ("apt_admin", "apt_manager", "tech_all"):
        assert refs(visible_contracts(world[key])) == ["A-001", "A-002", "B-001"]


def test_assigned_technician_sees_only_assigned(world):
    assert refs(visible_contracts(world["tech_assigned"])) == ["B-001"]


def test_client_sees_only_own_organisation(world):
    assert refs(visible_contracts(world["a_admin"])) == ["A-001", "A-002"]
    assert refs(visible_contracts(world["a_rw"])) == ["A-001", "A-002"]
    assert refs(visible_contracts(world["b_admin"])) == ["B-001"]


def test_restricted_client_sees_only_selected_contracts(world):
    assert refs(visible_contracts(world["a_restricted"])) == ["A-002"]


def test_access_to_other_org_contract_is_refused(world):
    with pytest.raises(Exception):
        ContractAccess.objects.create(user=world["a_rw"], contract=world["contracts"]["b1"])


def test_inactive_user_or_organisation_sees_nothing(world):
    u = world["a_rw"]
    u.is_active = False
    assert not visible_contracts(u).exists()
    u.is_active = True
    org = world["orgs"]["a"]
    org.is_active = False
    org.save()
    u.refresh_from_db()
    assert not visible_contracts(u).exists()


def test_dashboard_never_lists_other_clients_contracts(client, world):
    client.force_login(world["a_admin"])
    html = client.get(reverse("dashboard")).content.decode()
    assert "A-001" in html and "A-002" in html
    assert "B-001" not in html and "Client B" not in html


# --- Gestion des utilisateurs -------------------------------------------------------

def test_manageable_users_scope(world):
    a_emails = sorted(manageable_users(world["a_admin"]).values_list("email", flat=True))
    assert a_emails == ["admin@a.ci", "restreint@a.ci", "rw@a.ci"]
    assert not manageable_users(world["a_rw"]).exists()
    assert not manageable_users(world["tech_all"]).exists()
    assert not manageable_users(world["apt_manager"]).filter(organisation__kind="aptitude").exists()


def test_client_admin_cannot_open_other_org_user(client, world):
    client.force_login(world["a_admin"])
    resp = client.get(reverse("user_update", args=[world["b_admin"].pk]))
    assert resp.status_code == 404


def test_non_admin_client_cannot_manage_users(client, world):
    client.force_login(world["a_rw"])
    assert client.get(reverse("user_list")).status_code == 404


def _payload(**over):
    data = {"email": "nouveau@a.ci", "first_name": "Awa", "last_name": "Koné", "phone": "", "language": "fr",
            "profile": Profile.CLIENT_RW, "all_contracts": "on", "is_active": "on"}
    data.update(over)
    return data


def test_client_admin_cannot_grant_aptitude_profile(world):
    form = UserManageForm(_payload(profile=Profile.APTITUDE_ADMIN), actor=world["a_admin"])
    assert not form.is_valid()
    assert "profile" in form.errors


def test_client_admin_creates_user_in_own_org_only(world):
    form = UserManageForm(_payload(organisation=world["orgs"]["b"].pk), actor=world["a_admin"])
    assert form.is_valid(), form.errors
    user = form.save()
    assert user.organisation == world["orgs"]["a"]
    assert not user.has_usable_password()


def test_client_admin_cannot_attach_other_org_contract(world):
    data = _payload(contracts=[world["contracts"]["b1"].pk])
    data.pop("all_contracts")
    form = UserManageForm(data, actor=world["a_admin"])
    assert not form.is_valid()
    assert "contracts" in form.errors


def test_client_admin_restricts_user_to_some_contracts(world):
    data = _payload(contracts=[world["contracts"]["a1"].pk])
    data.pop("all_contracts")
    form = UserManageForm(data, actor=world["a_admin"])
    assert form.is_valid(), form.errors
    user = form.save()
    assert refs(visible_contracts(user)) == ["A-001"]


def test_last_client_admin_cannot_be_demoted_or_disabled(world):
    admin_a = world["a_admin"]
    data = _payload(email=admin_a.email, profile=Profile.CLIENT_RW)
    form = UserManageForm(data, instance=admin_a, actor=admin_a)
    assert not form.is_valid()
    data = _payload(email=admin_a.email, profile=Profile.CLIENT_ADMIN)
    data.pop("is_active")
    form = UserManageForm(data, instance=admin_a, actor=admin_a)
    assert not form.is_valid()


def test_user_creation_is_audited_and_sends_invitation(client, world, mailoutbox):
    client.force_login(world["a_admin"])
    resp = client.post(reverse("user_create"), _payload())
    assert resp.status_code == 302
    assert AuditEvent.objects.filter(action=AuditEvent.Action.USER_CREATED, target_user__email="nouveau@a.ci").exists()
    assert len(mailoutbox) == 1 and "nouveau@a.ci" in mailoutbox[0].to


def test_standby_profile_is_not_offered(world):
    offered = {value for value, _label in UserManageForm(actor=world["apt_admin"]).fields["profile"].choices}
    assert Profile.TECH_ALL in offered
    assert Profile.TECH_ASSIGNED not in offered


def test_user_with_standby_profile_stays_editable(world):
    user = world["tech_assigned"]
    form = UserManageForm(instance=user, actor=world["apt_admin"])
    assert Profile.TECH_ASSIGNED in {value for value, _label in form.fields["profile"].choices}


def test_profile_must_match_organisation_kind(world):
    with pytest.raises(Exception):
        User.objects.create_user("x@a.ci", "Motdepasse-tres-long-1", organisation=world["orgs"]["a"], profile=Profile.TECH_ALL)


# --- MFA et accès ---------------------------------------------------------------------

def test_anonymous_is_redirected_to_login(client):
    resp = client.get(reverse("dashboard"))
    assert resp.status_code == 302 and reverse("login") in resp["Location"]


def test_aptitude_user_must_enroll_mfa(client, world):
    client.force_login(world["tech_all"])
    resp = client.get(reverse("dashboard"))
    assert resp.status_code == 302 and resp["Location"] == reverse("mfa_setup")


def test_client_without_mfa_is_not_forced(client, world):
    client.force_login(world["a_rw"])
    assert client.get(reverse("dashboard")).status_code == 200


def test_client_with_mfa_must_verify(client, world):
    TOTPDevice.objects.create(user=world["a_rw"], name="app", confirmed=True)
    client.force_login(world["a_rw"])
    resp = client.get(reverse("dashboard"))
    assert resp.status_code == 302 and resp["Location"].startswith(reverse("mfa_verify"))


def test_mfa_setup_with_valid_token_unlocks_access(client, world):
    from django_otp.oath import totp
    user = world["tech_all"]
    client.force_login(user)
    client.get(reverse("mfa_setup"))
    device = TOTPDevice.objects.get(user=user, confirmed=False)
    token = f"{totp(device.bin_key, device.step, device.t0, device.digits, device.drift):06d}"
    resp = client.post(reverse("mfa_setup"), {"token": token})
    assert resp.status_code == 302
    assert client.get(reverse("dashboard")).status_code == 200


# --- Rendu des pages -----------------------------------------------------------------

def test_pages_render(client, world):
    assert client.get(reverse("login")).status_code == 200
    assert client.get(reverse("password_reset")).status_code == 200
    client.force_login(world["a_admin"])
    for name, args in [("dashboard", []), ("user_list", []), ("user_create", []),
                       ("user_update", [world["a_rw"].pk]), ("my_profile", []), ("mfa_setup", [])]:
        resp = client.get(reverse(name, args=args))
        assert resp.status_code == 200, name


# --- Jalon 2 : contrats et solutions ------------------------------------------------------

def test_contract_detail_is_isolated(client, world):
    client.force_login(world["a_rw"])
    ok = client.get(reverse("contract_detail", args=[world["contracts"]["a1"].pk]))
    assert ok.status_code == 200 and "Pare-feu A" in ok.content.decode()
    assert client.get(reverse("contract_detail", args=[world["contracts"]["b1"].pk])).status_code == 404


def test_restricted_client_cannot_open_non_selected_contract(client, world):
    client.force_login(world["a_restricted"])
    assert client.get(reverse("contract_detail", args=[world["contracts"]["a1"].pk])).status_code == 404
    assert client.get(reverse("contract_detail", args=[world["contracts"]["a2"].pk])).status_code == 200


def test_visible_solutions_scope(world):
    from accounts.permissions import visible_solutions
    names = lambda u: sorted(visible_solutions(u).values_list("name", flat=True))
    assert names(world["a_admin"]) == ["Pare-feu A"]                 # solution inactive masquée au client
    assert names(world["b_admin"]) == ["Pare-feu B"]
    assert names(world["tech_assigned"]) == ["Pare-feu B"]
    assert names(world["apt_admin"]) == ["Pare-feu A", "Pare-feu B", "VM retirée A"]


def test_contract_requires_type(world):
    from django.core.exceptions import ValidationError
    c = Contract(reference="X-1", title="Sans type", client=world["orgs"]["a"], start_date=datetime.date(2026, 1, 1))
    with pytest.raises(ValidationError):
        c.full_clean()
