"""Tickets, suivis, pièces jointes et historique."""
import hashlib
import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from contracts.models import Contract, Solution
from sla.models import Priority


class Status(models.TextChoices):
    NEW = "new", _("Nouveau")
    ACKNOWLEDGED = "acknowledged", _("Pris en charge")
    IN_PROGRESS = "in_progress", _("En cours")
    WAITING_CLIENT = "waiting_client", _("En attente client")
    WAITING_PREREQ = "waiting_prereq", _("En attente de prérequis")
    RESOLVED = "resolved", _("Résolu")
    CLOSED = "closed", _("Clos")


OPEN_STATUSES = {Status.NEW, Status.ACKNOWLEDGED, Status.IN_PROGRESS, Status.WAITING_CLIENT, Status.WAITING_PREREQ}
PAUSED_STATUSES = {Status.WAITING_CLIENT, Status.WAITING_PREREQ}


class Channel(models.TextChoices):
    PORTAL = "portal", _("Portail")
    EMAIL = "email", _("Email")
    API = "api", _("API")
    PHONE = "phone", _("Téléphone")


class TicketSequence(models.Model):
    """Compteur annuel des références APT-AAAA-NNNNN."""

    year = models.PositiveIntegerField(primary_key=True)
    last = models.PositiveIntegerField(default=0)

    @classmethod
    def next_reference(cls, year):
        with transaction.atomic():
            seq, _ = cls.objects.select_for_update().get_or_create(year=year)
            seq.last += 1
            seq.save(update_fields=["last"])
            return f"APT-{year}-{seq.last:05d}"


class Ticket(models.Model):
    reference = models.CharField(_("référence"), max_length=20, unique=True, editable=False)
    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name="tickets", verbose_name=_("contrat"))
    solutions = models.ManyToManyField(Solution, related_name="tickets", blank=True, verbose_name=_("solutions"))
    title = models.CharField(_("titre"), max_length=200)
    description = models.TextField(_("description"))
    priority = models.PositiveSmallIntegerField(_("priorité"), choices=Priority.choices, default=Priority.P4)
    forfait = models.CharField(
        _("forfait"), max_length=120, blank=True,
        help_text=_("Formule du contrat au moment de l'ouverture (ex. GOLD)."),
    )
    status = models.CharField(_("statut"), max_length=20, choices=Status.choices, default=Status.NEW, db_index=True)
    channel = models.CharField(_("canal"), max_length=10, choices=Channel.choices, default=Channel.PORTAL)

    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_tickets",
                                  verbose_name=_("demandeur"))
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_tickets")
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="assigned_tickets", verbose_name=_("assigné à"))
    out_of_coverage = models.BooleanField(_("créé hors couverture"), default=False,
                                          help_text=_("Créé par Aptitude hors heures ouvrées sur un contrat 8x5."))

    created_at = models.DateTimeField(_("créé le"), default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(_("mis à jour le"), default=timezone.now, db_index=True)
    acknowledged_at = models.DateTimeField(_("pris en charge le"), null=True, blank=True)
    resolved_at = models.DateTimeField(_("résolu le"), null=True, blank=True)
    closed_at = models.DateTimeField(_("clos le"), null=True, blank=True)

    # Échéances SLA (None = horloge non démarrée, ex. P1 en attente de prérequis)
    response_due = models.DateTimeField(_("échéance de prise en charge"), null=True, blank=True)
    resolution_due = models.DateTimeField(_("échéance de résolution"), null=True, blank=True)
    response_breached = models.BooleanField(default=False)
    resolution_breached = models.BooleanField(default=False)
    paused_at = models.DateTimeField(null=True, blank=True)
    paused_remaining = models.PositiveIntegerField(
        null=True, blank=True, help_text=_("Minutes SLA restantes au moment de la pause."))

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("ticket")
        verbose_name_plural = _("tickets")
        indexes = [models.Index(fields=["status", "resolution_due"])]

    def __str__(self):
        return f"{self.reference} — {self.title}"

    @property
    def short_ref(self):
        return self.reference

    @property
    def is_open(self):
        return self.status in OPEN_STATUSES

    @property
    def is_paused(self):
        return self.status in PAUSED_STATUSES

    def clean(self):
        if self.priority not in Priority.values:
            raise ValidationError({"priority": _("Priorité invalide.")})


def _upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower()[:10]
    return f"tickets/{instance.ticket.created_at:%Y/%m}/{uuid.uuid4().hex}{ext}"


class Comment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    body = models.TextField(_("message"))
    is_internal = models.BooleanField(_("note interne"), default=False,
                                      help_text=_("Visible uniquement par l'équipe Aptitude."))
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]
        verbose_name = _("suivi")
        verbose_name_plural = _("suivis")


class Attachment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, null=True, blank=True, related_name="attachments")
    file = models.FileField(upload_to=_upload_to)
    name = models.CharField(max_length=255)
    size = models.PositiveIntegerField()
    content_type = models.CharField(max_length=100, blank=True)
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]
        verbose_name = _("pièce jointe")
        verbose_name_plural = _("pièces jointes")

    @property
    def is_internal(self):
        return bool(self.comment_id and self.comment.is_internal)

    @staticmethod
    def digest(django_file):
        h = hashlib.sha256()
        for chunk in django_file.chunks():
            h.update(chunk)
        django_file.seek(0)
        return h.hexdigest()


class Event(models.Model):
    """Historique : chaque changement de statut, priorité, assignation, échéance."""

    class Kind(models.TextChoices):
        CREATED = "created", _("Création")
        STATUS = "status", _("Changement de statut")
        PRIORITY = "priority", _("Changement de priorité")
        ASSIGNED = "assigned", _("Assignation")
        COMMENT = "comment", _("Suivi")
        SLA = "sla", _("Événement SLA")

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    data = models.JSONField(default=dict, blank=True)
    is_internal = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = _("événement")
        verbose_name_plural = _("historique")
