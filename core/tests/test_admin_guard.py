"""Accès à l'administration : aucune information divulguée aux comptes non autorisés."""
import pytest
from django.urls import reverse

from reports.tests.test_reports import w  # noqa: F401  (fixture partagée)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("who", ["end_user", "esn_admin", "tech"])
def test_unauthorised_user_gets_a_plain_not_found_page(w, who):
    c, user = w["client"], w[who]
    assert not user.is_staff
    c.force_login(user)
    resp = c.get(reverse("admin:index"), follow=True)
    page = resp.content.decode()
    assert resp.status_code == 404
    assert user.email not in page
    assert "autorisé" not in page and "authentifié" not in page and "administration" not in page.lower()
    assert c.get(reverse("admin:login")).status_code == 404


def test_anonymous_visitor_is_sent_to_the_app_login(w):
    resp = w["client"].get(reverse("admin:index"), follow=True)
    assert resp.redirect_chain[-1][0].startswith(reverse("login"))
    assert resp.status_code == 200


def test_staff_member_still_reaches_the_admin(w):
    c, boss = w["client"], w["boss"]
    assert boss.is_staff  # Manager Aptitude
    c.force_login(boss)
    assert c.get(reverse("admin:index")).status_code == 200
    assert c.get(reverse("admin:login")).status_code == 302  # déjà connecté → index


def test_admin_home_has_no_recent_actions_block(w):
    c = w["client"]
    c.force_login(w["boss"])
    page = c.get(reverse("admin:index")).content.decode()
    assert 'id="recent-actions-module"' not in page
    assert "colMS" not in page
