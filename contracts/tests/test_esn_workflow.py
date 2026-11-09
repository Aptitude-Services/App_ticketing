"""Retours métier : clients finaux des ESN, import Excel des solutions, forfait repris sur le ticket."""
import datetime
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import Workbook

from accounts.admin import OrganisationForm
from accounts.models import Organisation, Profile, User
from contracts.models import Contract, ContractType, Solution
from tickets import services as S

pytestmark = pytest.mark.django_db
SECTOR = Organisation.ActivitySector.BANK


@pytest.fixture
def env(client, monkeypatch):
    # L'enrôlement MFA est testé ailleurs ; ici on ouvre directement l'administration.
    from accounts.middleware import MFARequiredMiddleware
    monkeypatch.setattr(MFARequiredMiddleware, "__call__", lambda self, request: self.get_response(request))
    apt = Organisation.objects.create(name="Aptitude Services", kind=Organisation.Kind.APTITUDE)
    esn = Organisation.objects.create(name="ESN A", kind=Organisation.Kind.CLIENT, activity_sector=SECTOR)
    end = Organisation.objects.create(name="Banque Finale", kind=Organisation.Kind.END_CLIENT, activity_sector=SECTOR)
    esn.end_clients.add(end)
    contract = Contract.objects.create(
        reference="ESN-1", title="Contrat", client=esn, start_date=datetime.date(2026, 1, 1),
        contract_type=ContractType.objects.get(name="Standard 24x7"),
    )
    admin = User.objects.create_superuser("admin@aptitudes.net", "Motdepasse-tres-long-1")
    client.force_login(admin)
    return {"apt": apt, "esn": esn, "end": end, "contract": contract, "admin": admin, "client": client}


# --- Organisation : rattachement des clients finaux -------------------------

def test_org_form_offers_only_end_clients(env):
    qs = OrganisationForm().fields["end_clients"].queryset
    assert list(qs) == [env["end"]]


def test_org_form_ignores_end_clients_on_non_esn(env):
    """Champ masqué pour un client final : une valeur reçue est ignorée, pas enregistrée."""
    form = OrganisationForm({"name": "Autre final", "kind": "end_client", "activity_sector": "bank",
                             "is_active": "on", "email_domains": "", "end_clients": [env["end"].pk]})
    assert form.is_valid(), form.errors
    org = form.save()
    assert not org.end_clients.exists()


def _post_org(client, url, **data):
    base = {"name": "Nouvelle org", "kind": "end_client", "activity_sector": "bank",
            "is_active": "on", "email_domains": ""}
    return client.post(url, {**base, **data})


def test_end_client_created_with_its_esns(env):
    """Un client final se crée séparément, puis se rattache à ses ESN depuis sa fiche."""
    esn_b = Organisation.objects.create(name="ESN B", kind=Organisation.Kind.CLIENT, activity_sector=SECTOR)
    resp = _post_org(env["client"], reverse("admin:accounts_organisation_add"),
                     name="Hôpital Sud", partner_esns=[env["esn"].pk, esn_b.pk])
    assert resp.status_code == 302, resp.context["adminform"].form.errors if resp.context else resp
    created = Organisation.objects.get(name="Hôpital Sud")
    assert set(created.partner_esns.all()) == {env["esn"], esn_b}


def test_end_client_page_shows_its_esns(env):
    resp = env["client"].get(reverse("admin:accounts_organisation_change", args=[env["end"].pk]))
    form = resp.context["adminform"].form
    assert form.fields["partner_esns"].initial == [env["esn"].pk]
    assert list(form.fields["partner_esns"].queryset) == list(
        Organisation.objects.filter(kind=Organisation.Kind.CLIENT))


def test_esn_ignores_partner_esns(env):
    """Une ESN ne se rattache pas à une autre ESN."""
    other = Organisation.objects.create(name="ESN C", kind=Organisation.Kind.CLIENT, activity_sector=SECTOR)
    _post_org(env["client"], reverse("admin:accounts_organisation_add"),
              name="ESN D", kind="client", partner_esns=[other.pk])
    assert not Organisation.objects.get(name="ESN D").partner_esns.exists()


def test_popup_is_locked_to_end_client_without_links(env):
    url = reverse("admin:accounts_organisation_add") + "?_to_field=id&_popup=1"
    form = env["client"].get(url).context["adminform"].form
    assert [value for value, _label in form.fields["kind"].choices] == ["end_client"]
    assert "end_clients" not in form.fields and "partner_esns" not in form.fields

    resp = _post_org(env["client"], url, name="Créé en popup", kind="client", _popup="1", _to_field="id")
    assert not Organisation.objects.filter(name="Créé en popup").exists()  # « Client ESN » refusé
    resp = _post_org(env["client"], url, name="Créé en popup", _popup="1", _to_field="id")
    assert Organisation.objects.get(name="Créé en popup").kind == Organisation.Kind.END_CLIENT


def test_new_esn_created_with_existing_end_client(env):
    form = OrganisationForm({"name": "ESN B", "kind": "client", "activity_sector": "telecom",
                             "is_active": "on", "email_domains": "", "end_clients": [env["end"].pk]})
    assert form.is_valid(), form.errors
    esn_b = form.save()
    # Le même client final est désormais partagé par deux ESN.
    assert set(env["end"].partner_esns.all()) == {env["esn"], esn_b}


def test_popup_from_end_clients_field_presets_end_client_kind(env):
    url = reverse("admin:accounts_organisation_add") + "?_to_field=id&_popup=1"
    resp = env["client"].get(url)
    assert resp.status_code == 200
    assert resp.context["adminform"].form.initial["kind"] == Organisation.Kind.END_CLIENT


def test_create_end_client_from_esn_page(env):
    url = reverse("admin:accounts_organisation_add_end_client", args=[env["esn"].pk])
    resp = env["client"].post(url, {"name": "Clinique Nord", "activity_sector": "health", "email_domains": ""})
    assert resp.status_code == 302
    created = Organisation.objects.get(name="Clinique Nord")
    assert created.kind == Organisation.Kind.END_CLIENT
    assert created in env["esn"].end_clients.all()


def test_org_admin_add_page_shows_client_esn_and_sector(env):
    resp = env["client"].get(reverse("admin:accounts_organisation_add"))
    html = resp.content.decode()
    assert "Client ESN" in html
    assert "Secteur d" in html
    assert "type de client" not in html.lower()


def test_org_admin_form_has_no_help_texts(env):
    """Formulaire épuré : aucun texte d'aide sous les champs de l'organisation."""
    html = env["client"].get(reverse("admin:accounts_organisation_add")).content.decode()
    for text in ("Obligatoire pour un client ESN", "Un même client final peut", "Maintenez appuyé",
                 "Domaines séparés"):
        assert text not in html, text


def test_contract_admin_add_page_renders(env):
    resp = env["client"].get(reverse("admin:contracts_contract_add"))
    assert resp.status_code == 200


# --- Import Excel des solutions ---------------------------------------------

def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile("solutions.xlsx", buf.getvalue(),
                              content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def test_import_solutions_creates_and_updates(env):
    contract = env["contract"]
    Solution.objects.create(contract=contract, name="Pare-feu", category="hardware", vendor="Ancien")
    upload = _xlsx([
        ["Catégorie", "Nom", "Éditeur", "Version", "Fin de licence"],
        ["Matériel", "Pare-feu", "Fortinet", "7.4", "31/12/2027"],
        ["logiciel", "ERP", "SAP", "S/4", datetime.datetime(2028, 6, 30)],
        ["inconnue", "Truc", "", "", ""],
        [None, None, None, None, None],
    ])
    url = reverse("admin:contracts_contract_import_solutions", args=[contract.pk])
    resp = env["client"].post(url, {"file": upload})
    assert resp.status_code == 200
    result = resp.context["result"]
    assert result["ok"] and result["created"] == 1 and result["updated"] == 1
    assert len(result["errors"]) == 1 and "Ligne 4" in str(result["errors"][0])

    fw = Solution.objects.get(contract=contract, name="Pare-feu")
    assert fw.vendor == "Fortinet" and fw.license_end == datetime.date(2027, 12, 31)
    erp = Solution.objects.get(contract=contract, name="ERP")
    assert erp.category == "software" and erp.license_end == datetime.date(2028, 6, 30)


def test_import_solutions_requires_name_and_category_columns(env):
    url = reverse("admin:contracts_contract_import_solutions", args=[env["contract"].pk])
    resp = env["client"].post(url, {"file": _xlsx([["Éditeur"], ["SAP"]])})
    assert not resp.context["result"]["ok"]
    assert not Solution.objects.exists()


def test_import_solutions_rejects_non_excel(env):
    url = reverse("admin:contracts_contract_import_solutions", args=[env["contract"].pk])
    bad = SimpleUploadedFile("x.xlsx", b"pas un classeur")
    resp = env["client"].post(url, {"file": bad})
    assert not resp.context["result"]["ok"]


# --- Forfait repris sur le ticket -------------------------------------------

def test_ticket_forfait_prefilled_from_contract_formula(env):
    gold, _ = ContractType.objects.get_or_create(name="GOLD", defaults={"sla": env["contract"].contract_type.sla})
    env["contract"].contract_type = gold
    env["contract"].save()
    user = User.objects.create_user("rw@esn.ci", "Motdepasse-tres-long-1", organisation=env["esn"],
                                    profile=Profile.CLIENT_ADMIN)
    ticket = S.create_ticket(user, env["contract"], "Panne", "Le service ne répond plus")
    assert ticket.forfait == "GOLD"


# --- Codes des organisations et références de contrat -----------------------

def test_organisation_codes_are_derived_and_unique(env):
    assert env["esn"].code == "EA"  # « ESN A » : calculé depuis le nom
    hud = Organisation.objects.create(name="HUDSON", kind=Organisation.Kind.CLIENT, activity_sector=SECTOR)
    lagune = Organisation.objects.create(name="Banque Lagune", kind=Organisation.Kind.END_CLIENT,
                                         activity_sector=SECTOR)
    twin = Organisation.objects.create(name="Hudson", kind=Organisation.Kind.CLIENT, activity_sector=SECTOR)
    assert (hud.code, lagune.code, twin.code) == ("HUD", "BLAG", "HUD2")


def test_organisation_code_entered_by_hand_is_checked(env):
    org = Organisation(name="Orange CI", code="or-ci", kind=Organisation.Kind.CLIENT, activity_sector=SECTOR)
    with pytest.raises(Exception):
        org.full_clean()
    org.code = "orci"
    org.full_clean()
    org.save()
    assert org.code == "ORCI"


def _add_contract(env, **data):
    base = {
        "title": "Contrat", "client": env["esn"].pk, "status": Contract.Status.ACTIVE,
        "contract_type": ContractType.objects.get(name="GOLD").pk, "start_date": "2026-01-01",
        "solutions-TOTAL_FORMS": "0", "solutions-INITIAL_FORMS": "0",
        "accesses-TOTAL_FORMS": "0", "accesses-INITIAL_FORMS": "0",
    }
    resp = env["client"].post(reverse("admin:contracts_contract_add"), {**base, **data})
    assert resp.status_code == 302, resp.context["adminform"].form.errors if resp.context else resp
    return Contract.objects.order_by("-pk").first()


def test_contract_reference_built_from_esn_and_end_client(env):
    from django.utils import timezone
    year = timezone.localdate().year
    esn, end = env["esn"], env["end"]
    first = _add_contract(env, end_clients=[end.pk])
    second = _add_contract(env, title="Autre", end_clients=[end.pk])
    assert first.reference == f"{esn.code}-{end.code}-{year}-001"
    assert second.reference == f"{esn.code}-{end.code}-{year}-002"

    alone = _add_contract(env, title="ESN seule")
    assert alone.reference == f"{esn.code}-{year}-001"

    other = Organisation.objects.create(name="Clinique Nord", kind=Organisation.Kind.END_CLIENT,
                                        activity_sector=SECTOR)
    esn.end_clients.add(other)
    multi = _add_contract(env, title="Plusieurs", end_clients=[end.pk, other.pk])
    assert multi.reference == f"{esn.code}-MULTI-{year}-001"


def test_contract_reference_not_asked_then_read_only(env):
    add_form = env["client"].get(reverse("admin:contracts_contract_add")).context["adminform"].form
    assert "reference" not in add_form.fields
    contract = env["contract"]
    change = env["client"].get(reverse("admin:contracts_contract_change", args=[contract.pk]))
    assert "reference" not in change.context["adminform"].form.fields
    assert contract.reference in change.content.decode()


def test_solution_forms_have_no_version_field(env):
    from django.contrib.admin.sites import site
    from contracts.admin import SolutionInline
    from contracts.models import Solution as Sol
    assert "version" not in SolutionInline.fields
    request = env["client"].get(reverse("admin:contracts_solution_add")).wsgi_request
    assert "version" not in site._registry[Sol].get_form(request)().fields


def test_import_entry_shown_above_solutions(env):
    """L'accès à l'import Excel est visible au-dessus du tableau des solutions."""
    add = env["client"].get(reverse("admin:contracts_contract_add")).content.decode()
    assert "enregistrez d'abord le contrat" in add.lower()
    assert reverse("admin:contracts_contract_import_template") in add
    change = env["client"].get(reverse("admin:contracts_contract_change", args=[env["contract"].pk]))
    assert reverse("admin:contracts_contract_import_solutions", args=[env["contract"].pk]) in change.content.decode()


def test_import_template_round_trip(env):
    """Le modèle téléchargé, une fois rempli, est accepté tel quel par l'import."""
    from openpyxl import load_workbook

    resp = env["client"].get(reverse("admin:contracts_contract_import_template"))
    assert resp.status_code == 200
    assert resp["Content-Disposition"].endswith('modele-import-solutions.xlsx"')
    wb = load_workbook(io.BytesIO(resp.content))
    assert wb.sheetnames == ["Solutions", "Catégories acceptées"]
    buf = io.BytesIO()
    wb.save(buf)
    upload = SimpleUploadedFile("rempli.xlsx", buf.getvalue())
    url = reverse("admin:contracts_contract_import_solutions", args=[env["contract"].pk])
    result = env["client"].post(url, {"file": upload}).context["result"]
    assert result["ok"] and result["created"] == 1 and not result["errors"], result
    sol = Solution.objects.get(contract=env["contract"], name="Pare-feu siège")
    assert sol.category == "hardware" and sol.serial_number == "FG100F0000000"
    assert sol.license_end == datetime.date(2026, 12, 31)


def test_code_not_asked_on_organisation_forms(env):
    """Le code est calculé automatiquement : il n'est plus saisi."""
    add = env["client"].get(reverse("admin:accounts_organisation_add")).context["adminform"].form
    assert "code" not in add.fields
    form = OrganisationForm({"name": "Orange CI", "kind": "client", "activity_sector": "telecom",
                             "is_active": "on", "email_domains": ""})
    assert form.is_valid(), form.errors
    assert form.save().code == "OCI"
