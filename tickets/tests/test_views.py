"""Écrans tickets : cloisonnement et parcours par le navigateur."""
import datetime
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from tickets import services as S
from tickets.models import Status, Ticket
from tickets.tests.test_services import MON_10, w  # noqa: F401  (fixture partagée)

pytestmark = pytest.mark.django_db


@pytest.fixture
def frozen():
    with mock.patch("django.utils.timezone.now", return_value=MON_10):
        yield


def login_aptitude(client, user):
    """Ouvre une session Aptitude avec MFA validée."""
    TOTPDevice.objects.create(user=user, name="app", confirmed=True)
    client.force_login(user)
    session = client.session
    from django_otp import DEVICE_ID_SESSION_KEY
    session[DEVICE_ID_SESSION_KEY] = user.totpdevice_set.first().persistent_id
    session.save()


def test_client_creates_ticket_from_portal(client, w, frozen):  # noqa: F811
    client.force_login(w["a_rw"])
    resp = client.post(reverse("ticket_create"), {
        "contract": w["c85"].pk, "solutions": [w["s1"].pk], "title": "Serveur lent",
        "description": "Depuis ce matin.", "priority": 4,
        "files": SimpleUploadedFile("journal.txt", b"erreur disque"),
    })
    t = Ticket.objects.get()
    assert resp.status_code == 302 and resp["Location"] == reverse("ticket_detail", args=[t.reference])
    assert t.attachments.count() == 1 and list(t.solutions.all()) == [w["s1"]]
    page = client.get(resp["Location"]).content.decode()
    assert "Serveur lent" in page and "journal.txt" in page


def test_client_blocked_outside_hours_on_8x5(client, w):  # noqa: F811
    sat = MON_10 + datetime.timedelta(days=5)
    with mock.patch("django.utils.timezone.now", return_value=sat):
        client.force_login(w["a_rw"])
        resp = client.post(reverse("ticket_create"), {"contract": w["c85"].pk, "title": "x", "description": "y", "priority": 4})
    assert resp.status_code == 200 and not Ticket.objects.exists()
    assert "heures ouvrées" in resp.content.decode()


def test_other_client_cannot_see_ticket_or_attachment(client, w, frozen):  # noqa: F811
    t = S.create_ticket(w["a_rw"], w["c85"], "Serveur lent", "desc")
    c = S.add_comment(w["a_rw"], t, "", files=[SimpleUploadedFile("cap.png", b"png")])
    client.force_login(w["b_rw"])
    assert client.get(reverse("ticket_detail", args=[t.reference])).status_code == 404
    assert client.get(reverse("attachment_download", args=[t.reference, c.attachments.get().pk])).status_code == 404
    assert t.reference not in client.get(reverse("ticket_list") + "?vue=tous").content.decode()
    assert client.post(reverse("ticket_comment", args=[t.reference]), {"body": "intrusion"}).status_code == 404


def test_internal_note_hidden_from_client(client, w, frozen):  # noqa: F811
    t = S.create_ticket(w["a_rw"], w["c85"], "Serveur lent", "desc")
    note = S.add_comment(w["tech"], t, "Mot de passe admin dans le coffre", internal=True,
                         files=[SimpleUploadedFile("interne.txt", b"secret")])
    client.force_login(w["a_rw"])
    page = client.get(reverse("ticket_detail", args=[t.reference])).content.decode()
    assert "coffre" not in page and "interne.txt" not in page
    att = note.attachments.get()
    assert client.get(reverse("attachment_download", args=[t.reference, att.pk])).status_code == 404


def test_read_only_client_has_no_write_controls(client, w, frozen):  # noqa: F811
    t = S.create_ticket(w["a_rw"], w["c85"], "Serveur lent", "desc")
    client.force_login(w["a_ro"])
    page = client.get(reverse("ticket_detail", args=[t.reference])).content.decode()
    assert reverse("ticket_comment", args=[t.reference]) not in page
    assert client.get(reverse("ticket_create")).status_code == 404
    client.post(reverse("ticket_comment", args=[t.reference]), {"body": "test"})
    assert not t.comments.exists()


def test_client_escalates_to_p3_from_detail(client, w, frozen):  # noqa: F811
    t = S.create_ticket(w["a_rw"], w["c85"], "Serveur lent", "desc")
    client.force_login(w["a_rw"])
    client.post(reverse("ticket_priority", args=[t.reference]), {"priority": 3})
    t.refresh_from_db()
    assert t.priority == 3
    client.post(reverse("ticket_priority", args=[t.reference]), {"priority": 2, "justification": "c'est grave !!!"})
    t.refresh_from_db()
    assert t.priority == 3


def test_aptitude_console_flow(client, w, frozen):  # noqa: F811
    t = S.create_ticket(w["a_rw"], w["c85"], "Serveur lent", "desc")
    login_aptitude(client, w["tech"])
    assert client.get(reverse("dashboard")).status_code == 200
    listing = client.get(reverse("ticket_list")).content.decode()
    assert t.reference in listing and "c-side" in listing
    client.post(reverse("ticket_assign", args=[t.reference]), {"assignee": w["tech"].pk})
    client.post(reverse("ticket_status", args=[t.reference]), {"status": Status.IN_PROGRESS})
    client.post(reverse("ticket_priority", args=[t.reference]), {"priority": 2, "justification": "Interruption totale du site"})
    t.refresh_from_db()
    assert (t.assignee, t.status, t.priority) == (w["tech"], Status.IN_PROGRESS, 2)
    page = client.get(reverse("ticket_detail", args=[t.reference])).content.decode()
    assert "Interruption totale du site" in page


def test_theme_preference_is_saved(client, w):  # noqa: F811
    client.force_login(w["a_rw"])
    client.post(reverse("set_theme"), {"theme": "dark"}, HTTP_X_REQUESTED_WITH="fetch")
    w["a_rw"].refresh_from_db()
    assert w["a_rw"].theme == "dark"
    assert 'data-theme="dark"' in client.get(reverse("dashboard")).content.decode()


# --- Priorité à l'ouverture et menu Rapports ---------------------------------------------

def test_creation_form_greys_out_p1_and_p2(client, w, frozen):  # noqa: F811
    login_aptitude(client, w["tech"])
    html = client.get(reverse("ticket_create")).content.decode()
    assert '<option value="1" disabled' in html and '<option value="2" disabled' in html
    assert '<option value="3"' in html and 'value="3" disabled' not in html


def test_aptitude_cannot_open_ticket_in_p2(client, w, frozen):  # noqa: F811
    login_aptitude(client, w["tech"])
    client.post(reverse("ticket_create"), {"contract": w["c85"].pk, "title": "x", "description": "y", "priority": 2})
    assert not Ticket.objects.exists()


def test_report_pages_writing_is_for_aptitude_only(client, w):  # noqa: F811
    login_aptitude(client, w["tech"])
    for kind in ("preventif", "curatif", "trimestriel"):
        assert client.get(reverse("report", args=[kind])).status_code == 200
        assert client.get(reverse("report_create", args=[kind])).status_code == 200
    assert client.get(reverse("report", args=["inconnu"])).status_code == 404
    # Le client consulte les rapports qui lui ont été envoyés, mais n'en rédige pas.
    client.force_login(w["a_rw"])
    assert client.get(reverse("report", args=["tous"])).status_code == 200
    assert client.get(reverse("report_create", args=["curatif"])).status_code == 403


def test_ticket_page_offers_escalation_to_n_plus_1_only(client, w, frozen):  # noqa: F811
    """Ingénieur : bloc « Escalade » limité à son N+1, plus de liste « Assigné à ». Le manager garde l'assignation."""
    from accounts.models import Profile, User
    apt = w["tech"].organisation
    boss = User.objects.create_user("boss@apt.ci", organisation=apt, profile=Profile.APTITUDE_MANAGER)
    User.objects.create_user("autre@apt.ci", organisation=apt, profile=Profile.APTITUDE_MANAGER)
    w["tech"].manager = boss
    w["tech"].save()
    t = S.create_ticket(w["a_rw"], w["c85"], "Serveur lent", "Lent.", now=MON_10)
    url = reverse("ticket_detail", args=[t.reference])

    login_aptitude(client, w["tech"])
    html = client.get(url).content.decode()
    assert 'id="esc-sel"' in html and html.count('name="manager"') == 1
    assert html.count("<option", html.index('id="esc-sel"'), html.index("</select>", html.index('id="esc-sel"'))) == 1
    assert 'id="as-sel"' not in html
    resp = client.post(reverse("ticket_escalate", args=[t.reference]),
                       {"manager": boss.pk, "reason": "Besoin d'un avis N2"})
    assert resp.status_code == 302
    t.refresh_from_db()
    assert t.assignee == boss
    assert "a escaladé le ticket" in client.get(url).content.decode()

    client.logout()
    login_aptitude(client, boss)
    html = client.get(url).content.decode()
    assert 'id="as-sel"' in html and 'id="esc-sel"' not in html
