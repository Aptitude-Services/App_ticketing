"""Parcours complet, de bout en bout, joué par les écrans comme en démonstration.

Chaque acteur a sa propre session (son propre « navigateur ») et passe par les vraies
pages : administration, portail client, console Aptitude, rapports.

  1. Super Admin Aptitude : ESN (avec logo), client final, contrat, comptes.
  2. Admin de l'ESN : crée l'utilisateur de son client final.
  3. Utilisateur du client final : ouvre un ticket, ne voit que son périmètre.
  4. Ingénieur Aptitude : prend en charge, échange avec le client, note interne, résout.
  5. Rapport curatif : rédigé par l'ingénieur, validé par son supérieur, envoyé, confirmé.
  6. Rapports préventif et trimestriel, alerte d'expiration de licence.

La double authentification est testée ailleurs (test_mfa) : elle est neutralisée ici.
"""
import datetime
import re

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Organisation, Profile, User
from contracts.models import Contract, ContractType, LicenseNotice, Solution
from contracts.notifications import notify_expiring_licenses
from reports.models import Report
from tickets.models import Status, Ticket

pytestmark = pytest.mark.django_db
PASSWORD = "Motdepasse-tres-long-1"
LOGO = b"<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'/>"


@pytest.fixture(autouse=True)
def no_mfa(monkeypatch):
    from accounts.middleware import MFARequiredMiddleware
    monkeypatch.setattr(MFARequiredMiddleware, "__call__", lambda self, request: self.get_response(request))


def session(user):
    c = Client()
    c.force_login(user)
    return c


def ok(resp, code=200):
    assert resp.status_code == code, f"{resp.status_code} attendu {code} : {resp.content[:800]!r}"
    return resp


def text(resp):
    return resp.content.decode()


def test_parcours_complet():
    # ================================================================== 1. Mise en place (Super Admin)
    Organisation.objects.create(name="Aptitude Services", kind=Organisation.Kind.CLIENT, is_operator=True)
    root = User.objects.create_superuser("admin@aptitudes.net", PASSWORD, first_name="Super", last_name="Admin")
    admin = session(root)

    # ESN avec son logo, sans secteur d'activité
    ok(admin.post(reverse("admin:accounts_organisation_add"), {
        "name": "Hudson IT", "kind": "client", "activity_sector": "", "email_domains": "hudson.ci",
        "is_active": "on", "logo": SimpleUploadedFile("hudson.svg", LOGO, content_type="image/svg+xml"),
    }), 302)
    esn = Organisation.objects.get(name="Hudson IT")
    assert esn.logo and esn.activity_sector == "" and esn.code

    # Client final, créé depuis la fiche de l'ESN (secteur demandé)
    ok(admin.post(reverse("admin:accounts_organisation_add_end_client", args=[esn.pk]),
                  {"name": "Banque Lagune", "activity_sector": "bank", "email_domains": "blag.ci"}), 302)
    end = Organisation.objects.get(name="Banque Lagune")
    assert end in esn.end_clients.all()

    # Une autre ESN, pour vérifier le cloisonnement
    other_esn = Organisation.objects.create(name="Autre ESN", kind=Organisation.Kind.CLIENT)
    other_end = Organisation.objects.create(name="Autre Client", kind=Organisation.Kind.END_CLIENT,
                                            activity_sector="health")
    other_esn.end_clients.add(other_end)
    gold = ContractType.objects.get(name="GOLD")  # SLA 24x7 : ticket possible à toute heure
    other_contract = Contract.objects.create(title="Autre", client=other_esn, start_date=datetime.date(2026, 1, 1),
                                             contract_type=gold)
    other_contract.end_clients.add(other_end)

    # Contrat : ESN + client final (liste déroulante) + une solution saisie dans le tableau
    page = ok(admin.get(reverse("admin:contracts_contract_add")))
    assert '<select name="end_clients"' in text(page)
    ok(admin.post(reverse("admin:contracts_contract_add"), {
        "title": "Support SOC", "client": esn.pk, "end_clients": end.pk, "contract_type": gold.pk,
        "status": "active", "start_date": "2026-01-01", "end_date": "", "allowance_tickets": "",
        "solutions-TOTAL_FORMS": "1", "solutions-INITIAL_FORMS": "0",
        "solutions-0-category": "hardware", "solutions-0-name": "FW-LYN-01", "solutions-0-vendor": "Fortinet",
        "solutions-0-license_end": (timezone.localdate() + datetime.timedelta(days=20)).strftime("%d/%m/%Y"),
        "solutions-0-is_active": "on",
        "accesses-TOTAL_FORMS": "0", "accesses-INITIAL_FORMS": "0",
    }), 302)
    contract = Contract.objects.get(title="Support SOC")
    today = timezone.localdate()
    # 2e contrat créé aujourd'hui (le contrat de l'autre ESN est le 1er)
    assert contract.reference == f"APT2-{today:%d%m}/COM/{today:%Y}"
    firewall = Solution.objects.get(contract=contract, name="FW-LYN-01")

    # Équipe Aptitude : un Manager, supérieur d'un Engineer ; un autre Manager
    def team(email, profile, manager=None):
        ok(admin.post(reverse("user_create") + "?type=equipe", {
            "email": email, "first_name": email.split("@")[0].capitalize(), "last_name": "Aptitude",
            "language": "fr", "organisation": Organisation.objects.get(kind="client", is_operator=True).pk,
            "profile": profile, "manager": manager.pk if manager else "", "all_contracts": "on", "is_active": "on",
        }), 302)
        return User.objects.get(email=email)

    manager = team("chef@aptitudes.net", Profile.APTITUDE_MANAGER)
    manager2 = team("autre.chef@aptitudes.net", Profile.APTITUDE_MANAGER)
    # Le supérieur se choisit sur la fiche de l'ingénieur (Équipe interne)
    assert "Supérieur hiérarchique" in text(ok(admin.get(reverse("user_create") + "?type=equipe")))
    engineer = team("ingenieur@aptitudes.net", Profile.TECH_ALL, manager=manager)
    assert engineer.manager == manager

    # Admin de l'ESN, créé par Aptitude
    ok(admin.post(reverse("user_create"), {
        "email": "admin@hudson.ci", "first_name": "Awa", "last_name": "Hudson", "language": "fr",
        "organisation": esn.pk, "profile": Profile.CLIENT_ADMIN, "all_contracts": "on", "is_active": "on",
    }), 302)
    esn_admin = User.objects.get(email="admin@hudson.ci")
    assert len(mail.outbox) >= 4, "un email d'invitation par compte créé"

    # ================================================================== 2. Admin de l'ESN
    esn_session = session(esn_admin)
    form = ok(esn_session.get(reverse("user_create")))
    assert "Banque Lagune" in text(form) and "Autre Client" not in text(form)
    for email, profile in (("it@blag.ci", Profile.CLIENT_RW), ("dg@blag.ci", Profile.CLIENT_RO)):
        ok(esn_session.post(reverse("user_create"), {
            "email": email, "first_name": "Julien", "last_name": "Lagune", "language": "fr",
            "organisation": end.pk, "profile": profile, "all_contracts": "on", "is_active": "on",
        }), 302)
    client_user = User.objects.get(email="it@blag.ci")
    reader = User.objects.get(email="dg@blag.ci")
    assert client_user.organisation == end and reader.organisation == end, "comptes rattachés au client final"
    # Accès limité à un contrat précis : le contrat du client final est proposé et attribué
    ok(esn_session.post(reverse("user_create"), {
        "email": "limite@blag.ci", "first_name": "L", "last_name": "Lagune", "language": "fr",
        "organisation": end.pk, "profile": Profile.CLIENT_RW, "is_active": "on", "contracts": [contract.pk],
    }), 302)
    limited = User.objects.get(email="limite@blag.ci")
    assert limited.organisation == end and not limited.all_contracts
    assert list(limited.contract_accesses.values_list("contract", flat=True)) == [contract.pk]
    # L'admin de l'ESN ne peut pas créer de compte chez un autre client
    resp = esn_session.post(reverse("user_create"), {
        "email": "pirate@autre.ci", "first_name": "P", "last_name": "X", "language": "fr",
        "organisation": other_end.pk, "profile": Profile.CLIENT_RW, "all_contracts": "on", "is_active": "on"})
    assert resp.status_code == 200 and not User.objects.filter(email="pirate@autre.ci").exists()
    stranger = User.objects.create_user("x@autre.ci", PASSWORD, organisation=other_end, profile=Profile.CLIENT_RW)

    # ================================================================== 3. Client final : ouvre un ticket
    portal = session(client_user)
    contracts_page = text(ok(portal.get(reverse("contract_list"))))
    assert contract.reference in contracts_page and other_contract.reference not in contracts_page
    form = text(ok(portal.get(reverse("ticket_create"))))
    assert "FW-LYN-01" in form
    mail.outbox.clear()
    resp = ok(portal.post(reverse("ticket_create"), {
        "contract": contract.pk, "solutions": [firewall.pk], "title": "VPN siège coupé",
        "description": "Plus aucun utilisateur ne se connecte au VPN depuis 8h.", "priority": "3",
    }), 302)
    ticket = Ticket.objects.get(title="VPN siège coupé")
    assert any(m.to == [client_user.email] and ticket.reference in m.subject for m in mail.outbox), "accusé de réception"
    assert any(engineer.email in m.to for m in mail.outbox), "l'équipe Aptitude est prévenue"
    assert ticket.requester == client_user and ticket.status == Status.NEW
    assert ticket.response_due and ticket.resolution_due, "échéances SLA calculées"
    ok(portal.get(resp["Location"]))
    detail_url = reverse("ticket_detail", args=[ticket.reference])

    # Cloisonnement : lecteur seul (voit, ne crée pas), client d'une autre ESN (ne voit rien)
    read_only = session(reader)
    ok(read_only.get(detail_url))
    ok(read_only.get(reverse("ticket_create")), 404)
    outsider = session(stranger)
    ok(outsider.get(detail_url), 404)
    assert ticket.reference not in text(ok(outsider.get(reverse("ticket_list") + "?vue=tous")))
    # L'admin de l'ESN voit le ticket de son client final
    assert ticket.reference in text(ok(esn_session.get(reverse("ticket_list") + "?vue=tous")))

    # Le client ne peut pas ouvrir en P1/P2 (escalade réservée à Aptitude)
    bad = portal.post(reverse("ticket_create"), {"contract": contract.pk, "title": "x", "description": "y",
                                                 "priority": "1"})
    assert bad.status_code == 200 and Ticket.objects.count() == 1

    # ================================================================== 4. Ingénieur Aptitude
    console = session(engineer)
    mail.outbox.clear()
    assert ticket.reference in text(ok(console.get(reverse("ticket_list"))))
    ok(console.post(reverse("ticket_assign", args=[ticket.reference]), {"assignee": engineer.pk}), 302)
    ok(console.post(reverse("ticket_status", args=[ticket.reference]), {"status": Status.IN_PROGRESS}), 302)
    ok(console.post(reverse("ticket_comment", args=[ticket.reference]),
                    {"body": "Nous analysons les journaux du pare-feu."}), 302)
    ok(console.post(reverse("ticket_comment", args=[ticket.reference]),
                    {"body": "NOTE-INTERNE certificat expiré côté IDP", "internal": "on"}), 302)
    ok(console.post(reverse("ticket_priority", args=[ticket.reference]),
                    {"priority": "2", "justification": "Tout le siège est impacté"}), 302)
    ticket.refresh_from_db()
    assert ticket.assignee == engineer and ticket.acknowledged_at and ticket.priority == 2
    to_client = [m for m in mail.outbox if m.to == [client_user.email]]
    assert any("Nous analysons les journaux" in m.body for m in to_client), "réponse envoyée au client"
    assert any("P2" in m.subject for m in to_client), "escalade annoncée au client"
    assert all("NOTE-INTERNE" not in m.body for m in mail.outbox), "la note interne ne sort pas"

    # Le client voit la réponse, la nouvelle priorité, mais pas la note interne ; il peut répondre
    seen = text(ok(portal.get(detail_url)))
    assert "Nous analysons les journaux" in seen and "NOTE-INTERNE" not in seen
    ok(portal.post(reverse("ticket_comment", args=[ticket.reference]), {"body": "Merci, nous attendons."}), 302)
    assert "Merci, nous attendons." in text(ok(console.get(detail_url)))
    # Le client ne peut pas changer le statut d'un ticket en cours
    ok(portal.post(reverse("ticket_status", args=[ticket.reference]), {"status": Status.RESOLVED}), 302)
    ticket.refresh_from_db()
    assert ticket.status == Status.IN_PROGRESS

    mail.outbox.clear()
    ok(console.post(reverse("ticket_status", args=[ticket.reference]), {"status": Status.RESOLVED}), 302)
    ticket.refresh_from_db()
    assert ticket.status == Status.RESOLVED and ticket.resolved_at
    assert [m.to for m in mail.outbox] == [[client_user.email]] and "Résolu" in mail.outbox[0].subject

    # ================================================================== 5. Rapport curatif
    create = text(ok(console.get(reverse("report_create", args=["curatif"]))))
    assert ticket.reference in create
    resp = ok(console.post(reverse("report_create", args=["curatif"]), {"ticket": f"{ticket.pk}:{end.pk}"}), 302)
    report = Report.objects.get(kind="curatif")
    assert report.reference.startswith(f"RPT-CUR-{esn.code}-{end.code}-")
    edit_url = reverse("report_edit", args=[report.pk])
    ok(console.get(edit_url))
    mail.outbox.clear()
    ok(console.post(edit_url, {
        "title": "Accès distant", "site": "Siège", "level": "N2", "symptoms": "VPN inaccessible",
        "diagnosis_category": "Certificat expiré", "cause_state": "Cause identifiée",
        "diagnosis": "Certificat du fournisseur d'identité expiré.", "fix_state": "Appliquée",
        "fix": "Certificat renouvelé.", "tests": "Connexion VPN | Validé",
        "timeline": "2026-11-04 | 08:42 | Ouverture du ticket\n04/11/2026 | 9:10 | Certificat renouvelé",
        "submit": "",
    }), 302)
    report.refresh_from_db()
    assert report.status == Report.Status.SUBMITTED
    assert [m.to for m in mail.outbox] == [[manager.email]], "seul le supérieur est prévenu"

    # Ni le rédacteur ni un autre manager ne valident ; le client ne voit rien avant l'envoi
    detail = reverse("report_detail", args=[report.pk])
    assert "Valider le rapport" not in text(ok(console.get(detail)))
    ok(session(manager2).post(reverse("report_action", args=[report.pk, "valider"])), 302)
    report.refresh_from_db()
    assert report.status == Report.Status.SUBMITTED
    ok(portal.get(detail), 404)
    ok(esn_session.get(detail), 404)

    boss = session(manager)
    assert "Valider le rapport" in text(ok(boss.get(detail)))
    ok(boss.post(reverse("report_action", args=[report.pk, "valider"])), 302)
    report.refresh_from_db()
    assert report.status == Report.Status.VALIDATED and report.fingerprint and report.validator == manager
    ok(console.get(edit_url), 302)  # verrouillé : plus modifiable

    mail.outbox.clear()
    ok(boss.post(reverse("report_action", args=[report.pk, "envoyer"])), 302)
    report.refresh_from_db()
    assert report.status == Report.Status.SENT
    assert esn_admin.email in mail.outbox[0].to

    # Côté client : le rapport, avec le logo de l'ESN, et la confirmation de réception
    assert report.reference in text(ok(esn_session.get(reverse("report", args=["tous"]))))
    seen = text(ok(portal.get(detail)))
    assert "data:image/svg+xml;base64," in seen and "Certificat du fournisseur" in seen
    assert ok(outsider.get(detail), 404)
    ok(portal.post(reverse("report_action", args=[report.pk, "confirmer"])), 302)
    report.refresh_from_db()
    assert report.client_validated_by == client_user

    # ================================================================== 6. Préventif, trimestriel, licences
    ok(console.post(reverse("report_create", args=["preventif"]), {"contract": f"{contract.pk}:{end.pk}"}), 302)
    prev = Report.objects.get(kind="preventif")
    assert prev.data["equipments"] == [["FW-LYN-01"]]
    ok(console.post(reverse("report_edit", args=[prev.pk]), {
        "site": "Siège", "started_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
        "controls": "Sécurité | MFA | Annuaire | Conforme |\nSécurité | TLS | Portail | Non conforme | 12 j",
        "recommendations": "Renouveler le certificat TLS | Haute | Support | 30/11/2026 |", "submit": "",
    }), 302)
    ok(boss.post(reverse("report_action", args=[prev.pk, "valider"])), 302)

    quarter = (timezone.localdate().month - 1) // 3 + 1
    ok(console.post(reverse("report_create", args=["trimestriel"]),
                    {"contract": f"{contract.pk}:{end.pk}", "quarter": f"{timezone.localdate().year}-{quarter}"}), 302)
    tri = Report.objects.get(kind="trimestriel")
    page = text(ok(console.get(reverse("report_detail", args=[tri.pk]))))
    assert "Certificat expiré" in page, "cause reprise du rapport curatif validé"
    assert "Renouveler le certificat TLS" in page, "recommandation reprise du rapport préventif"
    assert re.search(r"1\s*<small>/\s*1</small>", page), "1 ticket résolu sur 1"

    mail.outbox.clear()
    assert notify_expiring_licenses() == (1, 1)
    assert esn_admin.email in mail.outbox[0].to and "FW-LYN-01" in mail.outbox[0].body
    assert LicenseNotice.objects.filter(solution=firewall).exists()


def test_creation_de_compte_quand_la_messagerie_est_en_panne(monkeypatch):
    """Sans messagerie, le compte est créé et le lien d'invitation est affiché à l'administrateur."""
    import accounts.views as V

    def broken(*args, **kwargs):
        raise RuntimeError("Graph 404 ErrorInvalidUser")

    monkeypatch.setattr(V, "send_mail", broken)
    Organisation.objects.create(name="Aptitude Services", kind=Organisation.Kind.CLIENT, is_operator=True)
    esn = Organisation.objects.create(name="ESN", kind=Organisation.Kind.CLIENT)
    admin = session(User.objects.create_superuser("root@aptitudes.net", PASSWORD))
    resp = ok(admin.post(reverse("user_create"), {
        "email": "nouveau@esn.ci", "first_name": "N", "last_name": "X", "language": "fr",
        "organisation": esn.pk, "profile": Profile.CLIENT_RW, "all_contracts": "on", "is_active": "on",
    }, follow=True))
    assert User.objects.filter(email="nouveau@esn.ci").exists()
    link = re.search(r"https?://[^\s<\"]+/mot-de-passe/definir/[^/\s]+/[^/\s]+/", text(resp)).group(0)
    # Le lien mène bien au choix du mot de passe
    from urllib.parse import urlsplit
    page = Client().get(urlsplit(link).path, follow=True)
    assert page.status_code == 200 and "new_password1" in text(page)
