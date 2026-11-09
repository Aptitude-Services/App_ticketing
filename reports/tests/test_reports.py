"""Rapports curatif, préventif, trimestriel : référence, extraction, circuit de validation, envoi."""
import datetime
from zoneinfo import ZoneInfo

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.models import Organisation, Profile, User
from contracts.models import Contract, ContractType, LicenseNotice, Solution
from contracts.notifications import notify_expiring_licenses, threshold_for
from reports import services as R
from reports.builders import control_counts, quarter_bounds
from reports.forms import ReportContentForm, parse_lines
from reports.models import Report
from tickets import services as T
from tickets.models import Status

pytestmark = pytest.mark.django_db
TZ = ZoneInfo("Africa/Abidjan")
SECTOR = Organisation.ActivitySector.BANK
MON_10 = datetime.datetime(2026, 11, 2, 10, tzinfo=TZ)


@pytest.fixture
def w(client, monkeypatch):
    from accounts.middleware import MFARequiredMiddleware
    monkeypatch.setattr(MFARequiredMiddleware, "__call__", lambda self, request: self.get_response(request))
    apt = Organisation.objects.create(name="Aptitude Services", kind=Organisation.Kind.APTITUDE)
    esn = Organisation.objects.create(name="Hudson", code="HUD", kind=Organisation.Kind.CLIENT)
    end = Organisation.objects.create(name="Banque Lagune", code="BLAG", kind=Organisation.Kind.END_CLIENT,
                                      activity_sector=SECTOR)
    esn.end_clients.add(end)
    contract = Contract.objects.create(title="Support", client=esn, start_date=datetime.date(2026, 1, 1),
                                       contract_type=ContractType.objects.get(name="Standard 24x7"))
    contract.end_clients.add(end)
    sol = Solution.objects.create(contract=contract, category="hardware", name="FW-01")

    def mk(email, org, profile, **kw):
        return User.objects.create_user(email, "Motdepasse-tres-long-1", organisation=org, profile=profile, **kw)

    boss = mk("boss@apt.ci", apt, Profile.APTITUDE_MANAGER, first_name="Chef")
    other_mgr = mk("mgr2@apt.ci", apt, Profile.APTITUDE_MANAGER)
    tech = mk("tech@apt.ci", apt, Profile.TECH_ALL, first_name="Camille", manager=boss)
    esn_admin = mk("admin@hudson.ci", esn, Profile.CLIENT_ADMIN)
    end_user = mk("it@blag.ci", end, Profile.CLIENT_RW)
    ticket = T.create_ticket(end_user, contract, "VPN coupé", "Plus d'accès VPN", solutions=[sol], now=MON_10)
    T.assign(tech, ticket, tech, now=MON_10 + datetime.timedelta(minutes=5))
    T.change_status(tech, ticket, Status.IN_PROGRESS, now=MON_10 + datetime.timedelta(minutes=10))
    T.change_status(tech, ticket, Status.RESOLVED, now=MON_10 + datetime.timedelta(hours=2))
    return {"esn": esn, "end": end, "contract": contract, "ticket": ticket, "tech": tech, "boss": boss,
            "other_mgr": other_mgr, "esn_admin": esn_admin, "end_user": end_user, "client": client, "sol": sol}


def _curative(w):
    return R.create_report(w["tech"], Report.Kind.CURATIVE, w["contract"], end_client=w["end"], ticket=w["ticket"])


# --- Référence et extraction ----------------------------------------------------------------------

def test_reference_identifies_esn_and_end_client(w):
    r = _curative(w)
    assert r.reference == "RPT-CUR-HUD-BLAG-2026-001"
    assert _curative(w).reference == "RPT-CUR-HUD-BLAG-2026-002"
    q = R.create_report(w["tech"], Report.Kind.QUARTERLY, w["contract"], end_client=w["end"], year=2026, quarter=4)
    assert q.reference == "RPT-TRI-HUD-BLAG-2026T4-001"


def test_curative_extracts_ticket_and_contract(w):
    r = _curative(w)
    auto = R.auto_data(r)
    assert auto["esn"] == "Hudson" and auto["end_client"] == "Banque Lagune"
    assert auto["contract_ref"] == w["contract"].reference
    assert auto["ticket"]["reference"] == w["ticket"].reference
    assert auto["ticket"]["solutions"] == ["FW-01"]
    assert auto["ticket"]["resolution"]["met"] is True
    assert r.data["symptoms"] == "Plus d'accès VPN"
    assert r.data["timeline"], "chronologie préremplie depuis l'historique"


def test_preventive_prefills_equipments_and_controls(w):
    r = R.create_report(w["tech"], Report.Kind.PREVENTIVE, w["contract"], end_client=w["end"])
    assert r.data["equipments"] == [["FW-01"]]
    assert len(r.data["controls"]) > 10


def test_content_form_stores_lines(w):
    r = R.create_report(w["tech"], Report.Kind.PREVENTIVE, w["contract"], end_client=w["end"])
    form = ReportContentForm({"site": "Siège", "controls": "Sécurité | MFA | Annuaire | Conforme | ok\n"
                                                        "Sécurité | TLS | Portail | Non conforme | 12 j"},
                             report=r)
    assert form.is_valid(), form.errors
    form.apply()
    assert r.data["site"] == "Siège"
    counts = control_counts(r.data["controls"])
    assert (counts["total"], counts["ok"], counts["ko"]) == (2, 1, 1)


def test_parse_lines_pads_and_keeps_extra_pipes():
    assert parse_lines("a | b\n\nc", 3) == [["a", "b", ""], ["c", "", ""]]
    assert parse_lines("a | b | c | d", 3) == [["a", "b", "c | d"]]


# --- Circuit de validation ---------------------------------------------------------------------------

def test_author_cannot_validate_own_report(w):
    r = _curative(w)
    R.submit(w["tech"], r)
    assert not R.can_validate(w["tech"], r)
    with pytest.raises(PermissionDenied):
        R.validate(w["tech"], r)


def test_only_the_authors_manager_validates(w):
    r = _curative(w)
    mail.outbox.clear()
    R.submit(w["tech"], r)
    assert mail.outbox[0].to == ["boss@apt.ci"]
    assert not R.can_validate(w["other_mgr"], r)
    R.validate(w["boss"], r)
    r.refresh_from_db()
    assert r.status == Report.Status.VALIDATED and r.fingerprint
    assert "snapshot" in r.data and not R.can_edit(w["tech"], r)


def test_cannot_send_before_validation(w):
    r = _curative(w)
    R.submit(w["tech"], r)
    with pytest.raises(PermissionDenied):
        R.send_to_client(w["boss"], r)


def test_reject_then_resubmit(w):
    r = _curative(w)
    R.submit(w["tech"], r)
    R.reject(w["boss"], r, "Compléter le diagnostic")
    assert r.status == Report.Status.REJECTED and R.can_edit(w["tech"], r)
    R.submit(w["tech"], r)
    assert r.status == Report.Status.SUBMITTED and r.rejection_comment == ""


def test_sent_report_reaches_esn_and_is_visible_to_clients(w):
    r = _curative(w)
    assert not R.visible_reports(w["esn_admin"]).exists()
    R.submit(w["tech"], r)
    R.validate(w["boss"], r)
    assert not R.visible_reports(w["end_user"]).exists(), "invisible tant qu'il n'est pas envoyé"
    mail.outbox.clear()
    recipients = R.send_to_client(w["boss"], r)
    assert "admin@hudson.ci" in recipients
    assert mail.outbox and r.reference in mail.outbox[0].subject
    assert R.visible_reports(w["esn_admin"]).filter(pk=r.pk).exists()
    assert R.visible_reports(w["end_user"]).filter(pk=r.pk).exists()
    R.client_confirm(w["end_user"], r)
    assert r.client_validated_by == w["end_user"]


# --- Trimestriel ---------------------------------------------------------------------------------------

def test_quarterly_consolidates_tickets_and_reports(w):
    prev = R.create_report(w["tech"], Report.Kind.PREVENTIVE, w["contract"], end_client=w["end"])
    prev.data.update({"site": "Siège", "started_at": "2026-11-04T09:00",
                      "controls": [["Sécurité", "MFA", "", "Conforme", ""], ["Sécurité", "TLS", "", "Non conforme", ""]],
                      "recommendations": [["Renouveler le certificat", "Haute", "Support", "", ""]]})
    prev.save()
    R.submit(w["tech"], prev)
    R.validate(w["boss"], prev)
    cur = _curative(w)
    cur.data["diagnosis_category"] = "Configuration"
    cur.save()
    R.submit(w["tech"], cur)
    R.validate(w["boss"], cur)

    q = R.create_report(w["tech"], Report.Kind.QUARTERLY, w["contract"], end_client=w["end"], year=2026, quarter=4)
    auto = R.auto_data(q)
    assert (auto["tickets_total"], auto["tickets_resolved"]) == (1, 1)
    assert auto["visits_done"] == 1 and auto["anomalies"] == 1
    assert auto["causes"][0]["name"] == "Configuration"
    assert ["Renouveler le certificat", "Support"] == q.data["pending"][0][:2]


def test_quarter_bounds():
    assert quarter_bounds(2026, 3) == (datetime.date(2026, 7, 1), datetime.date(2026, 9, 30))
    assert quarter_bounds(2026, 4) == (datetime.date(2026, 10, 1), datetime.date(2026, 12, 31))


# --- Pages ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["curatif", "preventif", "trimestriel"])
def test_pages_render(w, kind):
    c = w["client"]
    c.force_login(w["tech"])
    assert c.get(reverse("report", args=[kind])).status_code == 200
    assert c.get(reverse("report_create", args=[kind])).status_code == 200
    if kind == "curatif":
        r = _curative(w)
    else:
        r = R.create_report(w["tech"], kind, w["contract"], end_client=w["end"], year=2026, quarter=4)
    assert c.get(reverse("report_edit", args=[r.pk])).status_code == 200
    resp = c.get(reverse("report_detail", args=[r.pk]))
    assert resp.status_code == 200 and r.reference in resp.content.decode()


def test_create_view_builds_curative_from_ticket(w):
    c = w["client"]
    c.force_login(w["tech"])
    resp = c.post(reverse("report_create", args=["curatif"]),
                  {"ticket": f"{w['ticket'].pk}:{w['end'].pk}"})
    r = Report.objects.get()
    assert resp.status_code == 302 and r.ticket == w["ticket"] and r.end_client == w["end"]


def test_client_cannot_open_unsent_report(w):
    r = _curative(w)
    c = w["client"]
    c.force_login(w["esn_admin"])
    assert c.get(reverse("report_detail", args=[r.pk])).status_code == 404
    assert c.get(reverse("report_create", args=["curatif"])).status_code == 403


def test_esn_logo_is_embedded(w):
    w["esn"].logo = SimpleUploadedFile("logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>",
                                       content_type="image/svg+xml")
    w["esn"].save()
    r = _curative(w)
    c = w["client"]
    c.force_login(w["tech"])
    assert "data:image/svg+xml;base64," in c.get(reverse("report_detail", args=[r.pk])).content.decode()


# --- ESN et licences --------------------------------------------------------------------------------------

def test_esn_needs_no_sector_but_end_client_does():
    Organisation(name="ESN X", kind=Organisation.Kind.CLIENT).full_clean()
    with pytest.raises(Exception):
        Organisation(name="Final X", kind=Organisation.Kind.END_CLIENT).full_clean()


def test_license_thresholds():
    assert [threshold_for(d) for d in (75, 60, 45, 20, 10, 3, 0)] == [None, 60, 60, 30, 15, 7, 0]


def test_license_expiry_notifies_esn_once_per_threshold(w):
    today = datetime.date(2026, 11, 9)
    w["sol"].license_end = today + datetime.timedelta(days=25)
    w["sol"].save()
    mail.outbox.clear()
    assert notify_expiring_licenses(today) == (1, 1)
    assert mail.outbox[0].to == ["admin@hudson.ci"] and "FW-01" in mail.outbox[0].body
    assert notify_expiring_licenses(today) == (0, 0), "pas de doublon au même seuil"
    assert notify_expiring_licenses(today + datetime.timedelta(days=12)) == (1, 1), "nouveau seuil : J-15"
    assert LicenseNotice.objects.count() == 2


def test_admin_action_notifies_esn(w, client):
    w["sol"].license_end = datetime.date(2026, 12, 1)
    w["sol"].save()
    admin = User.objects.create_superuser("root@aptitudes.net", "Motdepasse-tres-long-1")
    client.force_login(admin)
    mail.outbox.clear()
    resp = client.post(reverse("admin:contracts_solution_changelist"),
                       {"action": "notify_esn", "_selected_action": [w["sol"].pk]})
    assert resp.status_code == 302
    assert mail.outbox and mail.outbox[0].to == ["admin@hudson.ci"]
    assert LicenseNotice.objects.get().manual
