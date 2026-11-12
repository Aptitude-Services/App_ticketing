"""Module Messagerie : choix du mode d'envoi, journal, secrets chiffrés, page de configuration."""
import json

import pytest
from django.core import mail
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import AuditEvent, Organisation, Profile, User
from core import graph_mail
from core import mail as app_mail
from core.models import MailSettings, OutgoingMail

pytestmark = pytest.mark.django_db

LOCMEM = "django.core.mail.backends.locmem.EmailBackend"


@pytest.fixture(autouse=True)
def app_backend(settings):
    settings.EMAIL_BACKEND = "core.mail.AppEmailBackend"
    settings.MAIL_ENV_BACKEND = LOCMEM
    settings.DEFAULT_FROM_EMAIL = "support@aptitudes.net"


def configure(**fields):
    config = MailSettings.load()
    for name, value in fields.items():
        setattr(config, name, value)
    config.save()
    return config


class FakeSMTP:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeSMTP.instances.append(self)

    def open(self):
        return True

    def close(self):
        pass

    def send_messages(self, messages):
        return len(messages)


# --- Envoi --------------------------------------------------------------------

def test_env_mode_uses_backend_from_env_and_logs(settings):
    configure(from_email="Aptitude Support <support@aptitudes.net>", reply_to="noreply@aptitudes.net")
    assert mail.send_mail("Bienvenue", "corps", None, ["awa@client.ci"]) == 1

    assert mail.outbox[0].from_email == "Aptitude Support <support@aptitudes.net>"
    assert mail.outbox[0].reply_to == ["noreply@aptitudes.net"]
    log = OutgoingMail.objects.get()
    assert (log.status, log.provider, log.recipients, log.subject) == ("sent", "env", "awa@client.ci", "Bienvenue")


def test_env_backend_pointing_to_module_falls_back_to_console(settings):
    settings.MAIL_ENV_BACKEND = "core.mail.AppEmailBackend"
    assert app_mail.env_backend_path() == "django.core.mail.backends.console.EmailBackend"


def test_off_mode_sends_nothing_but_logs():
    configure(provider=MailSettings.Provider.OFF)
    assert mail.send_mail("Sujet", "corps", None, ["a@client.ci"]) == 0
    assert mail.outbox == []
    assert OutgoingMail.objects.get().status == "skipped"


def test_smtp_mode_uses_saved_parameters(monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(app_mail, "SMTPBackend", FakeSMTP)
    configure(provider="smtp", smtp_host="mail.hebergeur.ci", smtp_port=465, smtp_security="ssl",
              smtp_username="support@aptitudes.net", smtp_password="s3cret")
    assert mail.send_mail("Sujet", "corps", None, ["a@client.ci"]) == 1

    kwargs = FakeSMTP.instances[0].kwargs
    assert (kwargs["host"], kwargs["port"], kwargs["password"]) == ("mail.hebergeur.ci", 465, "s3cret")
    assert kwargs["use_ssl"] is True and kwargs["use_tls"] is False
    assert OutgoingMail.objects.get().provider == "smtp"


def test_smtp_failure_is_logged_and_raised_unless_fail_silently(monkeypatch):
    class Failing(FakeSMTP):
        def send_messages(self, messages):
            raise OSError("connexion refusée")

    monkeypatch.setattr(app_mail, "SMTPBackend", Failing)
    configure(provider="smtp", smtp_host="mail.hebergeur.ci")
    with pytest.raises(OSError):
        mail.send_mail("Sujet", "corps", None, ["a@client.ci"])
    assert mail.send_mail("Sujet", "corps", None, ["a@client.ci"], fail_silently=True) == 0
    failures = OutgoingMail.objects.filter(status="failed")
    assert failures.count() == 2 and "connexion refusée" in failures.first().error


def test_graph_mode_uses_saved_microsoft_365_parameters(monkeypatch):
    graph_mail._token_cache.clear()
    calls = []

    def fake_post(url, data, headers):
        calls.append(url)
        if "oauth2" in url:
            return 200, json.dumps({"access_token": "jeton", "expires_in": 3600}).encode()
        return 202, b""

    monkeypatch.setattr(graph_mail, "_post", fake_post)
    configure(provider="graph", graph_tenant_id="tenant-app", graph_client_id="client-app",
              graph_client_secret="secret", from_email="Support <envoi@aptitudes.net>")
    assert mail.send_mail("Sujet", "corps", None, ["a@client.ci"]) == 1
    assert calls == [
        "https://login.microsoftonline.com/tenant-app/oauth2/v2.0/token",
        "https://graph.microsoft.com/v1.0/users/envoi%40aptitudes.net/sendMail",
    ]


def test_incomplete_graph_configuration_is_logged(settings):
    settings.GRAPH_TENANT_ID = settings.GRAPH_CLIENT_ID = settings.GRAPH_CLIENT_SECRET = ""
    configure(provider="graph", graph_tenant_id="t")
    assert mail.send_mail("Sujet", "corps", None, ["a@client.ci"], fail_silently=True) == 0
    assert OutgoingMail.objects.get().status == "failed"


# --- Secrets ------------------------------------------------------------------

def test_secrets_are_encrypted_and_unreadable_after_key_change(settings):
    config = configure(smtp_password="s3cret", graph_client_secret="graph-secret")
    raw = MailSettings.objects.values_list("smtp_password_encrypted", "graph_client_secret_encrypted").get()
    assert "s3cret" not in raw[0] and "graph-secret" not in raw[1]
    assert MailSettings.load().smtp_password == "s3cret"
    settings.SECRET_KEY = "une-autre-cle"
    assert config.smtp_password == ""


# --- Page de configuration ------------------------------------------------------

@pytest.fixture
def people():
    apt = Organisation.objects.create(name="Aptitude Services", kind=Organisation.Kind.CLIENT, is_operator=True)
    client_org = Organisation.objects.create(name="Client A")

    def mk(email, org, profile):
        return User.objects.create_user(email, "Motdepasse-tres-long-1", organisation=org, profile=profile)

    return {
        "admin": mk("admin@aptitudes.net", apt, Profile.APTITUDE_ADMIN),
        "manager": mk("manager@aptitudes.net", apt, Profile.APTITUDE_MANAGER),
        "client_admin": mk("admin@a.ci", client_org, Profile.CLIENT_ADMIN),
    }


def login(client, user):
    if user.is_aptitude:
        TOTPDevice.objects.create(user=user, name="app", confirmed=True)
    client.force_login(user)
    if user.is_aptitude:
        session = client.session
        session[DEVICE_ID_SESSION_KEY] = user.totpdevice_set.first().persistent_id
        session.save()


@pytest.mark.parametrize("who", ["manager", "client_admin"])
def test_only_aptitude_admin_reaches_mail_settings(client, people, who):
    login(client, people[who])
    assert client.get(reverse("mail_settings")).status_code == 404
    assert client.post(reverse("mail_test"), {"to": "x@y.ci"}).status_code == 404


def test_admin_saves_smtp_settings_and_blank_password_keeps_secret(client, people):
    login(client, people["admin"])
    url = reverse("mail_settings")
    assert client.get(url).status_code == 200
    data = {"provider": "smtp", "from_email": "Aptitude Support <support@aptitudes.net>", "reply_to": "",
            "smtp_host": "mail.hebergeur.ci", "smtp_port": 587, "smtp_security": "starttls",
            "smtp_username": "support@aptitudes.net", "smtp_password": "s3cret",
            "graph_tenant_id": "", "graph_client_id": "", "graph_sender": ""}
    assert client.post(url, data).status_code == 302
    data["smtp_password"] = ""
    client.post(url, data)

    config = MailSettings.load()
    assert (config.provider, config.smtp_password, config.updated_by) == ("smtp", "s3cret", people["admin"])
    audit = AuditEvent.objects.filter(action=AuditEvent.Action.MAIL_SETTINGS_UPDATED).first()
    assert "s3cret" not in json.dumps(audit.details)


def test_graph_mode_requires_its_parameters(client, people):
    login(client, people["admin"])
    response = client.post(reverse("mail_settings"), {"provider": "graph", "smtp_port": 587, "smtp_security": "starttls"})
    assert response.status_code == 200
    assert set(response.context["form"].errors) == {"graph_tenant_id", "graph_client_id", "graph_client_secret"}


def test_admin_sends_test_email(client, people):
    login(client, people["admin"])
    response = client.post(reverse("mail_test"), {"to": "admin@aptitudes.net"})
    assert response.status_code == 302
    assert mail.outbox[0].to == ["admin@aptitudes.net"]
    assert OutgoingMail.objects.get().status == "sent"
