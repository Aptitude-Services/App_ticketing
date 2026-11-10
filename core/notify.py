"""Création des notifications internes (cloche de la barre du haut).

Appelé aux mêmes endroits que les emails (tickets/notifications.py, reports/services.py).
Ne lève jamais d'exception : une notification qui échoue n'empêche pas l'action.
"""
import logging

from django.conf import settings
from django.utils import translation

logger = logging.getLogger(__name__)


def notify(users, kind, title, url, actor=None, body=""):
    """Une notification par destinataire actif, hors auteur de l'action.

    `title` et `body` peuvent être des fonctions sans argument : elles sont alors évaluées
    dans la langue de chaque destinataire. Renvoie le nombre de notifications créées.
    """
    from .models import Notification

    created = 0
    for user in {u.pk: u for u in users if u and u.is_active}.values():
        if actor is not None and user.pk == actor.pk:
            continue
        try:
            with translation.override(user.language or settings.LANGUAGE_CODE):
                t = title() if callable(title) else title
                b = body() if callable(body) else body
            Notification.objects.create(recipient=user, actor=actor, kind=kind, title=str(t)[:255],
                                        body=" ".join(str(b or "").split())[:300], url=url)
            created += 1
        except Exception:
            logger.exception("Notification interne impossible pour %s", user.pk)
    return created
