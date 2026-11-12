"""Correctifs de la revue de sécurité :
- un Manager ne peut pas, depuis l'administration, toucher aux comptes Aptitude ni se donner
  le profil Super Admin ;
- le changement de mot de passe exige la double authentification (seule la réinitialisation
  par email en est exemptée)."""
import pytest
from django.urls import reverse

from accounts.models import Organisation, Profile, User
from reports.tests.test_reports import w  # noqa: F401  (fixture partagée, MFA neutralisée)

pytestmark = pytest.mark.django_db
PWD = "Motdepasse-tres-long-1"


# --- Administration : périmètre du Manager -------------------------------------------------------

def _admin_user_url(user, suffix="change"):
    # La page de mot de passe de UserAdmin garde le nom fixe « auth_user_password_change ».
    name = "admin:auth_user_password_change" if suffix == "password_change" else f"admin:accounts_user_{suffix}"
    return reverse(name, args=[user.pk])


def test_manager_cannot_open_or_reset_password_of_aptitude_accounts(w):
    c, boss = w["client"], w["boss"]
    superadmin = User.objects.create_user("root@apt.ci", PWD, organisation=boss.organisation,
                                          profile=Profile.APTITUDE_ADMIN)
    c.force_login(boss)
    for target in (superadmin, w["tech"], boss):
        assert c.get(_admin_user_url(target)).status_code in (302, 404)
        assert c.get(_admin_user_url(target, "password_change")).status_code in (302, 404)
        resp = c.post(_admin_user_url(target, "password_change"), {"password1": "Nouveau-mdp-123456",
                                                                   "password2": "Nouveau-mdp-123456"})
        assert resp.status_code in (302, 403, 404)
    superadmin.refresh_from_db()
    assert superadmin.check_password(PWD)
    listing = c.get(reverse("admin:accounts_user_changelist")).content.decode()
    assert w["esn_admin"].email in listing
    assert superadmin.email not in listing and w["tech"].email not in listing


def test_manager_cannot_grant_an_aptitude_profile(w):
    c, boss, target = w["client"], w["boss"], w["esn_admin"]
    c.force_login(boss)
    page = c.get(_admin_user_url(target)).content.decode()
    assert 'value="aptitude_admin"' not in page and 'value="aptitude_manager"' not in page
    resp = c.post(_admin_user_url(target), {
        "email": target.email, "organisation": target.organisation_id, "profile": Profile.APTITUDE_ADMIN,
        "language": "fr", "is_active": "on", "first_name": "", "last_name": "", "phone": "",
        "date_joined_0": "2026-01-01", "date_joined_1": "00:00:00",
    })
    assert resp.status_code == 200  # formulaire renvoyé avec erreur
    target.refresh_from_db()
    assert target.profile == Profile.CLIENT_ADMIN


def test_super_admin_keeps_full_access(w):
    c = w["client"]
    root = User.objects.create_user("root@apt.ci", PWD, organisation=w["boss"].organisation,
                                    profile=Profile.APTITUDE_ADMIN)
    c.force_login(root)
    assert c.get(_admin_user_url(w["boss"])).status_code == 200
    assert c.get(_admin_user_url(w["boss"], "password_change")).status_code == 200
    page = c.get(_admin_user_url(w["boss"])).content.decode()
    assert 'value="aptitude_admin"' in page


# --- Double authentification et mot de passe ------------------------------------------------------

@pytest.fixture
def unverified_engineer(client):
    apt = Organisation.objects.create(name="Aptitude Services", kind=Organisation.Kind.CLIENT, is_operator=True)
    user = User.objects.create_user("eng@apt.ci", PWD, organisation=apt, profile=Profile.TECH_ALL)
    client.force_login(user)  # mot de passe seul, sans code de l'application d'authentification
    return client, user


def test_password_change_requires_mfa(unverified_engineer):
    c, user = unverified_engineer
    resp = c.get(reverse("password_change"))
    assert resp.status_code == 302 and resp["Location"].startswith(reverse("mfa_setup"))
    c.post(reverse("password_change"), {"old_password": PWD, "new_password1": "Autre-mdp-tres-long-9",
                                        "new_password2": "Autre-mdp-tres-long-9"})
    user.refresh_from_db()
    assert user.check_password(PWD)


def test_reset_links_stay_reachable_without_mfa(unverified_engineer):
    c, _user = unverified_engineer
    resp = c.get(reverse("password_reset_confirm", kwargs={"uidb64": "xx", "token": "yy"}))
    assert not (resp.status_code == 302 and "mfa" in resp["Location"])
    assert c.get(reverse("password_reset")).status_code == 200


def test_groups_page_is_removed_from_admin(w):
    from django.urls import NoReverseMatch
    c = w["client"]
    root = User.objects.create_user("root@apt.ci", PWD, organisation=w["boss"].organisation,
                                    profile=Profile.APTITUDE_ADMIN)
    c.force_login(root)
    assert "auth/group" not in c.get(reverse("admin:index")).content.decode()
    with pytest.raises(NoReverseMatch):
        reverse("admin:auth_group_changelist")
