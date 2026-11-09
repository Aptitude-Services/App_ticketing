"""Rapports d'intervention : curatif (un ticket), préventif (une visite), trimestriel (consolidé).

Les informations connues de l'application (contrat, ESN, client final, ticket, SLA,
solutions, historique) sont extraites automatiquement ; le reste est saisi par le
rédacteur dans `data`. À la validation, les données extraites sont figées dans
`data["snapshot"]` et une empreinte SHA-256 est calculée : le rapport est verrouillé.
"""
import hashlib
import json

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import Organisation
from contracts.models import Contract


class ReportSequence(models.Model):
    """Compteur des références, par préfixe RPT-TYPE-ESN-CLIENTFINAL-ANNÉE."""

    prefix = models.CharField(max_length=60, primary_key=True)
    last = models.PositiveIntegerField(default=0)

    @classmethod
    def next_reference(cls, prefix):
        with transaction.atomic():
            seq, _created = cls.objects.select_for_update().get_or_create(prefix=prefix)
            while True:
                seq.last += 1
                reference = f"{prefix}-{seq.last:03d}"
                if not Report.objects.filter(reference=reference).exists():
                    break
            seq.save(update_fields=["last"])
            return reference


class Report(models.Model):
    class Kind(models.TextChoices):
        CURATIVE = "curatif", _("Maintenance curative")
        PREVENTIVE = "preventif", _("Maintenance préventive")
        QUARTERLY = "trimestriel", _("Rapport trimestriel")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Brouillon")
        SUBMITTED = "submitted", _("À valider")
        REJECTED = "rejected", _("À corriger")
        VALIDATED = "validated", _("Validé")
        SENT = "sent", _("Envoyé au client")

    KIND_CODES = {"curatif": "CUR", "preventif": "PRV", "trimestriel": "TRI"}
    EDITABLE = {Status.DRAFT, Status.REJECTED}

    reference = models.CharField(
        _("référence"), max_length=60, unique=True, editable=False,
        help_text=_("RPT-TYPE-ESN-CLIENTFINAL-AAAA-NNN, ex. RPT-CUR-HUD-BLAG-2026-001."),
    )
    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices)
    status = models.CharField(_("statut"), max_length=20, choices=Status.choices, default=Status.DRAFT,
                              db_index=True)
    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name="reports",
                                 verbose_name=_("contrat"))
    end_client = models.ForeignKey(
        Organisation, on_delete=models.PROTECT, null=True, blank=True, related_name="reports",
        limit_choices_to={"kind": Organisation.Kind.END_CLIENT}, verbose_name=_("client final"),
    )
    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.PROTECT, null=True, blank=True,
                               related_name="reports", verbose_name=_("ticket"))
    period_start = models.DateField(_("début de période"), null=True, blank=True)
    period_end = models.DateField(_("fin de période"), null=True, blank=True)
    title = models.CharField(_("intitulé"), max_length=200, blank=True)
    data = models.JSONField(_("contenu"), default=dict, blank=True)

    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reports_written",
                               verbose_name=_("rédacteur"))
    created_at = models.DateTimeField(_("rédigé le"), default=timezone.now)
    updated_at = models.DateTimeField(_("modifié le"), auto_now=True)
    submitted_at = models.DateTimeField(_("soumis le"), null=True, blank=True)
    validator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name="reports_validated", verbose_name=_("validé par"))
    validated_at = models.DateTimeField(_("validé le"), null=True, blank=True)
    rejection_comment = models.TextField(_("motif de la demande de correction"), blank=True)
    sent_at = models.DateTimeField(_("envoyé le"), null=True, blank=True)
    sent_to = models.TextField(_("envoyé à"), blank=True)
    client_validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name=_("confirmé par le client"))
    client_validated_at = models.DateTimeField(_("confirmé le"), null=True, blank=True)
    fingerprint = models.CharField(_("empreinte SHA-256"), max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("rapport")
        verbose_name_plural = _("rapports")

    def __str__(self):
        return f"{self.reference} — {self.get_kind_display()}"

    @property
    def esn(self):
        return self.contract.client

    @property
    def is_editable(self):
        return self.status in self.EDITABLE

    @property
    def is_locked(self):
        return self.status in {self.Status.VALIDATED, self.Status.SENT}

    @property
    def quarter(self):
        return (self.period_start.month - 1) // 3 + 1 if self.period_start else None

    @property
    def quarter_label(self):
        return f"T{self.quarter} {self.period_start.year}" if self.period_start else ""

    def reference_prefix(self):
        year = (self.period_start or timezone.localdate()).year
        stamp = f"{year}T{self.quarter}" if self.kind == self.Kind.QUARTERLY and self.period_start else str(year)
        end = self.end_client.code if self.end_client_id else "GEN"
        return "-".join(["RPT", self.KIND_CODES[self.kind], self.contract.client.code, end, stamp])

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = ReportSequence.next_reference(self.reference_prefix())
        super().save(*args, **kwargs)

    def compute_fingerprint(self):
        payload = json.dumps({"ref": self.reference, "data": self.data}, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
