"""Fichiers statiques de l'administration avec numéro de version.

Hors production (DEBUG), Django sert les CSS/JS sous leur nom simple : après une mise
à jour, le navigateur peut garder l'ancienne version en cache. On ajoute « ?v=<empreinte> »,
calculée sur le contenu du fichier : l'adresse change dès que le fichier change.
En production, le stockage « Manifest » ajoute en plus son propre hachage au nom.
"""
import hashlib
from functools import lru_cache

from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.utils.functional import lazy


@lru_cache(maxsize=None)
def _versioned_url(path):
    url = static(path)  # adresse complète (hachée en production)
    found = finders.find(path)
    if not found:
        return url
    with open(found, "rb") as fh:
        digest = hashlib.md5(fh.read(), usedforsecurity=False).hexdigest()[:10]
    return f"{url}?v={digest}"


# Calcul différé à l'affichage : au chargement du code, le manifeste des fichiers
# statiques peut ne pas encore exister (ex. pendant collectstatic).
versioned = lazy(_versioned_url, str)
