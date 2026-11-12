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
    apt = Organisation.objects.create(name="Aptitude Services", kind=Organisation.Kind.CLIENT, is_operator=True)
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
    form = ReportContentForm({"periodicity": "trimestrielle", "controls": "Sécurité | MFA | Annuaire | Conforme | ok\n"
                                                        "Sécurité | TLS | Portail | Non conforme | 12 j"},
                             report=r)
    assert form.is_valid(), form.errors
    form.apply()
    assert r.data["periodicity"] == "trimestrielle"
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
    recipients, mailed = R.send_to_client(w["boss"], r)
    assert mailed
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
    assert ["Renouveler le certificat", "Support"] == auto["derived"]["pending"][0][:2]


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
    """Trois alertes : 5 mois, 3 mois puis 1 mois avant l'échéance (mois calendaires)."""
    end = datetime.date(2027, 6, 15)
    cases = {datetime.date(2027, 1, 14): None, datetime.date(2027, 1, 15): 150, datetime.date(2027, 3, 14): 150,
             datetime.date(2027, 3, 15): 90, datetime.date(2027, 5, 15): 30, end: 30,
             datetime.date(2027, 6, 16): None}
    assert {day: threshold_for(end, day) for day in cases} == cases


def test_license_expiry_notifies_esn_once_per_threshold(w):
    today = datetime.date(2026, 11, 9)
    w["sol"].license_end = datetime.date(2027, 4, 1)  # moins de 5 mois
    w["sol"].save()
    mail.outbox.clear()
    assert notify_expiring_licenses(today) == (1, 1)
    assert "admin@hudson.ci" in mail.outbox[0].to and "FW-01" in mail.outbox[0].body
    assert notify_expiring_licenses(today) == (0, 0), "pas de doublon au même seuil"
    assert notify_expiring_licenses(today + datetime.timedelta(days=30)) == (0, 0), "toujours le seuil des 5 mois"
    assert notify_expiring_licenses(datetime.date(2027, 1, 1)) == (1, 1), "nouveau seuil : 3 mois"
    assert notify_expiring_licenses(datetime.date(2027, 3, 1)) == (1, 1), "dernier seuil : 1 mois"
    assert notify_expiring_licenses(datetime.date(2027, 3, 20)) == (0, 0), "trois alertes en tout"
    assert sorted(LicenseNotice.objects.values_list("threshold", flat=True)) == [30, 90, 150]


def test_license_alert_goes_to_esn_end_client_and_managers(w):
    end = Organisation.objects.create(name="Final Licences", kind=Organisation.Kind.END_CLIENT,
                                      activity_sector=Organisation.ActivitySector.BANK)
    w["sol"].contract.client.end_clients.add(end)
    w["sol"].contract.end_clients.add(end)
    User.objects.create_user("dsi@final.ci", organisation=end, profile=Profile.CLIENT_ADMIN)
    w["sol"].license_end = datetime.date(2026, 12, 1)
    w["sol"].save()
    mail.outbox.clear()
    assert notify_expiring_licenses(datetime.date(2026, 11, 9)) == (1, 1)
    internal, to_client = mail.outbox
    managers = set(User.objects.filter(profile=Profile.APTITUDE_MANAGER, is_active=True)
                   .values_list("email", flat=True))
    # Interne : vendeur + managers, invités à envoyer l'offre ; le client n'y figure pas.
    assert managers and {"admin@hudson.ci"} | managers <= set(internal.to)
    assert "dsi@final.ci" not in internal.to
    assert internal.subject.startswith("[Action requise] Offre de renouvellement à envoyer")
    assert "Action attendue" in internal.body and "Client prévenu" in internal.body
    assert "dsi@final.ci" in internal.body and "Vendeur" in internal.body
    # Client : seul destinataire, annonce de l'offre, sans adresse interne.
    assert "dsi@final.ci" in to_client.to and not (managers | {"admin@hudson.ci"}) & set(to_client.to)
    assert to_client.subject == "Expiration prochaine de votre licence"
    body = to_client.body
    assert "nous vous ferons parvenir une offre de renouvellement" in body
    assert "dans 22 jours" in body and "jour(s)" not in body and "Pensez à engager" not in body
    assert "Action attendue" not in body and "Vendeur" not in body


def test_admin_action_notifies_esn(w, client):
    w["sol"].license_end = datetime.date(2026, 12, 1)
    w["sol"].save()
    admin = User.objects.create_superuser("root@aptitudes.net", "Motdepasse-tres-long-1")
    client.force_login(admin)
    mail.outbox.clear()
    resp = client.post(reverse("admin:contracts_solution_changelist"),
                       {"action": "notify_esn", "_selected_action": [w["sol"].pk]})
    assert resp.status_code == 302
    assert mail.outbox and "admin@hudson.ci" in mail.outbox[0].to
    assert LicenseNotice.objects.get().manual


# --- Messagerie en panne : le circuit continue ---------------------------------------------------------

def _broken_mail(*args, **kwargs):
    raise RuntimeError("HTTP 404 ErrorInvalidUser")


def test_mail_failure_does_not_block_the_report(w, monkeypatch):
    monkeypatch.setattr(R, "send_mail", _broken_mail)
    r = _curative(w)
    validators, mailed = R.submit(w["tech"], r)
    assert r.status == Report.Status.SUBMITTED and validators and not mailed
    assert R.reject(w["boss"], r, "À revoir") is False and r.status == Report.Status.REJECTED
    R.submit(w["tech"], r)
    R.validate(w["boss"], r)
    recipients, mailed = R.send_to_client(w["boss"], r)
    assert r.status == Report.Status.SENT and recipients and not mailed


def test_submit_view_warns_instead_of_crashing_when_mail_fails(w, monkeypatch):
    monkeypatch.setattr(R, "send_mail", _broken_mail)
    r = _curative(w)
    c = w["client"]
    c.force_login(w["tech"])
    resp = c.post(reverse("report_edit", args=[r.pk]), {"submit": ""}, follow=True)
    assert resp.status_code == 200
    r.refresh_from_db()
    assert r.status == Report.Status.SUBMITTED
    assert "pas pu partir" in resp.content.decode()


def test_license_alert_retried_when_mail_fails(w, monkeypatch):
    import contracts.notifications as N
    today = datetime.date(2026, 11, 9)
    w["sol"].license_end = today + datetime.timedelta(days=10)
    w["sol"].save()
    monkeypatch.setattr(N, "send_mail", _broken_mail)
    assert notify_expiring_licenses(today) == (0, 0)
    assert not LicenseNotice.objects.exists(), "rien n'est tracé : l'alerte sera retentée"


# --- Chronologie : date | heure | action -------------------------------------------------------------

def test_timeline_prefilled_as_date_time_action(w):
    r = _curative(w)
    first = r.data["timeline"][0]
    assert first[0] == "2026-11-02" and first[1] == "10:00" and "Ouverture du ticket" in first[2]


def test_timeline_is_normalised_and_validated(w):
    r = _curative(w)
    form = ReportContentForm({"timeline": "04/11/2026 | 8:42 | Ouverture\n2026-11-04 | 09:10 | Correctif"}, report=r)
    assert form.is_valid(), form.errors
    form.apply()
    assert r.data["timeline"] == [["2026-11-04", "08:42", "Ouverture"], ["2026-11-04", "09:10", "Correctif"]]
    bad = ReportContentForm({"timeline": "31/02/2026 | 25:00 |"}, report=r)
    assert not bad.is_valid()
    assert len(bad.errors["timeline"]) == 3, "date, heure et action signalées"


def test_old_two_column_timeline_is_converted(w):
    r = _curative(w)
    r.data["timeline"] = [["04/11 08:42", "Ouverture du ticket"]]
    form = ReportContentForm(report=r)
    assert form.initial["timeline"] == "2026-11-04 | 08:42 | Ouverture du ticket"


def test_edit_page_offers_the_timeline_table(w):
    c = w["client"]
    c.force_login(w["tech"])
    page = c.get(reverse("report_edit", args=[_curative(w).pk])).content.decode()
    assert "data-row-editor" in page and "js/row_editor.js" in page and "Ajouter une étape" in page


# --- Améliorations : en-tête, pied de page, fonction, couleur, trimestriel ------------------------------

def test_report_page_has_short_footer_and_no_fingerprint_text(w):
    r = _curative(w)
    R.submit(w["tech"], r)
    R.validate(w["boss"], r)
    c = w["client"]
    c.force_login(w["tech"])
    html = c.get(reverse("report_detail", args=[r.pk])).content.decode()
    assert "Hudson — Document confidentiel</span>" in html
    assert "prestataires désignés" not in html and "Support opéré par" not in html
    assert "SHA-256" not in html and "toute modification crée une nouvelle version" not in html
    assert "Rapport d&#x27;intervention · Maintenance curative" not in html
    assert html.count("Rapport de maintenance curative") == 2  # page de garde + en-tête de page


def test_engineer_title_comes_from_the_user_profile(w):
    w["tech"].job_title = "Ingénieure support N2"
    w["tech"].save()
    r = _curative(w)
    assert R.auto_data(r)["technician_title"] == "Ingénieure support N2"
    assert "technician_title" not in ReportContentForm(report=r).fields
    c = w["client"]
    c.force_login(w["tech"])
    assert "Camille, Ingénieure support N2" in c.get(reverse("report_detail", args=[r.pk])).content.decode()


def test_engineer_title_defaults_to_profile(w):
    assert R.auto_data(_curative(w))["author_title"] == "Ingénieur support"


def test_report_uses_esn_brand_color(w):
    w["esn"].brand_color = "#1F6FB2"
    w["esn"].save()
    c = w["client"]
    c.force_login(w["tech"])
    html = c.get(reverse("report_detail", args=[_curative(w).pk])).content.decode()
    assert "--accent: #1F6FB2" in html


def test_quarterly_ignores_tickets_without_intervention_report(w):
    """Le trimestriel ne reprend que les tickets couverts par un rapport curatif validé."""
    q = R.create_report(w["tech"], Report.Kind.QUARTERLY, w["contract"], end_client=w["end"], year=2026, quarter=4)
    assert R.auto_data(q)["tickets_total"] == 0, "ticket sans rapport : non repris"
    cur = _curative(w)
    R.submit(w["tech"], cur)
    R.validate(w["boss"], cur)
    assert R.auto_data(q)["tickets_total"] == 1


def test_controls_use_the_one_click_editor(w):
    r = R.create_report(w["tech"], Report.Kind.PREVENTIVE, w["contract"], end_client=w["end"])
    import json
    widget = ReportContentForm(report=r).fields["controls"].widget
    conf = json.loads(widget.attrs["data-controls-editor"])
    assert conf["results"] == ["Conforme", "À surveiller", "Non conforme", "N/A"]
    assert conf["equipments"] == ["FW-01"]


def test_quarterly_needs_no_input_everything_comes_from_intervention_reports(w):
    """Le trimestriel se remplit à partir des rapports curatifs et préventifs validés."""
    prev = R.create_report(w["tech"], Report.Kind.PREVENTIVE, w["contract"], end_client=w["end"])
    prev.data.update({"site": "Siège", "started_at": "2026-11-04T09:00", "visit_total": 4,
                      "controls": [["Sécurité", "TLS", "Portail", "Non conforme", ""]],
                      "operations": [["09:30", "Mise à jour du firmware", "FW-01"]],
                      "recommendations": [["Renouveler le certificat", "Haute", "Support", "30/11/2026", ""]]})
    prev.save()
    R.submit(w["tech"], prev)
    R.validate(w["boss"], prev)
    cur = _curative(w)
    cur.data.update({"interruption": "2 h 50", "fix_state": "Appliquée", "fix": "Certificat renouvelé",
                     "followups": [["Superviser l'expiration", "Exploitation", "15/12/2026", ""]]})
    cur.save()
    R.submit(w["tech"], cur)
    R.validate(w["boss"], cur)

    q = R.create_report(w["tech"], Report.Kind.QUARTERLY, w["contract"], end_client=w["end"], year=2026, quarter=4)
    d = R.auto_data(q)["derived"]
    assert d["visits_planned"] == 4
    assert d["availability"] == "99,87"  # 170 min d'interruption sur 92 jours
    assert ["Mise à jour du firmware (FW-01)"] in d["done_actions"]
    assert any("Certificat renouvelé" in row[0] for row in d["done_actions"])
    assert any(row[0].startswith("Non conforme : TLS") for row in d["attention"])
    assert d["recommendations"][0][:3] == ["Renouveler le certificat", f"Visite {prev.reference}", "élevé"]
    assert [row[0] for row in d["action_plan"]] == ["Renouveler le certificat", "Superviser l'expiration"]
    assert d["next_point"] == "Prochain point : rapport trimestriel T1 2027."

    c = w["client"]
    c.force_login(w["tech"])
    page = c.get(reverse("report_detail", args=[q.pk])).content.decode()
    assert "Mise à jour du firmware" in page and "Superviser l&#x27;expiration" in page and "99,87 %" in page
    assert "highlights" not in ReportContentForm(report=q).fields, "plus rien à saisir hormis les ajustements"

    # Une valeur saisie remplace la valeur déduite ; à la validation, le contenu est figé dans le rapport.
    q.data["availability"] = "99,5"
    q.save()
    R.submit(w["tech"], q)
    R.validate(w["boss"], q)
    q.refresh_from_db()
    assert q.data["availability"] == "99,5" and q.data["action_plan"] == d["action_plan"]


# --- Paramètres des alertes de licence (administration) ----------------------------------------------

def _conf(**kw):
    from contracts.models import LicenseAlertSettings
    conf = LicenseAlertSettings.get()
    for k, v in kw.items():
        setattr(conf, k, v)
    conf.full_clean()
    conf.save()
    return conf


def test_license_settings_change_number_and_spacing_of_reminders(w):
    """Deux rappels en jours (30 et 7) au lieu de trois en mois."""
    _conf(thresholds="7, 30", unit="days")
    end = datetime.date(2027, 3, 31)
    assert threshold_for(end, datetime.date(2027, 2, 28)) is None
    assert threshold_for(end, datetime.date(2027, 3, 1)) == 30
    assert threshold_for(end, datetime.date(2027, 3, 24)) == 7
    w["sol"].license_end = end
    w["sol"].save()
    assert notify_expiring_licenses(datetime.date(2027, 1, 1)) == (0, 0), "plus de rappel à 5 mois"
    assert notify_expiring_licenses(datetime.date(2027, 3, 2)) == (1, 1)
    assert notify_expiring_licenses(datetime.date(2027, 3, 25)) == (1, 1)
    assert sorted(LicenseNotice.objects.values_list("threshold", flat=True)) == [7, 30]


def test_license_alerts_can_be_switched_off(w):
    _conf(enabled=False)
    w["sol"].license_end = datetime.date(2026, 12, 1)
    w["sol"].save()
    assert notify_expiring_licenses(datetime.date(2026, 11, 9)) == (0, 0)


def test_license_alert_recipients_follow_settings(w):
    _conf(notify_managers=False)
    w["sol"].license_end = datetime.date(2026, 12, 1)
    w["sol"].save()
    mail.outbox.clear()
    notify_expiring_licenses(datetime.date(2026, 11, 9))
    assert [m.to for m in mail.outbox] == [["admin@hudson.ci"], ["it@blag.ci"]], \
        "ESN (interne) puis client final, sans les managers"


def test_license_delay_wording():
    from contracts.notifications import _when
    assert [_when(d) for d in (0, 1, 10)] == ["aujourd'hui", "demain", "dans 10 jours"]


@pytest.mark.parametrize("bad", ["", "5, -1", "trois", "30"])
def test_license_settings_reject_bad_thresholds(bad):
    from django.core.exceptions import ValidationError
    from contracts.models import LicenseAlertSettings
    conf = LicenseAlertSettings.get()
    conf.thresholds = bad
    with pytest.raises(ValidationError):
        conf.full_clean()


def test_license_settings_admin_page(w, client):
    admin = User.objects.create_superuser("root@aptitudes.net", "Motdepasse-tres-long-1")
    client.force_login(admin)
    listing = client.get(reverse("admin:contracts_licensealertsettings_changelist"))
    assert listing.status_code == 302, "la liste ouvre directement la fiche unique"
    page = client.get(listing["Location"]).content.decode()
    assert "Seuils de rappel" in page and "3 rappel(s) : 5 mois, 3 mois, 1 mois" in page
    assert "Jamais" in page, "le planificateur n'est pas encore passé"
    data = {"enabled": "on", "thresholds": "6, 2", "unit": "months", "notify_esn": "on",
            "notify_end_client": "on", "start_hour": 8, "end_hour": 17}
    assert client.post(listing["Location"], data).status_code == 302
    from contracts.models import LicenseAlertSettings
    conf = LicenseAlertSettings.get()
    assert (conf.thresholds, conf.notify_managers, conf.start_hour) == ("6, 2", False, 8)



def test_site_comes_from_solution_location_not_typed(w):
    """Le site n'est plus saisi : il vient de la « localisation » des solutions."""
    w["sol"].location = "Salle serveurs Plateau"
    w["sol"].save()
    cur = _curative(w)
    assert "site" not in ReportContentForm(report=cur).fields
    assert R.auto_data(cur)["site"] == "Salle serveurs Plateau"
    Solution.objects.create(contract=w["contract"], category="software", name="VPN", location="Agence Cocody")
    prev = R.create_report(w["tech"], Report.Kind.PREVENTIVE, w["contract"], end_client=w["end"])
    assert "site" not in ReportContentForm(report=prev).fields
    assert R.auto_data(prev)["site"] == "Salle serveurs Plateau, Agence Cocody"
    c = w["client"]
    c.force_login(w["tech"])
    assert "Salle serveurs Plateau" in c.get(reverse("report_detail", args=[cur.pk])).content.decode()
    assert "Salle serveurs Plateau" in c.get(reverse("report_edit", args=[cur.pk])).content.decode()
    # Figé à la validation, et repris par le trimestriel.
    R.submit(w["tech"], cur)
    R.validate(w["boss"], cur)
    q = R.create_report(w["tech"], Report.Kind.QUARTERLY, w["contract"], end_client=w["end"], year=2026, quarter=4)
    assert {"name": "Salle serveurs Plateau", "count": 1} in R.auto_data(q)["sites"]


def test_site_typed_in_old_reports_is_kept(w):
    cur = _curative(w)
    cur.data["site"] = "Siège"
    cur.save()
    assert R.auto_data(cur)["site"] == "Siège"
