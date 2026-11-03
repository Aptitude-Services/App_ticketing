"""Référentiel contrats : types de contrat (porteurs du SLA), contrats, solutions, accès."""
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from accounts.models import Organisation, Profile, User
from sla.models import SLA


class ContractType(models.Model):
    """Ex. « Infogérance 24x7 », « Maintenance 8x5 ». Chaque type porte un SLA."""

    name = models.CharField(_("nom"), max_length=120, unique=True)
    description = models.TextField(_("description"), blank=True)
    sla = models.ForeignKey(SLA, on_delete=models.PROTECT, related_name="contract_types", verbose_name=_("SLA"))
    is_active = models.BooleanField(_("actif"), default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("type de contrat")
        verbose_name_plural = _("types de contrat")

    def __str__(self):
        return self.name


class Contract(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Brouillon")
        ACTIVE = "active", _("Actif")
        EXPIRED = "expired", _("Expiré")
        TERMINATED = "terminated", _("Résilié")

    reference = models.CharField(_("référence"), max_length=50, unique=True)
    title = models.CharField(_("intitulé"), max_length=200)
    client = models.ForeignKey(
        Organisation, on_delete=models.PROTECT, related_name="contracts",
        limit_choices_to={"kind": Organisation.Kind.CLIENT}, verbose_name=_("client"),
    )
    contract_type = models.ForeignKey(
        ContractType, on_delete=models.PROTECT, related_name="contracts", null=True,
        verbose_name=_("type de contrat"),
    )
    start_date = models.DateField(_("début"))
    end_date = models.DateField(_("fin"), null=True, blank=True)
    status = models.CharField(_("statut"), max_length=20, choices=Status.choices, default=Status.ACTIVE)
    # Prévu, inactif en V1 (forfait d'heures ou de tickets)
    allowance_hours = models.PositiveIntegerField(_("forfait d'heures"), null=True, blank=True)
    allowance_tickets = models.PositiveIntegerField(_("forfait de tickets"), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["client__name", "reference"]
        verbose_name = _("contrat")
        verbose_name_plural = _("contrats")

    def __str__(self):
        return f"{self.reference} — {self.title}"

    @property
    def sla(self):
        return self.contract_type.sla if self.contract_type_id else None

    @property
    def coverage(self):
        return self.sla.coverage if self.sla else None

    def get_coverage_display(self):
        return self.sla.get_coverage_display() if self.sla else "—"

    def clean(self):
        if not self.contract_type_id:
            raise ValidationError({"contract_type": _("Le type de contrat est obligatoire.")})
        if self.client_id and self.client.is_aptitude:
            raise ValidationError({"client": _("Un contrat doit appartenir à une organisation cliente.")})
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": _("La fin doit suivre le début.")})


class Solution(models.Model):
    """Élément couvert par un contrat : logiciel, matériel, machine virtuelle, cloud ou autre."""

    class Category(models.TextChoices):
        SOFTWARE = "software", _("Software")
        HARDWARE = "hardware", _("Hardware")
        VM = "vm", _("Machine virtuelle")
        CLOUD = "cloud", _("Cloud")
        OTHER = "other", _("Autre")

    # Descriptif affiché au survol de chaque catégorie, pour guider la saisie.
    CATEGORY_HELP = {
        "software": _("Logiciel ou licence installé chez le client : antivirus, sauvegarde, SIEM, système…"),
        "hardware": _("Équipement physique : serveur, pare-feu, switch, routeur, poste, stockage…"),
        "vm": _("Machine virtuelle hébergée sur un hyperviseur (VMware, Hyper-V, Proxmox…)."),
        "cloud": _("Service ou abonnement en ligne : Microsoft 365, Azure, AWS, SaaS…"),
        "other": _("Tout autre élément : onduleur, imprimante, téléphonie, service…"),
    }

    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="solutions", verbose_name=_("contrat"))
    category = models.CharField(_("catégorie"), max_length=20, choices=Category.choices)
    vendor = models.CharField(_("éditeur"), max_length=120, blank=True)
    model = models.CharField(_("modèle"), max_length=120, blank=True)
    version = models.CharField(_("version"), max_length=120, blank=True)
    name = models.CharField(_("nom"), max_length=200)
    serial_number = models.CharField(_("n° de série"), max_length=120, blank=True)
    location = models.CharField(_("localisation"), max_length=200, blank=True)
    license_start = models.DateField(_("début de licence"), null=True, blank=True)
    license_end = models.DateField(_("fin de licence"), null=True, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["contract", "category", "name"]
        verbose_name = _("solution")
        verbose_name_plural = _("solutions")

    def __str__(self):
        return f"{self.name} ({self.category_label})"

    @property
    def category_label(self):
        return self.get_category_display()

    def clean(self):
        if self.license_start and self.license_end and self.license_end < self.license_start:
            raise ValidationError({"license_end": _("La fin de licence doit suivre le début.")})


class ContractAccess(models.Model):
    """Contrat ouvert à un utilisateur précis.

    Sert à deux cas : un technicien « contrats affectés », et un utilisateur
    client que son admin a limité à certains contrats.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="contract_accesses")
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="accesses")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "contract")]
        verbose_name = _("accès contrat")
        verbose_name_plural = _("accès contrats")

    def __str__(self):
        return f"{self.user} → {self.contract.reference}"

    def clean(self):
        if not self.user_id:
            return
        # À la création d'un contrat dans l'administration, le contrat n'a pas encore d'identifiant :
        # on contrôle quand même l'accès sur le contrat en cours de saisie.
        try:
            contract = self.contract
        except Contract.DoesNotExist:
            return
        if self.user.is_client and contract.client_id not in self.user.organisation.scope_ids():
            raise ValidationError(_("Un utilisateur client ne peut accéder qu'aux contrats de son organisation."))
        if self.user.is_aptitude and self.user.profile != Profile.TECH_ASSIGNED:
            raise ValidationError(_("Seuls les profils « Engineer (restricted) » reçoivent des affectations."))

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
