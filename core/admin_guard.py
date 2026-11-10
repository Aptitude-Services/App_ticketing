"""Entrée de l'administration (/gestion/login/) sans fuite d'information.

Django affiche par défaut, à un utilisateur connecté sans droit d'administration :
« Vous êtes authentifié sous le nom <email>, mais vous n'êtes pas autorisé… ». Ce message
confirme l'existence de l'espace d'administration et expose l'adresse du compte.

Ici :
- utilisateur connecté sans droit d'administration → la page « introuvable » habituelle (404),
  identique à n'importe quelle adresse inexistante ;
- visiteur non connecté → la page de connexion de l'application (avec ses protections :
  limitation des tentatives, double authentification), puis retour à la page demandée ;
- membre autorisé → connexion standard de l'administration.
"""
from django.contrib import admin
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import render
from django.urls import reverse


def admin_login(request, extra_context=None):
    if request.user.is_authenticated:
        if not admin.site.has_permission(request):
            return render(request, "404.html", status=404)
        return admin.site.login(request, extra_context)
    return redirect_to_login(request.GET.get("next") or reverse("admin:index"), reverse("login"))
