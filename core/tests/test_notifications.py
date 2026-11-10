"""Cloche de notifications : qui est notifié de quoi, et parcours dans l'interface."""
import datetime

import pytest
from django.urls import reverse

from core.models import Notification
from reports import services as R
from reports.models import Report
from reports.tests.test_reports import MON_10, w  # noqa: F401  (fixture partagée)
from tickets import services as T
from tickets.models import Status

pytestmark = pytest.mark.django_db


def titles(user):
    return [n.title for n in Notification.objects.filter(recipient=user)]


def unread(user):
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()


# --- Tickets ------------------------------------------------------------------------------------

def test_new_ticket_notifies_support_team_but_not_its_author(w):
    ref = w["ticket"].reference
    assert f"{ref} — Nouveau ticket" in titles(w["boss"])
    assert f"{ref} — Nouveau ticket" in titles(w["tech"])
    # Le client a ouvert le ticket lui-même : pas de notification de sa propre action.
    assert not any("bien été enregistrée" in t for t in titles(w["end_user"]))


def test_self_assignment_is_silent_but_assignment_by_someone_else_notifies(w):
    ref = w["ticket"].reference
    assert f"{ref} — Ticket qui vous est assigné" not in titles(w["tech"])
    t = T.create_ticket(w["end_user"], w["contract"], "Imprimante", "Ne répond plus",
                        now=MON_10 + datetime.timedelta(hours=3))
    T.assign(w["boss"], t, w["tech"], now=MON_10 + datetime.timedelta(hours=3, minutes=1))
    n = Notification.objects.get(recipient=w["tech"], title=f"{t.reference} — Ticket qui vous est assigné")
    assert n.actor == w["boss"] and n.url == reverse("ticket_detail", args=[t.reference]) and n.is_unread


def test_client_is_notified_of_status_and_replies_but_never_of_internal_notes(w):
    ref = w["ticket"].reference
    assert f"{ref} — Statut : Résolu" in titles(w["end_user"])
    before = unread(w["end_user"])
    T.add_comment(w["tech"], w["ticket"], "Note interne : à surveiller", internal=True)
    assert unread(w["end_user"]) == before
    T.add_comment(w["tech"], w["ticket"], "Le VPN est rétabli.")
    assert f"{ref} — Nouvelle réponse de notre équipe" in titles(w["end_user"])


def test_client_reply_notifies_the_assigned_engineer(w):
    T.change_status(w["end_user"], w["ticket"], Status.IN_PROGRESS)  # réouverture
    T.add_comment(w["end_user"], w["ticket"], "Toujours coupé chez nous.")
    assert f"{w['ticket'].reference} — Réponse du client" in titles(w["tech"])
    assert f"{w['ticket'].reference} — Réponse du client" not in titles(w["boss"])


def test_notification_failure_never_blocks_the_action(w, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("base indisponible")
    monkeypatch.setattr(Notification.objects, "create", boom)
    t = T.create_ticket(w["end_user"], w["contract"], "Wi-Fi", "Coupé", now=MON_10 + datetime.timedelta(hours=4))
    assert t.pk


# --- Rapports -----------------------------------------------------------------------------------

def test_report_workflow_notifies_each_step(w):
    r = R.create_report(w["tech"], Report.Kind.CURATIVE, w["contract"], end_client=w["end"], ticket=w["ticket"])
    url = reverse("report_detail", args=[r.pk])

    R.submit(w["tech"], r)
    n = Notification.objects.get(recipient=w["boss"], title=f"Rapport à valider : {r.reference}")
    assert n.url == url and n.actor == w["tech"]
    assert f"Rapport à valider : {r.reference}" not in titles(w["other_mgr"])  # pas son ingénieur

    R.reject(w["boss"], r, "Préciser la cause racine")
    n = Notification.objects.get(recipient=w["tech"], title=f"Rapport à corriger : {r.reference}")
    assert n.body == "Préciser la cause racine"

    R.submit(w["tech"], r)
    R.validate(w["boss"], r)
    assert f"Rapport validé : {r.reference}" in titles(w["tech"])

    R.send_to_client(w["boss"], r)
    assert f"Nouveau rapport disponible : {r.reference}" in titles(w["esn_admin"])
    assert f"Nouveau rapport disponible : {r.reference}" not in titles(w["tech"])

    R.client_confirm(w["esn_admin"], r)
    assert f"Réception confirmée : {r.reference}" in titles(w["tech"])
    assert f"Réception confirmée : {r.reference}" in titles(w["boss"])
    assert f"Réception confirmée : {r.reference}" not in titles(w["esn_admin"])


# --- Interface ----------------------------------------------------------------------------------

def test_bell_shows_unread_count_and_items(w):
    c = w["client"]
    c.force_login(w["boss"])
    page = c.get(reverse("dashboard")).content.decode()
    assert "data-notif" in page and 'data-notif-count' in page
    assert f"{w['ticket'].reference} — Nouveau ticket" in page
    data = c.get(reverse("notification_panel")).json()
    assert data["unread"] == unread(w["boss"]) > 0
    assert "Nouveau ticket" in data["html"]


def test_bell_is_also_on_the_client_portal(w):
    c = w["client"]
    c.force_login(w["end_user"])
    page = c.get(reverse("dashboard")).content.decode()
    assert page.count("data-notif ") >= 2  # barre latérale + barre mobile
    assert f"{w['ticket'].reference} — Statut" in page


def test_opening_a_notification_marks_it_read_and_redirects(w):
    c = w["client"]
    c.force_login(w["boss"])
    n = Notification.objects.filter(recipient=w["boss"]).first()
    resp = c.get(reverse("notification_open", args=[n.pk]))
    assert resp.status_code == 302 and resp["Location"] == n.url
    n.refresh_from_db()
    assert not n.is_unread


def test_cannot_open_someone_elses_notification(w):
    c = w["client"]
    c.force_login(w["end_user"])
    n = Notification.objects.filter(recipient=w["boss"]).first()
    assert c.get(reverse("notification_open", args=[n.pk])).status_code == 404
    n.refresh_from_db()
    assert n.is_unread


def test_mark_all_read(w):
    c = w["client"]
    c.force_login(w["boss"])
    assert unread(w["boss"]) > 0
    assert unread(w["tech"]) > 0
    resp = c.post(reverse("notification_read_all"), {"next": reverse("notifications")})
    assert resp.status_code == 302
    assert unread(w["boss"]) == 0
    assert unread(w["tech"]) > 0, "seules les notifications de l'utilisateur connecté"
    assert c.get(reverse("notification_read_all")).status_code == 405


def test_notification_list_page(w):
    c = w["client"]
    c.force_login(w["boss"])
    page = c.get(reverse("notifications")).content.decode()
    assert "Nouveau ticket" in page


def test_bell_requires_login(w):
    assert w["client"].get(reverse("notification_panel")).status_code == 302
