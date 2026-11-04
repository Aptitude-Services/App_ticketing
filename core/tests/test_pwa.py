"""Application installable (PWA) : manifeste, service worker, page hors ligne, liens dans les pages."""
import json

import pytest
from django.urls import reverse

from accounts.models import Organisation, Profile, User

pytestmark = pytest.mark.django_db


def test_manifest_describes_an_installable_app(client):
    resp = client.get("/manifest.webmanifest")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("application/manifest+json")
    data = json.loads(resp.content)
    assert data["name"] == "Aptitude | Assistance Center"
    assert data["start_url"] == "/" and data["display"] == "standalone"
    sizes = {i["sizes"] for i in data["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(i.get("purpose") == "maskable" for i in data["icons"])


def test_service_worker_is_served_at_the_root(client):
    resp = client.get("/sw.js")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("application/javascript")
    assert resp["Service-Worker-Allowed"] == "/"
    body = resp.content.decode()
    assert "aptitude-shell-" in body and "/hors-ligne/" in body
    # Les pages ne sont jamais mises en cache : la navigation passe toujours par le réseau.
    assert 'request.mode === "navigate"' in body and "fetch(request).catch" in body


def test_offline_page_needs_no_login(client):
    resp = client.get(reverse("offline"))
    assert resp.status_code == 200 and "Pas de connexion" in resp.content.decode()


def test_pwa_files_skip_mfa_for_unverified_aptitude_user(client):
    org = Organisation.objects.create(name="Aptitude Services", kind=Organisation.Kind.APTITUDE)
    user = User.objects.create_user("ing@aptitudes.net", "Motdepasse-tres-long-1", organisation=org,
                                    profile=Profile.TECH_ALL)
    client.force_login(user)  # MFA pas encore activée : les pages redirigent, pas les fichiers PWA
    assert client.get(reverse("dashboard")).status_code == 302
    for url in ("/manifest.webmanifest", "/sw.js", reverse("offline")):
        assert client.get(url).status_code == 200


def test_pages_link_the_manifest_and_mobile_script(client):
    html = client.get(reverse("login")).content.decode()
    assert 'rel="manifest" href="/manifest.webmanifest"' in html
    assert 'name="theme-color"' in html and "js/mobile" in html
