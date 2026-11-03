"""Règles métier des tickets : un seul point d'entrée pour toute modification.

Vues, emails entrants et API passent par ces fonctions : les règles (droits,
couverture 8x5, priorités, SLA, historique) ne sont écrites qu'ici.
"""
import datetime
import os

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from accounts.models import Profile
from accounts.permissions import visible_contracts
from sla import engine
from sla.models import CLIENT_MAX_PRIORITY, PRIORITIES_REQUIRING_JUSTIFICATION, Priority

from .models import OPEN_STATUSES, Attachment, Channel, Comment, Event, Status, Ticket, TicketSequence

# Priorités interdites à l'ouverture : elles ne s'atteignent que par escalade justifiée.
ESCALATION_ONLY_PRIORITIES = PRIORITIES_REQUIRING_JUSTIFICATION

RISK_THRESHOLD = 0.75
AUTO_CLOSE_AFTER = datetime.timedelta(days=1)
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".txt", ".log", ".csv", ".docx", ".xlsx", ".pptx",
                      ".zip", ".eml", ".msg", ".json", ".xml", ".pcap"}


class CoverageError(ValidationError):
    """Création refusée hors couverture d'un contrat 8x5."""

    def __init__(self, next_open):
        self.next_open = next_open
        super().__init__(_("Ce contrat est couvert en heures ouvrées. La création de ticket sera possible à "
                           "partir du %(when)s.") % {"when": timezone.localtime(next_open).strftime("%d/%m/%Y %H:%M")})


# --- Droits -----------------------------------------------------------------------

def visible_tickets(user):
    """Tickets visibles : ceux des contrats visibles. Jamais d'autre filtre ailleurs."""
    return Ticket.objects.filter(contract__in=visible_contracts(user)).select_related(
        "contract__client", "contract__contract_type__sla", "assignee", "requester")


def can_write(user):
    return user.is_authenticated and user.is_active and user.can_write_tickets


def writable_contracts(user):
    if not can_write(user):
        return visible_contracts(user).none()
    from contracts.models import Contract
    return visible_contracts(user).filter(status=Contract.Status.ACTIVE)


def _require(condition, message=None):
    if not condition:
        raise PermissionDenied(message or _("Action non autorisée."))


def _event(ticket, actor, kind, internal=False, at=None, **data):
    """Historise l'action et date la dernière mise à jour du ticket (tout changement passe par ici)."""
    at = at or timezone.now()
    if not internal:
        Ticket.objects.filter(pk=ticket.pk).update(updated_at=at)
        ticket.updated_at = at
    return Event.objects.create(ticket=ticket, actor=actor, kind=kind, data=data, is_internal=internal, created_at=at)


# --- Échéances ----------------------------------------------------------------------

def _target(ticket):
    sla = ticket.contract.sla
    return sla, (sla.target(ticket.priority) if sla else None)


def _set_deadlines(ticket, start, keep_earlier=False):
    """Calcule les échéances depuis `start`. Avec keep_earlier, une échéance ne recule jamais."""
    sla, target = _target(ticket)
    if not target:
        ticket.response_due = ticket.resolution_due = None
        return
    if not ticket.acknowledged_at:
        due = engine.add_minutes(sla, start, target.response_minutes)
        ticket.response_due = min(due, ticket.response_due) if keep_earlier and ticket.response_due else due
    if ticket.priority == Priority.P1 and ticket.status == Status.WAITING_PREREQ:
        # P1 : la résolution ne démarre qu'à la prise en charge actée (sauvegarde saine + devis validé).
        ticket.resolution_due = None
        return
    due = engine.add_minutes(sla, start, target.resolution_minutes)
    ticket.resolution_due = min(due, ticket.resolution_due) if keep_earlier and ticket.resolution_due else due


def _pause(ticket, now):
    sla = ticket.contract.sla
    ticket.paused_at = now
    ticket.paused_remaining = engine.elapsed_minutes(sla, now, ticket.resolution_due) if (sla and ticket.resolution_due) else None


def _resume(ticket, now):
    sla, target = _target(ticket)
    if ticket.paused_remaining is not None and sla:
        ticket.resolution_due = engine.add_minutes(sla, now, ticket.paused_remaining)
    elif ticket.resolution_due is None and target:
        # Sortie de « En attente de prérequis » : l'horloge de résolution démarre maintenant.
        ticket.resolution_due = engine.add_minutes(sla, now, target.resolution_minutes)
    ticket.paused_at = None
    ticket.paused_remaining = None


# --- Création ------------------------------------------------------------------------

@transaction.atomic
def create_ticket(actor, contract, title, description, solutions=(), priority=Priority.P4, channel=Channel.PORTAL,
                  requester=None, now=None):
    now = now or timezone.now()
    _require(can_write(actor))
    _require(writable_contracts(actor).filter(pk=contract.pk).exists(), _("Contrat non accessible."))
    priority = int(priority)
    # Tout ticket s'ouvre en P4 ou P3 ; P2 et P1 s'obtiennent ensuite par escalade justifiée.
    _require(priority not in ESCALATION_ONLY_PRIORITIES, _("Un ticket s'ouvre en P4 ou en P3."))

    sla = contract.sla
    out_of_coverage = False
    if sla and not engine.is_covered(sla, now):
        if actor.is_client:
            raise CoverageError(engine.next_coverage_start(sla, now))
        out_of_coverage = True

    solutions = list(solutions)
    for s in solutions:
        if s.contract_id != contract.pk or not s.is_active:
            raise ValidationError(_("Une solution sélectionnée n'appartient pas à ce contrat."))

    requester = requester or actor
    if requester.is_client and contract.client_id not in requester.organisation.scope_ids():
        raise ValidationError(_("Le demandeur doit appartenir au client du contrat."))

    ticket = Ticket(contract=contract, title=title.strip(), description=description.strip(), priority=priority,
                    channel=channel, requester=requester, created_by=actor, out_of_coverage=out_of_coverage,
                    created_at=now, updated_at=now, reference=TicketSequence.next_reference(timezone.localtime(now).year))
    _set_deadlines(ticket, now)
    ticket.full_clean(exclude=["solutions"])
    ticket.save()
    ticket.solutions.set(solutions)
    _event(ticket, actor, Event.Kind.CREATED, at=now, priority=priority, channel=channel, out_of_coverage=out_of_coverage)
    if out_of_coverage:
        _event(ticket, actor, Event.Kind.SLA, at=now, internal=True, note="created_out_of_coverage")
    return ticket


# --- Priorité ------------------------------------------------------------------------

def allowed_priorities(user, ticket):
    if not (can_write(user) and ticket.is_open):
        return []
    if user.is_aptitude:
        return [p for p in Priority.values if p != ticket.priority]
    # Client : escalade de P4 vers P3 uniquement.
    return [Priority.P3] if ticket.priority == Priority.P4 else []


@transaction.atomic
def change_priority(actor, ticket, new, justification="", now=None):
    now = now or timezone.now()
    new = int(new)
    _require(new in allowed_priorities(actor, ticket), _("Changement de priorité non autorisé."))
    justification = (justification or "").strip()
    if new in PRIORITIES_REQUIRING_JUSTIFICATION and len(justification) < 10:
        raise ValidationError(_("Une justification d'au moins 10 caractères est obligatoire pour passer en P1 ou P2."))
    old = ticket.priority
    ticket.priority = new
    if new == Priority.P1:
        if ticket.status in (Status.WAITING_CLIENT,):
            ticket.paused_at = ticket.paused_remaining = None
        ticket.status = Status.WAITING_PREREQ
        _set_deadlines(ticket, now, keep_earlier=True)
        ticket.resolution_due = None
    else:
        if ticket.status == Status.WAITING_PREREQ:
            ticket.status = Status.IN_PROGRESS
            ticket.resolution_due = None
        _set_deadlines(ticket, now, keep_earlier=new < old)
        if ticket.status == Status.WAITING_CLIENT:
            _pause(ticket, now)
    ticket.save()
    _event(ticket, actor, Event.Kind.PRIORITY, at=now, old=old, new=new, justification=justification)
    return ticket


# --- Statut ----------------------------------------------------------------------------

APTITUDE_TRANSITIONS = {
    Status.NEW: {Status.ACKNOWLEDGED, Status.IN_PROGRESS, Status.WAITING_CLIENT, Status.RESOLVED, Status.CLOSED},
    Status.ACKNOWLEDGED: {Status.IN_PROGRESS, Status.WAITING_CLIENT, Status.RESOLVED},
    Status.IN_PROGRESS: {Status.WAITING_CLIENT, Status.RESOLVED},
    Status.WAITING_CLIENT: {Status.IN_PROGRESS, Status.RESOLVED},
    Status.WAITING_PREREQ: {Status.IN_PROGRESS, Status.RESOLVED},
    Status.RESOLVED: {Status.IN_PROGRESS, Status.CLOSED},
    Status.CLOSED: set(),
}


def allowed_statuses(user, ticket):
    if not can_write(user):
        return []
    if user.is_aptitude:
        options = set(APTITUDE_TRANSITIONS.get(ticket.status, set()))
        if ticket.priority == Priority.P1 and ticket.status == Status.WAITING_PREREQ:
            options = {Status.IN_PROGRESS, Status.RESOLVED}
        return [s for s in Status.values if s in options]
    # Client : réouvrir un ticket résolu.
    return [Status.IN_PROGRESS] if ticket.status == Status.RESOLVED else []


@transaction.atomic
def change_status(actor, ticket, new, now=None, _system=False):
    now = now or timezone.now()
    if not _system:
        _require(new in allowed_statuses(actor, ticket), _("Changement de statut non autorisé."))
    old = ticket.status
    was_paused = old in (Status.WAITING_CLIENT, Status.WAITING_PREREQ)
    ticket.status = new

    if new in (Status.ACKNOWLEDGED, Status.IN_PROGRESS) and not ticket.acknowledged_at:
        _acknowledge(ticket, now)
    if new == Status.WAITING_CLIENT:
        _pause(ticket, now)
    elif was_paused and new in OPEN_STATUSES:
        _resume(ticket, now)
    if new == Status.RESOLVED:
        if not ticket.acknowledged_at:
            _acknowledge(ticket, now)
        ticket.resolved_at = now
        ticket.resolution_breached = bool(ticket.resolution_due and now > ticket.resolution_due)
        ticket.paused_at = ticket.paused_remaining = None
    if old == Status.RESOLVED and new == Status.IN_PROGRESS:
        ticket.resolved_at = None
        ticket.resolution_breached = False
    if new == Status.CLOSED:
        ticket.closed_at = now
    ticket.save()
    _event(ticket, actor, Event.Kind.STATUS, at=now, old=old, new=new, automatic=_system)
    return ticket


def _acknowledge(ticket, now):
    ticket.acknowledged_at = now
    ticket.response_breached = bool(ticket.response_due and now > ticket.response_due)


# --- Assignation ------------------------------------------------------------------------

def assignable_users(ticket):
    from accounts.models import User
    qs = User.objects.filter(is_active=True, profile__in=[Profile.APTITUDE_ADMIN, Profile.APTITUDE_MANAGER,
                                                          Profile.TECH_ALL, Profile.TECH_ASSIGNED])
    return [u for u in qs.order_by("first_name", "last_name") if visible_contracts(u).filter(pk=ticket.contract_id).exists()]


@transaction.atomic
def assign(actor, ticket, user, now=None):
    now = now or timezone.now()
    _require(actor.is_aptitude and can_write(actor))
    if user is not None and user not in assignable_users(ticket):
        raise ValidationError(_("Cette personne n'a pas accès au contrat du ticket."))
    old = ticket.assignee
    ticket.assignee = user
    ticket.save(update_fields=["assignee"])
    _event(ticket, actor, Event.Kind.ASSIGNED, at=now, old=str(old) if old else None, new=str(user) if user else None)
    return ticket


# --- Suivis et pièces jointes --------------------------------------------------------------

def validate_upload(f):
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(_("Type de fichier non accepté : %(ext)s") % {"ext": ext or "?"})
    if f.size > MAX_ATTACHMENT_BYTES:
        raise ValidationError(_("Fichier trop volumineux (10 Mo maximum) : %(name)s") % {"name": f.name})


@transaction.atomic
def add_comment(actor, ticket, body, internal=False, files=(), now=None):
    now = now or timezone.now()
    _require(can_write(actor))
    _require(visible_tickets(actor).filter(pk=ticket.pk).exists())
    _require(ticket.status != Status.CLOSED, _("Ce ticket est clos."))
    if internal:
        _require(actor.is_aptitude, _("Seule l'équipe Aptitude peut écrire une note interne."))
    body = (body or "").strip()
    files = list(files)
    if not body and not files:
        raise ValidationError(_("Écrivez un message ou joignez un fichier."))
    for f in files:
        validate_upload(f)

    comment = Comment.objects.create(ticket=ticket, author=actor, body=body, is_internal=internal, created_at=now)
    for f in files:
        Attachment.objects.create(ticket=ticket, comment=comment, file=f, name=os.path.basename(f.name)[:255],
                                  size=f.size, content_type=getattr(f, "content_type", "")[:100],
                                  sha256=Attachment.digest(f), uploaded_by=actor, created_at=now)
    _event(ticket, actor, Event.Kind.COMMENT, at=now, internal=internal, comment=comment.pk)

    # Effets sur le cycle de vie
    if actor.is_aptitude and not internal and ticket.status == Status.NEW:
        change_status(actor, ticket, Status.ACKNOWLEDGED, now=now, _system=True)
    elif actor.is_client and ticket.status == Status.WAITING_CLIENT:
        change_status(actor, ticket, Status.IN_PROGRESS, now=now, _system=True)
    elif actor.is_client and ticket.status == Status.RESOLVED:
        change_status(actor, ticket, Status.IN_PROGRESS, now=now, _system=True)
    return comment


# --- Lecture : état SLA pour l'affichage -------------------------------------------------------

def _fmt(minutes):
    minutes = max(0, int(minutes))
    h, m = divmod(minutes, 60)
    if h >= 48:
        d, h = divmod(h, 24)
        return f"{d} j {h} h" if h else f"{d} j"
    if h and m:
        return f"{h} h {m:02d}"
    return f"{h} h" if h else f"{m} min"


def sla_status(ticket, now=None):
    """État de l'échéance en cours : ce qui compte pour l'utilisateur à cet instant."""
    now = now or timezone.now()
    sla, target = _target(ticket)
    if not sla or not target:
        return {"state": "none", "label": _("Sans SLA"), "pct": 0}
    if ticket.status == Status.CLOSED or ticket.status == Status.RESOLVED:
        missed = ticket.resolution_breached or ticket.response_breached
        return {"state": "missed" if missed else "met", "label": _("Délai dépassé") if missed else _("Délai tenu"),
                "pct": 100}
    if ticket.status == Status.WAITING_PREREQ:
        return {"state": "paused", "label": _("Suspendu : prérequis à fournir"), "pct": 0}
    if ticket.status == Status.WAITING_CLIENT:
        left = ticket.paused_remaining
        return {"state": "paused", "label": _("En pause, attente du client"), "pct": _pct(target.resolution_minutes, left)}

    if not ticket.acknowledged_at and ticket.response_due:
        due, total, kind = ticket.response_due, target.response_minutes, _("Prise en charge")
    elif ticket.resolution_due:
        due, total, kind = ticket.resolution_due, target.resolution_minutes, _("Résolution")
    else:
        return {"state": "none", "label": "—", "pct": 0}

    if now >= due:
        late = engine.elapsed_minutes(sla, due, now) if not sla.is_24x7 else int((now - due).total_seconds() // 60)
        return {"state": "late", "label": _("%(kind)s dépassée de %(t)s") % {"kind": kind, "t": _fmt(late)},
                "pct": 100, "due": due, "kind": kind}
    left = engine.elapsed_minutes(sla, now, due)
    pct = _pct(total, left)
    state = "risk" if pct >= RISK_THRESHOLD * 100 else "ok"
    return {"state": state, "label": _("%(kind)s : reste %(t)s") % {"kind": kind, "t": _fmt(left)},
            "pct": pct, "due": due, "kind": kind, "left": left}


def _pct(total, left):
    if not total or left is None:
        return 0
    return max(0, min(100, round((total - left) * 100 / total)))


# --- Tâche planifiée : clôture automatique ---------------------------------------------------------

def auto_close(now=None):
    now = now or timezone.now()
    closed = 0
    for t in Ticket.objects.filter(status=Status.RESOLVED, resolved_at__lte=now - AUTO_CLOSE_AFTER):
        change_status(None, t, Status.CLOSED, now=now, _system=True)
        closed += 1
    return closed
