"""Référentiel contrats : types de contrat (porteurs du SLA), contrats, solutions, accès."""
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import Organisation, Profile, User
from sla.models import SLA


class ContractSequence(models.Model):
    """Compteur des références de contrat, par préfixe ESN[-client final]-année.

    Ex. préfixe « HUD-BLAG-2026 » → HUD-BLAG-2026-001, HUD-BLAG-2026-002…
    """

    prefix = models.CharField(max_length=40, primary_key=True)
    last = models.PositiveIntegerField(default=0)

    @classmethod
    def next_reference(cls, prefix):
        with transaction.atomic():
            seq, _ = cls.objects.select_for_update().get_or_create(prefix=prefix)
            while True:
                seq.last += 1
                reference = f"{prefix}-{seq.last:03d}"
                # Une référence saisie à la main par le passé pourrait déjà exister.
                if not Contract.objects.filter(reference=reference).exists():
                    break
            seq.save(update_fields=["last"])
            return reference


def contract_reference_prefix(client, end_clients=(), year=None):
    """Préfixe lisible : code ESN, code client final (ou MULTI s'il y en a plusieurs), année."""
    year = year or timezone.localdate().year
    parts = [client.code]
    end_clients = list(end_clients)
    if len(end_clients) == 1:
        parts.append(end_clients[0].code)
    elif len(end_clients) > 1:
        parts.append("MULTI")
    parts.append(str(year))
    return "-".join(parts)


class ServiceFeature(models.Model):
    """Critère ou prestation de service d'une formule (ex. Support N3, Supervision, SOC...)."""

    class Category(models.TextChoices):
        SUPPORT = "support", _("Support & Niveaux")
        SUPERVISION = "supervision", _("Supervision & Monitoring")
        SECURITY = "security", _("Sécurité, SOC & Incidents")
        CHANGES = "changes", _("Gestion des changements")
        GOVERNANCE = "governance", _("Gouvernance & Conformité")
        INFRASTRUCTURE = "infrastructure", _("Infrastructure & Matériel")

    code = models.CharField(_("code"), max_length=60, unique=True)
    name = models.CharField(_("intitulé"), max_length=150)
    category = models.CharField(_("catégorie"), max_length=30, choices=Category.choices, default=Category.SUPPORT)
    description = models.TextField(_("description"), blank=True)
    order = models.PositiveSmallIntegerField(_("ordre"), default=10)
    is_active = models.BooleanField(_("actif"), default=True)

    class Meta:
        ordering = ["category", "order", "name"]
        verbose_name = _("critère de service")
        verbose_name_plural = _("critères de service")

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"


class ContractType(models.Model):
    """Ex. « STARTER », « BRONZE », « SILVER », « GOLD », « PLATINUM ».

    Chaque formule porte un SLA et un ensemble de critères / prestations.
    """

    name = models.CharField(_("nom"), max_length=120, unique=True)
    description = models.TextField(_("description"), blank=True)
    sla = models.ForeignKey(SLA, on_delete=models.PROTECT, related_name="contract_types", verbose_name=_("SLA"))
    positioning = models.CharField(
        _("positionnement"), max_length=150, blank=True,
        help_text=_("Ex. Garantie SAV, Assistance essentielle, Assistance opérationnelle, MSSP..."),
    )
    target_clients = models.CharField(
        _("type de clients"), max_length=150, blank=True,
        help_text=_("Ex. Tout client, PME – non critique, SI critiques, Banques / Telco..."),
    )
    scope = models.CharField(
        _("périmètre couvert"), max_length=150, blank=True,
        help_text=_("Ex. Support incidents, Support + supervision, Managed Security Services..."),
    )
    billing_mode = models.CharField(
        _("mode de facturation"), max_length=150, blank=True,
        help_text=_("Ex. Gratuit, CFA/équipement/mois, Forfait..."),
    )
    commitment_period = models.CharField(
        _("engagement contractuel"), max_length=150, blank=True,
        help_text=_("Ex. Min: 1 mois - Max: 3 mois, Annuel..."),
    )
    features = models.ManyToManyField(
        ServiceFeature, blank=True, related_name="contract_types",
        verbose_name=_("critères inclus dans la formule"),
    )
    allowance_tickets = models.PositiveIntegerField(
        _("forfait de tickets"), null=True, blank=True,
        help_text=_("Nombre de tickets inclus, repris par défaut sur les contrats de cette formule. "
                    "Vide : illimité."),
    )
    is_active = models.BooleanField(_("actif"), default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("formule / type de contrat")
        verbose_name_plural = _("formules / types de contrat")

    def __str__(self):
        return self.name

    def features_by_category(self):
        """Regroupe les critères de la formule par catégorie."""
        by_cat = {}
        for feat in self.features.filter(is_active=True).order_by("category", "order", "name"):
            by_cat.setdefault(feat.get_category_display(), []).append(feat)
        return by_cat


class Contract(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Brouillon")
        ACTIVE = "active", _("Actif")
        EXPIRED = "expired", _("Expiré")
        TERMINATED = "terminated", _("Résilié")

    reference = models.CharField(
        _("référence"), max_length=50, unique=True, blank=True,
        help_text=_("Attribuée automatiquement à la création : ESN-CLIENTFINAL-AAAA-NNN (ex. HUD-BLAG-2026-001)."),
    )
    title = models.CharField(_("intitulé"), max_length=200)
    client = models.ForeignKey(
        Organisation, on_delete=models.PROTECT, related_name="contracts",
        limit_choices_to={"kind": Organisation.Kind.CLIENT}, verbose_name=_("client ESN"),
    )
    end_clients = models.ManyToManyField(
        Organisation, blank=True, related_name="covered_contracts",
        limit_choices_to={"kind": Organisation.Kind.END_CLIENT}, verbose_name=_("clients finaux"),
        help_text=_("Clients finaux couverts par ce contrat. La liste se limite à ceux rattachés à l'ESN choisie."),
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
    extra_features = models.ManyToManyField(
        ServiceFeature, blank=True, related_name="contracts_extra",
        verbose_name=_("options additionnelles (sur-mesure client)"),
        help_text=_("Critères ou options activés pour ce client en plus de ceux de sa formule de base."),
    )
    excluded_features = models.ManyToManyField(
        ServiceFeature, blank=True, related_name="contracts_excluded",
        verbose_name=_("options exclues"),
        help_text=_("Critères de la formule retirés exceptionnellement pour ce contrat."),
    )
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

    @property
    def active_features(self):
        """Tous les critères actifs pour ce contrat (base + options client - exclusions)."""
        base_features = self.contract_type.features.filter(is_active=True) if self.contract_type_id else ServiceFeature.objects.none()
        extras = self.extra_features.filter(is_active=True)
        excluded_ids = set(self.excluded_features.values_list("id", flat=True))
        all_features = (base_features | extras).distinct()
        if excluded_ids:
            all_features = all_features.exclude(id__in=excluded_ids)
        return all_features.order_by("category", "order", "name")

    def has_feature(self, code: str) -> bool:
        """Vérifie si un critère spécifique est actif sur ce contrat."""
        if self.excluded_features.filter(code=code).exists():
            return False
        if self.extra_features.filter(code=code, is_active=True).exists():
            return True
        if self.contract_type_id:
            return self.contract_type.features.filter(code=code, is_active=True).exists()
        return False

    @property
    def has_support_n3(self) -> bool:
        return self.has_feature("support_n3")

    @property
    def has_supervision_disponibilite(self) -> bool:
        return self.has_feature("supervision_disponibilite")

    @property
    def has_supervision_performance(self) -> bool:
        return self.has_feature("supervision_performance")

    @property
    def has_vulnerabilites(self) -> bool:
        return self.has_feature("gestion_vulnerabilites")

    def active_features_annotated(self):
        """Liste des critères actifs avec indication de leur origine (formule vs sur-mesure client)."""
        base_ids = set(self.contract_type.features.values_list("id", flat=True)) if self.contract_type_id else set()
        extra_ids = set(self.extra_features.values_list("id", flat=True))
        annotated = []
        for feat in self.active_features:
            is_custom = feat.id in extra_ids and feat.id not in base_ids
            annotated.append({
                "feature": feat,
                "is_custom": is_custom,
                "badge": _("Option personnalisée") if is_custom else _("Inclus dans la formule"),
            })
        return annotated

    def active_features_by_category(self):
        """Regroupe les critères actifs par catégorie avec indication custom vs formule."""
        grouped = {}
        for item in self.active_features_annotated():
            cat_label = item["feature"].get_category_display()
            grouped.setdefault(cat_label, []).append(item)
        return grouped

    def assign_reference(self, end_clients=()):
        """Attribue la référence (une seule fois). Les clients finaux sont passés
        explicitement : à la création, la relation n'est pas encore enregistrée."""
        if not self.reference and self.client_id:
            self.reference = ContractSequence.next_reference(contract_reference_prefix(self.client, end_clients))

    def save(self, *args, **kwargs):
        self.assign_reference()  # filet de sécurité hors admin : ESN seule
        super().save(*args, **kwargs)

    def clean(self):
        if not self.contract_type_id:
            raise ValidationError({"contract_type": _("Le type de contrat est obligatoire.")})
        if self.client_id and not self.client.is_esn:
            raise ValidationError({"client": _("Un contrat se rattache à un client ESN.")})
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
        verbose_name = _("affectation au contrat")
        verbose_name_plural = _("affectations aux contrats")

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
        if self.user.is_client and not self.user.organisation.relates_to(contract):
            raise ValidationError(_("Un utilisateur client ne peut accéder qu'aux contrats de son organisation."))
        if self.user.is_aptitude and self.user.profile != Profile.TECH_ASSIGNED:
            raise ValidationError(_("Seuls les profils « Engineer (restricted) » reçoivent des affectations."))

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
