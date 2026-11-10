"""Suppression d'un contrat ou d'un ticket de test depuis l'administration : Super Admin seul."""
import pytest
from django.urls import reverse

from accounts.models import Profile, User
from contracts.models import Contract
from reports import services as R
from reports.models import Report
from reports.tests.test_reports import w  # noqa: F401  (fixture partagée)
from tickets.models import Event, Ticket

pytestmark = pytest.mark.django_db


@pytest.fixture
def root(w):
    return User.objects.create_user("root@apt.ci", "Motdepasse-tres-long-1", organisation=w["boss"].organisation,
                                    profile=Profile.APTITUDE_ADMIN)


def _with_report(w):
    return R.create_report(w["tech"], Report.Kind.CURATIVE, w["contract"], end_client=w["end"], ticket=w["ticket"])


def test_super_admin_deletes_a_contract_with_its_tickets_and_reports(w, root):
    report = _with_report(w)
    c, contract, ticket = w["client"], w["contract"], w["ticket"]
    c.force_login(root)
    url = reverse("admin:contracts_contract_delete", args=[contract.pk])
    page = c.get(url).content.decode()
    assert "Impossible" not in page and ticket.reference in page and report.reference in page
    assert c.post(url, {"post": "yes"}).status_code == 302
    assert not Contract.objects.filter(pk=contract.pk).exists()
    assert not Ticket.objects.filter(pk=ticket.pk).exists()
    assert not Report.objects.filter(pk=report.pk).exists()
    assert not Event.objects.filter(ticket_id=ticket.pk).exists()


def test_super_admin_deletes_a_ticket_with_its_history(w, root):
    c, ticket = w["client"], w["ticket"]
    c.force_login(root)
    url = reverse("admin:tickets_ticket_delete", args=[ticket.pk])
    assert "Impossible" not in c.get(url).content.decode()
    c.post(url, {"post": "yes"})
    assert not Ticket.objects.filter(pk=ticket.pk).exists()
    assert Contract.objects.filter(pk=w["contract"].pk).exists()


def test_bulk_delete_of_contracts_by_super_admin(w, root):
    c = w["client"]
    c.force_login(root)
    c.post(reverse("admin:contracts_contract_changelist"),
           {"action": "delete_selected", "_selected_action": [w["contract"].pk], "post": "yes"})
    assert not Contract.objects.filter(pk=w["contract"].pk).exists()


def test_manager_still_cannot_delete_history(w):
    c, boss = w["client"], w["boss"]
    c.force_login(boss)
    contract_url = reverse("admin:contracts_contract_delete", args=[w["contract"].pk])
    assert "Impossible" in c.get(contract_url).content.decode()
    c.post(contract_url, {"post": "yes"})
    assert Contract.objects.filter(pk=w["contract"].pk).exists()
    assert c.get(reverse("admin:tickets_ticket_delete", args=[w["ticket"].pk])).status_code == 403
    assert Ticket.objects.filter(pk=w["ticket"].pk).exists()


def test_events_cannot_be_deleted_one_by_one(w, root):
    c = w["client"]
    c.force_login(root)
    page = c.get(reverse("admin:tickets_event_changelist")).content.decode()
    assert "delete_selected" not in page
