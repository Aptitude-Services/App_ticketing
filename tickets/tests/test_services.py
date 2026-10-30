"""Règles métier des tickets : droits, couverture, priorités, SLA, cycle de vie."""
import datetime
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import Organisation, Profile, User
from contracts.models import Contract, ContractAccess, ContractType, Solution
from tickets import services as S
from tickets.models import Comment, Status

pytestmark = pytest.mark.django_db
TZ = ZoneInfo("Africa/Abidjan")


def at(y, m, d, h=0, mi=0):
    return datetime.datetime(y, m, d, h, mi, tzinfo=TZ)


MON_10 = at(2026, 11, 2, 10)      # lundi, heures ouvrées
SAT_10 = at(2026, 11, 7, 10)      # samedi


@pytest.fixture
def w():
    apt = Organisation.objects.create(name="Aptitude Services", kind="aptitude")
    a = Organisation.objects.create(name="Client A")
    b = Organisation.objects.create(name="Client B")
    t24 = ContractType.objects.get(name="Standard 24x7")
    t85 = ContractType.objects.get(name="Standard 8x5")
    d = datetime.date(2026, 1, 1)
    c24 = Contract.objects.create(reference="A-24", title="SOC A", client=a, start_date=d, contract_type=t24)
    c85 = Contract.objects.create(reference="A-85", title="Serveurs A", client=a, start_date=d, contract_type=t85)
    cb = Contract.objects.create(reference="B-85", title="Serveurs B", client=b, start_date=d, contract_type=t85)
    s1 = Solution.objects.create(contract=c85, category="hardware", name="Serveur A")
    sb = Solution.objects.create(contract=cb, category="hardware", name="Serveur B")

    def mk(email, org, profile, **kw):
        return User.objects.create_user(email, "Motdepasse-tres-long-1", organisation=org, profile=profile, **kw)

    u = {
        "tech": mk("tech@apt.ci", apt, Profile.TECH_ALL),
        "tech2": mk("tech2@apt.ci", apt, Profile.TECH_ASSIGNED),
        "a_rw": mk("rw@a.ci", a, Profile.CLIENT_RW),
        "a_ro": mk("ro@a.ci", a, Profile.CLIENT_RO),
        "b_rw": mk("rw@b.ci", b, Profile.CLIENT_RW),
    }
    ContractAccess.objects.create(user=u["tech2"], contract=cb)
    return {"c24": c24, "c85": c85, "cb": cb, "s1": s1, "sb": sb, **u}


def new(w, actor="a_rw", contract="c85", now=MON_10, **kw):
    return S.create_ticket(w[actor], w[contract], "Serveur lent", "Le serveur répond lentement.", now=now, **kw)


# --- Création ---------------------------------------------------------------------------

def test_reference_and_default_priority(w):
    t = new(w)
    assert t.reference == "APT-2026-00001" and t.priority == 4 and t.status == Status.NEW
    assert new(w).reference == "APT-2026-00002"


def test_p4_deadlines_on_8x5(w):
    t = new(w)  # lundi 10h : prise en charge 8 h ouvrées -> mardi 9h ; résolution 48 h -> lundi suivant 13h
    assert t.response_due == at(2026, 11, 3, 9)
    assert t.resolution_due == at(2026, 11, 9, 13)


def test_client_cannot_create_outside_8x5_hours(w):
    with pytest.raises(S.CoverageError) as e:
        new(w, now=SAT_10)
    assert e.value.next_open == at(2026, 11, 9, 8)


def test_client_can_create_anytime_on_24x7(w):
    t = new(w, contract="c24", now=SAT_10)
    assert t.response_due == at(2026, 11, 7, 18) and not t.out_of_coverage


def test_aptitude_creation_out_of_hours_is_flagged(w):
    t = new(w, actor="tech", now=SAT_10)
    assert t.out_of_coverage
    assert t.response_due == at(2026, 11, 9, 16)  # 8 h ouvrées à partir de lundi 8h


def test_read_only_client_cannot_create(w):
    with pytest.raises(PermissionDenied):
        new(w, actor="a_ro")


def test_client_cannot_create_on_other_org_contract(w):
    with pytest.raises(PermissionDenied):
        new(w, contract="cb")


def test_solution_must_belong_to_contract(w):
    with pytest.raises(ValidationError):
        new(w, solutions=[w["sb"]])
    assert list(new(w, solutions=[w["s1"]]).solutions.all()) == [w["s1"]]


def test_client_can_open_in_p3_but_not_p2(w):
    assert new(w, priority=3).priority == 3
    with pytest.raises(PermissionDenied):
        new(w, priority=2)


# --- Priorité et escalade -----------------------------------------------------------------

def test_client_escalates_p4_to_p3_only(w):
    t = new(w)
    assert S.allowed_priorities(w["a_rw"], t) == [3]
    S.change_priority(w["a_rw"], t, 3, now=MON_10)
    assert t.priority == 3 and S.allowed_priorities(w["a_rw"], t) == []


def test_p2_requires_justification_and_aptitude(w):
    t = new(w)
    with pytest.raises(PermissionDenied):
        S.change_priority(w["a_rw"], t, 2, "panne totale du site", now=MON_10)
    with pytest.raises(ValidationError):
        S.change_priority(w["tech"], t, 2, "", now=MON_10)
    S.change_priority(w["tech"], t, 2, "Interruption totale du service", now=MON_10)
    assert t.priority == 2


def test_escalation_never_pushes_deadline_later(w):
    t = new(w, now=MON_10)
    before = t.resolution_due
    S.change_priority(w["tech"], t, 2, "Interruption totale du service", now=MON_10 + datetime.timedelta(hours=1))
    assert t.resolution_due <= before
    assert t.resolution_due == at(2026, 11, 3, 14)  # 12 h ouvrées depuis lundi 11h


def test_p1_waits_for_prerequisites_then_starts_clock(w):
    t = new(w, contract="c24")
    S.change_priority(w["tech"], t, 1, "Cyber-attaque, chiffrement en cours", now=MON_10)
    assert t.status == Status.WAITING_PREREQ and t.resolution_due is None
    assert S.sla_status(t, now=MON_10 + datetime.timedelta(hours=5))["state"] == "paused"
    later = MON_10 + datetime.timedelta(hours=5)
    S.change_status(w["tech"], t, Status.IN_PROGRESS, now=later)
    assert t.resolution_due == later + datetime.timedelta(hours=8)


# --- Statuts, pauses et respect du SLA ---------------------------------------------------------

def test_waiting_client_pauses_and_resumes(w):
    t = new(w, contract="c24", now=MON_10)          # résolution P4 : 48 h -> mercredi 10h
    S.change_status(w["tech"], t, Status.WAITING_CLIENT, now=MON_10 + datetime.timedelta(hours=8))
    assert t.paused_remaining == 40 * 60
    resume = MON_10 + datetime.timedelta(hours=30)
    S.add_comment(w["a_rw"], t, "Voici les informations demandées.", now=resume)
    t.refresh_from_db()
    assert t.status == Status.IN_PROGRESS
    assert t.resolution_due == resume + datetime.timedelta(hours=40)


def test_public_reply_from_aptitude_acknowledges(w):
    t = new(w, contract="c24", now=MON_10)
    S.add_comment(w["tech"], t, "Nous regardons.", now=MON_10 + datetime.timedelta(minutes=30))
    t.refresh_from_db()
    assert t.status == Status.ACKNOWLEDGED and not t.response_breached


def test_late_acknowledgement_is_recorded(w):
    t = new(w, contract="c24", now=MON_10)
    S.change_status(w["tech"], t, Status.ACKNOWLEDGED, now=MON_10 + datetime.timedelta(hours=9))
    assert t.response_breached


def test_resolution_breach_and_reopen_by_client(w):
    t = new(w, contract="c24", now=MON_10)
    S.change_status(w["tech"], t, Status.RESOLVED, now=MON_10 + datetime.timedelta(hours=50))
    assert t.resolution_breached
    assert S.allowed_statuses(w["a_rw"], t) == [Status.IN_PROGRESS]
    S.change_status(w["a_rw"], t, Status.IN_PROGRESS, now=MON_10 + datetime.timedelta(hours=51))
    assert t.status == Status.IN_PROGRESS and t.resolved_at is None


def test_auto_close_after_one_day(w):
    t = new(w, contract="c24", now=MON_10)
    S.change_status(w["tech"], t, Status.RESOLVED, now=MON_10)
    assert S.auto_close(now=MON_10 + datetime.timedelta(hours=23)) == 0
    assert S.auto_close(now=MON_10 + datetime.timedelta(hours=25)) == 1
    t.refresh_from_db()
    assert t.status == Status.CLOSED


def test_sla_status_risk_and_late(w):
    t = new(w, contract="c24", now=MON_10)
    S.change_status(w["tech"], t, Status.IN_PROGRESS, now=MON_10)
    assert S.sla_status(t, now=MON_10 + datetime.timedelta(hours=10))["state"] == "ok"
    assert S.sla_status(t, now=MON_10 + datetime.timedelta(hours=40))["state"] == "risk"
    late = S.sla_status(t, now=MON_10 + datetime.timedelta(hours=50))
    assert late["state"] == "late" and "2 h" in late["label"]


# --- Suivis et droits ------------------------------------------------------------------------

def test_client_cannot_write_internal_note(w):
    t = new(w)
    with pytest.raises(PermissionDenied):
        S.add_comment(w["a_rw"], t, "test", internal=True, now=MON_10)


def test_attachment_rules(w):
    t = new(w)
    ok = SimpleUploadedFile("capture.png", b"\x89PNG data", content_type="image/png")
    c = S.add_comment(w["a_rw"], t, "", files=[ok], now=MON_10)
    assert c.attachments.get().sha256
    with pytest.raises(ValidationError):
        S.add_comment(w["a_rw"], t, "x", files=[SimpleUploadedFile("outil.exe", b"MZ")], now=MON_10)


def test_assign_only_to_technician_with_access(w):
    t = new(w)
    with pytest.raises(ValidationError):
        S.assign(w["tech"], t, w["tech2"])   # tech2 n'est affecté qu'au contrat du client B
    S.assign(w["tech"], t, w["tech"])
    assert t.assignee == w["tech"]
    with pytest.raises(PermissionDenied):
        S.assign(w["a_rw"], t, w["tech"])


def test_visible_tickets_isolation(w):
    ta = new(w)
    tb = S.create_ticket(w["b_rw"], w["cb"], "Serveur B", "Panne", now=MON_10)
    refs = lambda u: set(S.visible_tickets(u).values_list("reference", flat=True))
    assert refs(w["a_rw"]) == {ta.reference}
    assert refs(w["b_rw"]) == {tb.reference}
    assert refs(w["tech2"]) == {tb.reference}
    assert refs(w["tech"]) == {ta.reference, tb.reference}
    with pytest.raises(PermissionDenied):
        S.add_comment(w["b_rw"], ta, "intrusion", now=MON_10)
