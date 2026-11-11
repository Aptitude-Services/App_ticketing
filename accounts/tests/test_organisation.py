"""Secteur d'activité des organisations : obligatoire pour un client, interdit pour Aptitude."""
import pytest
from django.contrib.admin.sites import site
from django.core.exceptions import ValidationError

from accounts.models import Organisation

pytestmark = pytest.mark.django_db

BANK = Organisation.ActivitySector.BANK


def test_esn_does_not_require_activity_sector():
    """Le secteur d'activité se demande au client final, pas à l'ESN."""
    Organisation(name="ESN X", kind=Organisation.Kind.CLIENT).full_clean()


def test_client_with_sector_is_valid():
    org = Organisation(name="Banque X", kind=Organisation.Kind.CLIENT, activity_sector=BANK)
    org.full_clean()
    assert org.get_activity_sector_display() == "Banque"


def test_end_client_requires_activity_sector():
    org = Organisation(name="Filiale", kind=Organisation.Kind.END_CLIENT)
    with pytest.raises(ValidationError) as exc:
        org.full_clean()
    assert "activity_sector" in exc.value.message_dict


def test_aptitude_has_no_activity_sector():
    org = Organisation(name="Aptitude Services", kind=Organisation.Kind.APTITUDE, activity_sector=BANK)
    with pytest.raises(ValidationError) as exc:
        org.full_clean()
    assert "activity_sector" in exc.value.message_dict
    org.activity_sector = ""
    org.full_clean()


def test_admin_form_asks_end_client_for_activity_sector(rf, admin_user):
    request = rf.get("/")
    request.user = admin_user
    form_class = site._registry[Organisation].get_form(request)
    data = {"name": "PME Y", "kind": "end_client", "activity_sector": "", "email_domains": "", "is_active": "on"}
    form = form_class(data)
    assert not form.is_valid()
    assert "activity_sector" in form.errors

    form = form_class({**data, "activity_sector": "bank"})
    assert form.is_valid(), form.errors
    assert form.save().activity_sector == "bank"


def test_admin_form_ignores_sector_for_esn(rf, admin_user):
    request = rf.get("/")
    request.user = admin_user
    form_class = site._registry[Organisation].get_form(request)
    form = form_class({"name": "ESN Z", "kind": "client", "activity_sector": "bank", "email_domains": "",
                       "is_active": "on"})
    assert form.is_valid(), form.errors
    assert form.save().activity_sector == ""


def test_admin_lists_and_filters_by_sector():
    admin = site._registry[Organisation]
    assert "sector" in admin.list_display
    assert "activity_sector" in admin.list_filter


def test_esn_kind_is_labelled_client_esn():
    assert dict(Organisation.Kind.choices)["client"] == "Client ESN"


# --- Logo de l'ESN ----------------------------------------------------------------------------------

SVG = b"<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'/>"


@pytest.fixture
def admin_client_nomfa(client, admin_user, monkeypatch):
    from accounts.middleware import MFARequiredMiddleware
    monkeypatch.setattr(MFARequiredMiddleware, "__call__", lambda self, request: self.get_response(request))
    client.force_login(admin_user)
    return client


def test_create_esn_with_logo(admin_client_nomfa):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.urls import reverse

    url = reverse("admin:accounts_organisation_add")
    page = admin_client_nomfa.get(url).content.decode()
    assert 'enctype="multipart/form-data"' in page and 'name="logo"' in page

    resp = admin_client_nomfa.post(url, {
        "name": "ESN Logo", "kind": "client", "activity_sector": "", "email_domains": "", "is_active": "on",
        "logo": SimpleUploadedFile("esn.svg", SVG, content_type="image/svg+xml"),
    })
    assert resp.status_code == 302, resp.content.decode()[:500]
    esn = Organisation.objects.get(name="ESN Logo")
    assert esn.logo and esn.logo_data_uri().startswith("data:image/svg+xml;base64,")

    # Aperçu du logo sur la fiche et vignette dans la liste
    change = admin_client_nomfa.get(reverse("admin:accounts_organisation_change", args=[esn.pk])).content.decode()
    assert 'class="logo-preview"' in change and "data:image/svg+xml" in change
    listing = admin_client_nomfa.get(reverse("admin:accounts_organisation_changelist")).content.decode()
    assert "org-logo-thumb" in listing


def test_logo_rejects_non_image(admin_client_nomfa):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.urls import reverse

    resp = admin_client_nomfa.post(reverse("admin:accounts_organisation_add"), {
        "name": "ESN Exe", "kind": "client", "email_domains": "", "is_active": "on",
        "logo": SimpleUploadedFile("virus.exe", b"MZ"),
    })
    assert resp.status_code == 200 and not Organisation.objects.filter(name="ESN Exe").exists()


def test_logo_ignored_for_end_client(admin_client_nomfa):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.urls import reverse

    admin_client_nomfa.post(reverse("admin:accounts_organisation_add"), {
        "name": "Final Logo", "kind": "end_client", "activity_sector": "bank", "email_domains": "", "is_active": "on",
        "logo": SimpleUploadedFile("f.svg", SVG, content_type="image/svg+xml"),
    })
    assert not Organisation.objects.get(name="Final Logo").logo


# --- Liste par ESN (clients finaux dépliables) ---------------------------------------------------------

@pytest.fixture
def esn_tree():
    esn = Organisation.objects.create(name="ESN Arbre", kind=Organisation.Kind.CLIENT)
    linked = Organisation.objects.create(name="Final Rattache", kind=Organisation.Kind.END_CLIENT, activity_sector=BANK)
    alone = Organisation.objects.create(name="Final Seul", kind=Organisation.Kind.END_CLIENT, activity_sector=BANK)
    esn.end_clients.add(linked)
    return esn, linked, alone


def _rows(page):
    """Noms affichés comme lignes du tableau (liens de la colonne Nom)."""
    import re
    return re.findall(r'class="field-name"><a href="[^"]+">([^<]+)</a>', page)


def test_changelist_shows_esn_with_foldable_end_clients(admin_client_nomfa, esn_tree):
    import json
    import re
    from django.urls import reverse
    esn, linked, alone = esn_tree
    page = admin_client_nomfa.get(reverse("admin:accounts_organisation_changelist")).content.decode()
    rows = _rows(page)
    assert "ESN Arbre" in rows and "Final Seul" in rows       # client final sans ESN : visible, mention « sans ESN »
    assert "Final Rattache" not in rows                        # rattaché : replié sous son ESN
    assert "sans ESN" in page and "organisation_tree.js" in page
    data = re.search(r'class="org-toggle"[^>]*data-children="([^"]+)"', page).group(1)
    import html
    children = json.loads(html.unescape(data))
    assert [c["name"] for c in children] == ["Final Rattache"]
    assert children[0]["url"] == reverse("admin:accounts_organisation_change", args=[linked.pk])


@pytest.mark.parametrize("query", ["q=Final", "kind__exact=end_client", "activity_sector__exact=bank"])
def test_search_or_filter_lists_end_clients_flat(admin_client_nomfa, esn_tree, query):
    from django.urls import reverse
    page = admin_client_nomfa.get(reverse("admin:accounts_organisation_changelist") + "?" + query).content.decode()
    assert {"Final Rattache", "Final Seul"} <= set(_rows(page))


def test_end_client_change_page_still_reachable(admin_client_nomfa, esn_tree):
    from django.urls import reverse
    _esn, linked, _alone = esn_tree
    resp = admin_client_nomfa.get(reverse("admin:accounts_organisation_change", args=[linked.pk]))
    assert resp.status_code == 200
