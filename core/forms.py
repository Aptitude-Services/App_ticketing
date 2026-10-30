from email.utils import parseaddr

from django import forms
from django.core.validators import validate_email
from django.utils.translation import gettext_lazy as _

from .models import MailSettings


class MailSettingsForm(forms.ModelForm):
    """Mode d'envoi et paramètres. Un secret laissé vide conserve celui déjà enregistré."""

    smtp_password = forms.CharField(
        label=_("mot de passe"), required=False, strip=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
    )
    graph_client_secret = forms.CharField(
        label=_("secret client"), required=False, strip=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
    )
    clear_smtp_password = forms.BooleanField(label=_("Effacer le mot de passe enregistré"), required=False)

    class Meta:
        model = MailSettings
        fields = [
            "provider", "from_email", "reply_to",
            "smtp_host", "smtp_port", "smtp_security", "smtp_username",
            "graph_tenant_id", "graph_client_id", "graph_sender",
        ]
        widgets = {"provider": forms.RadioSelect}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, has in (("smtp_password", self.instance.smtp_password_encrypted),
                          ("graph_client_secret", self.instance.graph_client_secret_encrypted)):
            if has:
                self.fields[name].help_text = (
                    _("Enregistré. Laisser vide pour le conserver.") if getattr(self.instance, name)
                    else _("Illisible (clé du serveur changée) : à ressaisir.")
                )

    def clean_from_email(self):
        value = self.cleaned_data["from_email"].strip()
        if value:
            validate_email(parseaddr(value)[1])
        return value

    def clean(self):
        data = super().clean()
        P = MailSettings.Provider
        provider = data.get("provider")
        required = []
        if provider == P.SMTP:
            required = ["smtp_host", "smtp_port"]
        elif provider == P.GRAPH:
            required = ["graph_tenant_id", "graph_client_id"]
            if not (data.get("graph_client_secret") or self.instance.graph_client_secret):
                self.add_error("graph_client_secret", _("Ce champ est obligatoire pour Microsoft 365."))
        for name in required:
            if not data.get(name):
                self.add_error(name, _("Ce champ est obligatoire pour ce mode d'envoi."))
        return data

    def save(self, commit=True):
        config = super().save(commit=False)
        if self.cleaned_data.get("clear_smtp_password"):
            config.smtp_password = ""
        elif self.cleaned_data.get("smtp_password"):
            config.smtp_password = self.cleaned_data["smtp_password"]
        if self.cleaned_data.get("graph_client_secret"):
            config.graph_client_secret = self.cleaned_data["graph_client_secret"]
        if commit:
            config.save()
        return config


class MailTestForm(forms.Form):
    to = forms.EmailField(label=_("Envoyer un email de test à"))
