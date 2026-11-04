"""Application installable (PWA) : manifeste, service worker et page hors ligne.

Ces trois adresses sont publiques (aucune donnée) et servies à la racine, pour que le
service worker couvre tout le site.
"""
import hashlib

from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import cache_control

THEME = "#1F2D3D"


@cache_control(max_age=3600)
def manifest(request):
    data = {
        "name": "Aptitude | Assistance Center",
        "short_name": "Aptitude",
        "description": "Support et suivi des tickets Aptitude Services.",
        "lang": "fr",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": THEME,
        "theme_color": THEME,
        "icons": [
            {"src": static("img/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": static("img/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": static("img/icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Mes tickets", "url": "/tickets/", "icons": [{"src": static("img/icon-192.png"), "sizes": "192x192"}]},
            {"name": "Ouvrir un ticket", "url": "/tickets/nouveau/", "icons": [{"src": static("img/icon-192.png"), "sizes": "192x192"}]},
        ],
    }
    return JsonResponse(data, content_type="application/manifest+json", json_dumps_params={"ensure_ascii": False})


@cache_control(no_cache=True)
def service_worker(request):
    shell = "|".join(static(p) for p in ("css/app.css", "js/mobile.js", "img/logo.png", "img/icon-192.png"))
    version = hashlib.sha256(shell.encode()).hexdigest()[:12]
    response = render(request, "pwa/sw.js", {"version": version}, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response


def offline(request):
    return render(request, "pwa/offline.html")
