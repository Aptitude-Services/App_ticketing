from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from .crypto import decrypt, encrypt


class MailSettings(models.Model):
    """Configuration de l'envoi des emails, modifiable dans l'application (ligne unique).

    Les secrets (mot de passe SMTP, secret Graph) sont chiffrés en base avec une clé
    dérivée de DJANGO_SECRET_KEY : changer cette clé oblige à les ressaisir.
    """

    class Provider(models.TextChoices):
        ENV = "env", _("Paramètres du serveur (fichier .env)")
        SMTP = "smtp", _("Serveur SMTP")
        GRAPH = "graph", _("Microsoft 365 (API Graph)")
        OFF = "off", _("Désactivé (aucun envoi, journal seulement)")

    class Security(models.TextChoices):
        STARTTLS = "starttls", _("STARTTLS (port 587)")
        SSL = "ssl", _("SSL/TLS implicite (port 465)")
        NONE = "none", _("Aucun chiffrement (relais interne uniquement)")

    provider = models.CharField(_("mode d'envoi"), max_length=10, choices=Provider.choices, default=Provider.ENV)
    from_email = models.CharField(
        _("expéditeur"), max_length=254, blank=True,
        help_text=_("Ex. Aptitude Support <support@aptitudes.net>. Vide : DEFAULT_FROM_EMAIL du serveur."),
    )
    reply_to = models.EmailField(_("adresse de réponse"), blank=True)

    smtp_host = models.CharField(_("serveur SMTP"), max_length=255, blank=True)
    smtp_port = models.PositiveIntegerField(_("port"), default=587)
    smtp_security = models.CharField(_("chiffrement"), max_length=10, choices=Security.choices, default=Security.STARTTLS)
    smtp_username = models.CharField(_("identifiant"), max_length=254, blank=True)
    smtp_password_encrypted = models.TextField(blank=True, editable=False)

    graph_tenant_id = models.CharField(_("ID de locataire (tenant)"), max_length=100, blank=True)
    graph_client_id = models.CharField(_("ID d'application (client)"), max_length=100, blank=True)
    graph_client_secret_encrypted = models.TextField(blank=True, editable=False)
    graph_sender = models.EmailField(
        _("boîte d'envoi"), blank=True, help_text=_("Vide : l'adresse de l'expéditeur."),
    )

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = _("configuration de la messagerie")
        verbose_name_plural = _("configuration de la messagerie")

    def __str__(self):
        return str(self.get_provider_display())

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    smtp_password = property(lambda self: decrypt(self.smtp_password_encrypted),
                             lambda self, value: setattr(self, "smtp_password_encrypted", encrypt(value)))
    graph_client_secret = property(lambda self: decrypt(self.graph_client_secret_encrypted),
                                   lambda self, value: setattr(self, "graph_client_secret_encrypted", encrypt(value)))


class OutgoingMail(models.Model):
    """Journal des emails envoyés par l'application (sans le corps du message)."""

    class Status(models.TextChoices):
        SENT = "sent", _("Envoyé")
        FAILED = "failed", _("Échec")
        SKIPPED = "skipped", _("Non envoyé (messagerie désactivée)")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    provider = models.CharField(_("mode d'envoi"), max_length=10, choices=MailSettings.Provider.choices)
    sender = models.CharField(_("expéditeur"), max_length=254)
    recipients = models.TextField(_("destinataires"))
    subject = models.CharField(_("sujet"), max_length=500)
    status = models.CharField(_("statut"), max_length=10, choices=Status.choices)
    error = models.TextField(_("erreur"), blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("email envoyé")
        verbose_name_plural = _("journal des emails")

    def __str__(self):
        return f"{self.subject} → {self.recipients}"
