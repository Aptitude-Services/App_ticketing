"""SLA, objectifs par priorité et jours fériés."""
import datetime

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class Priority(models.IntegerChoices):
    """P1 est la plus haute. Un ticket naît en P4."""

    P1 = 1, _("P1 — Très élevée")
    P2 = 2, _("P2 — Élevée")
    P3 = 3, _("P3 — Moyenne")
    P4 = 4, _("P4 — Basse")


PRIORITY_NAMES = {
    Priority.P1: _("Très élevée"),
    Priority.P2: _("Élevée"),
    Priority.P3: _("Moyenne"),
    Priority.P4: _("Basse"),
}

PRIORITY_DEFINITIONS = {
    Priority.P1: _("Dysfonctionnement majeur avec fort impact sur la production à la suite d'une cyber-attaque. "
                   "Interruption partielle ou totale de services, sans contournement. Prise en charge actée dès "
                   "disponibilité d'une sauvegarde saine et validation du devis."),
    Priority.P2: _("Dysfonctionnement majeur avec fort impact sur la production. Interruption totale de services, "
                   "sans contournement."),
    Priority.P3: _("Dysfonctionnement avec impact sur la production. Interruption intermittente de services, "
                   "sans contournement."),
    Priority.P4: _("Dysfonctionnement avec faible impact sur la production. Pas d'interruption de services, "
                   "contournement disponible."),
}

# Profils autorisés par priorité : le client va jusqu'à P3, Aptitude seule en P2 et P1.
CLIENT_MAX_PRIORITY = Priority.P3
PRIORITIES_REQUIRING_JUSTIFICATION = {Priority.P1, Priority.P2}


class SLA(models.Model):
    class Coverage(models.TextChoices):
        H24X7 = "24x7", "24x7"
        H8X5 = "8x5", "8x5"

    name = models.CharField(_("nom"), max_length=100, unique=True)
    coverage = models.CharField(_("couverture"), max_length=5, choices=Coverage.choices)
    day_start = models.TimeField(_("début de journée"), default=datetime.time(8, 0),
                                 help_text=_("Utilisé en 8x5 uniquement."))
    day_end = models.TimeField(_("fin de journée"), default=datetime.time(17, 0))
    working_days = models.CharField(
        _("jours ouvrés"), max_length=20, default="0,1,2,3,4",
        help_text=_("Utilisé en 8x5 uniquement. Stocké de 0 (lundi) à 6 (dimanche), saisi par cases à cocher."),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("SLA")
        verbose_name_plural = _("SLA")

    def __str__(self):
        return self.name

    def clean(self):
        if self.coverage == self.Coverage.H8X5 and self.day_end <= self.day_start:
            raise ValidationError({"day_end": _("La fin de journée doit suivre le début.")})
        try:
            days = self.weekdays()
        except ValueError:
            raise ValidationError({"working_days": _("Format attendu : 0,1,2,3,4")})
        if not days or any(d < 0 or d > 6 for d in days):
            raise ValidationError({"working_days": _("Jours entre 0 et 6.")})

    def weekdays(self):
        return {int(d) for d in self.working_days.split(",") if d.strip() != ""}

    @property
    def is_24x7(self):
        return self.coverage == self.Coverage.H24X7

    def target(self, priority):
        return self.targets.filter(priority=priority).first()


class SLATarget(models.Model):
    sla = models.ForeignKey(SLA, on_delete=models.CASCADE, related_name="targets")
    priority = models.PositiveSmallIntegerField(_("priorité"), choices=Priority.choices)
    response_minutes = models.PositiveIntegerField(_("prise en charge (minutes)"))
    resolution_minutes = models.PositiveIntegerField(_("résolution (minutes)"))

    class Meta:
        ordering = ["sla", "priority"]
        unique_together = [("sla", "priority")]
        verbose_name = _("objectif SLA")
        verbose_name_plural = _("objectifs SLA")

    def __str__(self):
        return f"{self.sla} · P{self.priority}"

    def clean(self):
        if self.response_minutes and self.resolution_minutes and self.response_minutes > self.resolution_minutes:
            raise ValidationError(_("La prise en charge ne peut pas dépasser la résolution."))


class Holiday(models.Model):
    """Jour férié et chômé en Côte d'Ivoire, exclu du calcul en 8x5."""

    class Kind(models.TextChoices):
        FIXED = "fixed", _("Fixe")
        COMPUTED = "computed", _("Calculé (Pâques)")
        ANNOUNCED = "announced", _("Annoncé par le gouvernement")
        SUBSTITUTE = "substitute", _("Lundi chômé (report)")

    date = models.DateField(_("date"), unique=True)
    name = models.CharField(_("nom"), max_length=120)
    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices, default=Kind.FIXED)

    class Meta:
        ordering = ["date"]
        verbose_name = _("jour férié")
        verbose_name_plural = _("jours fériés")

    def __str__(self):
        return f"{self.date:%d/%m/%Y} — {self.name}"
