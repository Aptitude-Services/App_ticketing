from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Organisation(models.Model):
    """Aptitude, un client ESN, ou un client final d'une ou plusieurs ESN."""

    class Kind(models.TextChoices):
        APTITUDE = "aptitude", _("Aptitude")
        CLIENT = "client", _("Client ESN")
        END_CLIENT = "end_client", _("Client final")

    class ActivitySector(models.TextChoices):
        BANK = "bank", _("Banque")
        HEALTH = "health", _("Santé")
        TELECOM = "telecom", _("Télécommunications")
        INSURANCE = "insurance", _("Assurance")
        PUBLIC = "public", _("Administration publique")
        ENERGY = "energy", _("Énergie")
        INDUSTRY = "industry", _("Industrie")
        RETAIL = "retail", _("Commerce et distribution")
        EDUCATION = "education", _("Éducation")
        TRANSPORT = "transport", _("Transport")
        OTHER = "other", _("Autre")

    name = models.CharField(_("nom"), max_length=200, unique=True)
    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices, default=Kind.CLIENT)
    activity_sector = models.CharField(
        _("secteur d'activité"), max_length=30, choices=ActivitySector.choices, blank=True,
        help_text=_("Obligatoire pour un client ESN ou un client final ; vide pour Aptitude."),
    )
    end_clients = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="partner_esns",
        verbose_name=_("clients finaux"),
        help_text=_("Clients finaux de cette ESN. Un même client final peut être rattaché à plusieurs ESN, "
                    "chacune intervenant sur ses propres solutions."),
    )
    is_active = models.BooleanField(_("active"), default=True)
    email_domains = models.CharField(
        _("domaines email"), max_length=500, blank=True,
        help_text=_("Domaines séparés par des virgules, ex. client.ci, client.com"),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("organisation")
        verbose_name_plural = _("organisations")

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        client_kinds = {self.Kind.CLIENT, self.Kind.END_CLIENT}
        if self.kind in client_kinds and not self.activity_sector:
            raise ValidationError({"activity_sector": _("Choisissez le secteur d'activité.")})
        if self.kind == self.Kind.APTITUDE and self.activity_sector:
            raise ValidationError({"activity_sector": _("Aptitude n'a pas de secteur d'activité.")})
        if self.pk:
            self.clean_links()

    def clean_links(self):
        """Contrôle les rattachements déjà enregistrés (indisponibles avant la sauvegarde)."""
        if not self.pk:
            return
        if self.kind != self.Kind.CLIENT and self.end_clients.exists():
            raise ValidationError({"kind": _("Retirez les clients finaux avant de changer ce type d'organisation.")})
        if self.end_clients.exclude(kind=self.Kind.END_CLIENT).exists():
            raise ValidationError({"end_clients": _("Seuls des clients finaux peuvent être rattachés à une ESN.")})
        if self.kind != self.Kind.END_CLIENT and self.partner_esns.exists():
            raise ValidationError({"kind": _("Retirez les ESN rattachées avant de changer ce type d'organisation.")})
        if self.partner_esns.exclude(kind=self.Kind.CLIENT).exists():
            raise ValidationError(_("Un client final ne se rattache qu'à des clients ESN."))

    @property
    def is_aptitude(self):
        return self.kind == self.Kind.APTITUDE

    @property
    def is_esn(self):
        return self.kind == self.Kind.CLIENT

    @property
    def is_end_client(self):
        return self.kind == self.Kind.END_CLIENT

    def scope_ids(self):
        """Organisations dont les comptes sont gérés : elle-même, et ses clients finaux si c'est une ESN."""
        ids = [self.pk]
        if self.is_esn:
            ids += list(self.end_clients.values_list("pk", flat=True))
        return ids

    def relates_to(self, contract) -> bool:
        """Vrai si l'organisation est l'ESN du contrat, un de ses clients finaux historiques, ou un client final couvert."""
        if contract.client_id in self.scope_ids():
            return True
        if self.is_end_client and contract.pk:
            return contract.end_clients.filter(pk=self.pk).exists()
        return False

    def domain_list(self):
        return [d.strip().lower() for d in self.email_domains.split(",") if d.strip()]


class Profile(models.TextChoices):
    APTITUDE_ADMIN = "aptitude_admin", "Super Admin"
    APTITUDE_MANAGER = "aptitude_manager", "Manager"
    TECH_ALL = "tech_all", "Engineer"
    TECH_ASSIGNED = "tech_assigned", "Engineer (restricted)"
    CLIENT_ADMIN = "client_admin", "Client Admin"
    CLIENT_RW = "client_rw", "Client User"
    CLIENT_RO = "client_ro", "Client Viewer"


# Profils en réserve : gardés dans le code, mais plus proposés à l'attribution.
# Retirer un profil de cet ensemble suffit à le rendre de nouveau disponible.
STANDBY_PROFILES = {Profile.TECH_ASSIGNED}
APTITUDE_PROFILES = {Profile.APTITUDE_ADMIN, Profile.APTITUDE_MANAGER, Profile.TECH_ALL, Profile.TECH_ASSIGNED}
CLIENT_PROFILES = {Profile.CLIENT_ADMIN, Profile.CLIENT_RW, Profile.CLIENT_RO}


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("L'email est obligatoire.")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        org, _created = Organisation.objects.get_or_create(
            kind=Organisation.Kind.APTITUDE, defaults={"name": "Aptitude Services"}
        )
        extra.setdefault("organisation", org)
        extra.setdefault("profile", Profile.APTITUDE_ADMIN)
        extra["is_superuser"] = True
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(_("email"), unique=True)
    first_name = models.CharField(_("prénom"), max_length=100, blank=True)
    last_name = models.CharField(_("nom"), max_length=100, blank=True)
    phone = models.CharField(_("téléphone"), max_length=30, blank=True)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.PROTECT, related_name="users", verbose_name=_("organisation")
    )
    profile = models.CharField(_("profil"), max_length=30, choices=Profile.choices)
    language = models.CharField(_("langue"), max_length=5, choices=[("fr", "Français"), ("en", "English")], default="fr")
    theme = models.CharField(_("thème"), max_length=10, default="system",
                             choices=[("system", _("Comme mon système")), ("light", _("Clair")), ("dark", _("Sombre"))])
    all_contracts = models.BooleanField(
        _("accès à tous les contrats de l'organisation"), default=True,
        help_text=_("Décocher pour limiter l'utilisateur aux contrats sélectionnés."),
    )
    is_active = models.BooleanField(_("actif"), default=True)
    date_joined = models.DateTimeField(_("créé le"), default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["organisation__name", "last_name", "first_name"]
        verbose_name = _("utilisateur")
        verbose_name_plural = _("utilisateurs")

    def __str__(self):
        return self.get_full_name() or self.email

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name or self.email.split("@")[0]

    @property
    def display_name(self):
        return self.get_full_name() or self.email.split("@")[0]

    @property
    def initials(self):
        if self.first_name or self.last_name:
            return ((self.first_name[:1] + self.last_name[:1]) or self.first_name[:2]).upper()
        return self.email[:2].upper()

    def clean(self):
        super().clean()
        self.email = (self.email or "").lower()
        if self.organisation_id and self.profile:
            if self.organisation.is_aptitude and self.profile not in APTITUDE_PROFILES:
                raise ValidationError({"profile": _("Ce profil est réservé aux organisations clientes.")})
            if not self.organisation.is_aptitude and self.profile not in CLIENT_PROFILES:
                raise ValidationError({"profile": _("Ce profil est réservé à Aptitude.")})

    # --- Droits dérivés du profil ------------------------------------------
    @property
    def is_aptitude(self):
        return self.profile in APTITUDE_PROFILES

    @property
    def is_client(self):
        return self.profile in CLIENT_PROFILES

    @property
    def is_staff(self):
        """Accès à l'administration Django : admins et managers Aptitude."""
        return self.is_active and self.profile in {Profile.APTITUDE_ADMIN, Profile.APTITUDE_MANAGER}

    @property
    def sees_all_contracts(self):
        if self.profile in {Profile.APTITUDE_ADMIN, Profile.APTITUDE_MANAGER, Profile.TECH_ALL}:
            return True
        return False

    @property
    def can_write_tickets(self):
        return self.profile != Profile.CLIENT_RO

    @property
    def can_manage_users(self):
        return self.profile in {Profile.APTITUDE_ADMIN, Profile.APTITUDE_MANAGER, Profile.CLIENT_ADMIN}

    @property
    def can_configure(self):
        return self.profile in {Profile.APTITUDE_ADMIN, Profile.APTITUDE_MANAGER}

    @property
    def mfa_required(self):
        return self.is_aptitude

    # --- Permissions de l'administration Django -----------------------------
    MANAGER_APPS = {"accounts", "contracts", "sla", "tickets"}

    def has_perm(self, perm, obj=None):
        if self.is_active and self.profile == Profile.APTITUDE_ADMIN:
            return True
        if self.is_active and self.profile == Profile.APTITUDE_MANAGER and perm.split(".")[0] in self.MANAGER_APPS:
            return True
        return super().has_perm(perm, obj)

    def has_module_perms(self, app_label):
        if self.is_active and self.profile == Profile.APTITUDE_ADMIN:
            return True
        if self.is_active and self.profile == Profile.APTITUDE_MANAGER and app_label in self.MANAGER_APPS:
            return True
        return super().has_module_perms(app_label)


class AuditEvent(models.Model):
    """Journal d'audit : connexions, changements de droits, actions sensibles."""

    class Action(models.TextChoices):
        LOGIN = "login", _("Connexion")
        LOGIN_FAILED = "login_failed", _("Échec de connexion")
        LOGOUT = "logout", _("Déconnexion")
        USER_CREATED = "user_created", _("Utilisateur créé")
        USER_UPDATED = "user_updated", _("Utilisateur modifié")
        MFA_ENABLED = "mfa_enabled", _("MFA activée")
        MAIL_SETTINGS_UPDATED = "mail_settings_updated", _("Messagerie modifiée")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=30, choices=Action.choices)
    target_user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    organisation = models.ForeignKey(Organisation, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("événement d'audit")
        verbose_name_plural = _("journal d'audit")

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.get_action_display()}"
