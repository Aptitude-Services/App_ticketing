"""Emails de suivi des tickets.

- Client (demandeur) : accusé de réception, puis chaque étape (prise en charge, attente,
  résolution, clôture), chaque réponse d'Aptitude et chaque changement de priorité.
  Jamais les notes internes.
- Ingénieur assigné : l'assignation, puis chaque réponse du client.
- Équipe Aptitude : un nouveau ticket, ou une réponse du client sur un ticket non assigné.

L'auteur d'une action n'est pas prévenu de sa propre action, sauf l'accusé de réception. Un email qui ne part pas
n'interrompt jamais l'action : l'échec est inscrit au journal des emails.

Chaque email est doublé d'une notification interne (cloche), pour les mêmes destinataires — sauf
l'auteur de l'action, y compris pour l'accusé de réception.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _

from accounts.models import Profile, User
from core.notify import notify

from .models import Status

logger = logging.getLogger(__name__)

SUPPORT_PROFILES = (Profile.APTITUDE_ADMIN, Profile.APTITUDE_MANAGER, Profile.TECH_ALL)

STATUS_MESSAGES = {
    Status.ACKNOWLEDGED: "Votre demande a été prise en charge par notre équipe.",
    Status.IN_PROGRESS: "Notre équipe travaille sur votre demande.",
    Status.WAITING_CLIENT: "Nous avons besoin d'un retour de votre part pour avancer : "
                           "répondez directement sur le portail.",
    Status.WAITING_PREREQ: "Des prérequis sont nécessaires pour poursuivre l'intervention.",
    Status.RESOLVED: "Votre demande est résolue. Si le problème persiste, répondez sur le portail : "
                     "le ticket sera rouvert.",
    Status.CLOSED: "Votre demande est close. Merci de votre confiance.",
}


def _url(ticket):
    path = reverse("ticket_detail", args=[ticket.reference])
    return f"{settings.SITE_URL.rstrip('/')}{path}" if settings.SITE_URL else path


def _send(users, subject, lines, ticket, actor=None):
    """Un email par destinataire, dans sa langue, plus une notification interne. Ne lève jamais d'exception."""
    users = list(users)
    notify(users, "ticket", f"{ticket.reference} — {subject}", reverse("ticket_detail", args=[ticket.reference]),
           actor=actor, body=next((line for line in lines if line), ""))
    sent = 0
    for user in {u.pk: u for u in users if u and u.is_active and u.email}.values():
        try:
            with translation.override(user.language or settings.LANGUAGE_CODE):
                body = "\n".join([_("Bonjour %(name)s,") % {"name": user.display_name}, ""]
                                 + list(lines)
                                 + ["", f"{ticket.reference} — {ticket.title}", _url(ticket), "",
                                    _("L'équipe Aptitude Support")])
                sent += send_mail(f"[{ticket.reference}] {subject}", body, None, [user.email],
                                  fail_silently=True)
        except Exception:
            logger.exception("Notification du ticket %s impossible", ticket.reference)
    return sent


def _support_team(ticket):
    from accounts.permissions import visible_contracts

    users = User.objects.filter(is_active=True, profile__in=SUPPORT_PROFILES)
    return [u for u in users if visible_contracts(u).filter(pk=ticket.contract_id).exists()]


def _others(users, actor):
    return [u for u in users if u and (actor is None or u.pk != actor.pk)]


def ticket_created(ticket, actor):
    # Accusé de réception : envoyé au demandeur, y compris quand il a ouvert le ticket lui-même.
    _send([ticket.requester] if ticket.requester.is_client else [], "Votre demande a bien été enregistrée",
          ["Votre demande a bien été enregistrée. Notre équipe vous répond dans les délais de votre contrat.",
           f"Priorité : P{ticket.priority}"], ticket, actor)
    _send(_others(_support_team(ticket), actor), "Nouveau ticket",
          [f"Nouveau ticket de {ticket.requester.display_name} ({ticket.requester.organisation}), "
           f"contrat {ticket.contract.reference}, priorité P{ticket.priority}.",
           "", ticket.description[:1500]], ticket, actor)


def status_changed(ticket, actor, new):
    message = STATUS_MESSAGES.get(new)
    if not message:
        return
    label = dict(Status.choices)[new]
    _send(_others([ticket.requester], actor), f"Statut : {label}", [message], ticket, actor)


def priority_changed(ticket, actor, old, new, justification=""):
    lines = [f"La priorité de votre demande passe de P{old} à P{new}."]
    if justification:
        lines.append(f"Motif : {justification}")
    _send(_others([ticket.requester], actor), f"Priorité P{new}", lines, ticket, actor)


def assigned(ticket, actor, user):
    _send(_others([user], actor), "Ticket qui vous est assigné",
          [f"Ce ticket vous est assigné (priorité P{ticket.priority}, client {ticket.contract.client})."], ticket, actor)


def commented(ticket, actor, comment):
    if comment.is_internal:
        return  # une note interne ne sort jamais de l'équipe Aptitude
    excerpt = comment.body[:1500] if comment.body else "(pièce jointe)"
    if actor.is_aptitude:
        _send(_others([ticket.requester], actor), "Nouvelle réponse de notre équipe",
              [f"{actor.display_name} a répondu :", "", excerpt], ticket, actor)
    else:
        targets = [ticket.assignee] if ticket.assignee_id else _support_team(ticket)
        _send(_others(targets, actor), "Réponse du client",
              [f"{actor.display_name} ({actor.organisation}) a répondu :", "", excerpt], ticket, actor)
