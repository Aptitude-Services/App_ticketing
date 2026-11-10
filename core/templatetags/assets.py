"""{% versioned 'css/app.css' %} : adresse d'un fichier statique avec numéro de version
(voir core/assets.py), pour que le navigateur charge toujours la dernière version."""
from django import template

from core.assets import versioned as _versioned

register = template.Library()


@register.simple_tag
def versioned(path):
    return str(_versioned(path))
