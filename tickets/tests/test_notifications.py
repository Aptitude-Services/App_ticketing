"""Emails de suivi des tickets : qui est prévenu, à quelle étape, et jamais d'une note interne."""
import datetime
from zoneinfo import ZoneInfo

import pytest
from django.core import mail

from accounts.models import Organisation, Profile, User
from contracts.models import Contract, ContractType
from tickets import services as S
from tickets.models import Status

pytestmark = pytest.mark.django_db
NOW = datetime.datetime(2026, 11, 2, 10, tzinfo=ZoneInfo("Africa/Abidjan"))


@pytest.fixture
def w():
    apt = Organisation.objects.create(name="Aptitude Services", kind="aptitude")
    esn = Organisation.objects.create(name="ESN", kind="client")
    end = Organisation.objects.create(name="Final", kind="end_client", activity_sector="bank")
    esn.end_clients.add(end)
    contract = Contract.objects.create(title="C", client=esn, start_date=datetime.date(2026, 1, 1),
                                       contract_type=ContractType.objects.get(name="GOLD"))
    contract.end_clients.add(end)

    def mk(email, org, profile):
        return User.objects.create_user(email, "Motdepasse-tres-long-1", organisation=org, profile=profile)

    return {
        "contract": contract,
        "client": mk("it@final.ci", end, Profile.CLIENT_RW),
        "eng": mk("eng@apt.ci", apt, Profile.TECH_ALL),
        "mgr": mk("mgr@apt.ci", apt, Profile.APTITUDE_MANAGER),
        "restricted": mk("r@apt.ci", apt, Profile.TECH_ASSIGNED),  # sans affectation : pas prévenu
    }


def sent_to(email):
    return [m for m in mail.outbox if email in m.to]


def test_creation_acknowledges_client_and_alerts_support_team(w):
    mail.outbox.clear()
    t = S.create_ticket(w["client"], w["contract"], "VPN coupé", "Plus d'accès", now=NOW)
    ack = sent_to("it@final.ci")
    assert len(ack) == 1 and t.reference in ack[0].subject and "bien été enregistrée" in ack[0].subject
    assert sent_to("eng@apt.ci") and sent_to("mgr@apt.ci")
    assert not sent_to("r@apt.ci"), "un ingénieur sans accès au contrat n'est pas prévenu"
    assert "Plus d'accès" in sent_to("eng@apt.ci")[0].body


def test_lifecycle_emails_reach_the_right_people(w):
    t = S.create_ticket(w["client"], w["contract"], "VPN", "x", now=NOW)
    mail.outbox.clear()
    S.assign(w["mgr"], t, w["eng"], now=NOW)
    assert [m.to for m in mail.outbox] == [["eng@apt.ci"]]

    mail.outbox.clear()
    S.change_status(w["eng"], t, Status.IN_PROGRESS, now=NOW)
    assert [m.to for m in mail.outbox] == [["it@final.ci"]] and "En cours" in mail.outbox[0].subject

    mail.outbox.clear()
    S.add_comment(w["eng"], t, "Pouvez-vous redémarrer le boîtier ?", now=NOW)
    assert [m.to for m in mail.outbox] == [["it@final.ci"]] and "redémarrer" in mail.outbox[0].body

    mail.outbox.clear()
    S.add_comment(w["eng"], t, "SECRET certificat expiré", internal=True, now=NOW)
    assert not mail.outbox, "une note interne ne part jamais"

    mail.outbox.clear()
    S.add_comment(w["client"], t, "C'est fait, merci", now=NOW)
    assert [m.to for m in mail.outbox] == [["eng@apt.ci"]], "la réponse du client va à l'ingénieur assigné"

    mail.outbox.clear()
    S.change_priority(w["eng"], t, 2, "Tout le siège est impacté", now=NOW)
    assert [m.to for m in mail.outbox] == [["it@final.ci"]] and "P2" in mail.outbox[0].subject
    assert "Tout le siège" in mail.outbox[0].body

    mail.outbox.clear()
    S.change_status(w["eng"], t, Status.RESOLVED, now=NOW)
    assert [m.to for m in mail.outbox] == [["it@final.ci"]] and "Résolu" in mail.outbox[0].subject
    assert all("SECRET" not in m.body for m in mail.outbox)


def test_first_public_reply_sends_one_email_not_two(w):
    """La réponse qui fait passer le ticket en « Pris en charge » n'envoie qu'un email."""
    t = S.create_ticket(w["client"], w["contract"], "VPN", "x", now=NOW)
    mail.outbox.clear()
    S.add_comment(w["eng"], t, "Nous regardons.", now=NOW)
    t.refresh_from_db()
    assert t.status == Status.ACKNOWLEDGED and len(mail.outbox) == 1


def test_client_reply_on_unassigned_ticket_goes_to_the_team(w):
    t = S.create_ticket(w["client"], w["contract"], "VPN", "x", now=NOW)
    mail.outbox.clear()
    S.add_comment(w["client"], t, "Des nouvelles ?", now=NOW)
    assert sent_to("eng@apt.ci") and sent_to("mgr@apt.ci") and not sent_to("it@final.ci")


def test_auto_close_tells_the_client(w):
    t = S.create_ticket(w["client"], w["contract"], "VPN", "x", now=NOW)
    S.change_status(w["eng"], t, Status.RESOLVED, now=NOW)
    mail.outbox.clear()
    assert S.auto_close(now=NOW + datetime.timedelta(days=2)) == 1
    assert [m.to for m in mail.outbox] == [["it@final.ci"]] and "Clos" in mail.outbox[0].subject


def test_mail_failure_never_blocks_the_ticket(w, monkeypatch):
    import tickets.notifications as N

    def broken(*args, **kwargs):
        raise RuntimeError("Graph 404")

    monkeypatch.setattr(N, "send_mail", broken)
    t = S.create_ticket(w["client"], w["contract"], "VPN", "x", now=NOW)
    S.add_comment(w["eng"], t, "Réponse", now=NOW)
    S.change_status(w["eng"], t, Status.RESOLVED, now=NOW)
    t.refresh_from_db()
    assert t.status == Status.RESOLVED
