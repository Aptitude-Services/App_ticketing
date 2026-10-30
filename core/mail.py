"""Module Messagerie : envoi des emails selon la configuration saisie dans l'application.

EMAIL_BACKEND pointe toujours ici. Selon le mode choisi dans Configuration > Messagerie,
les messages partent par un serveur SMTP, par Microsoft 365 (API Graph), par le
backend défini dans le .env (MAIL_ENV_BACKEND), ou ne partent pas (mode désactivé).
Chaque message est inscrit au journal OutgoingMail, avec l'erreur en cas d'échec.
"""
import logging
from email.utils import parseaddr

from django.conf import settings
from django.core.mail import get_connection
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend
from django.db import DatabaseError

from .graph_mail import GraphEmailBackend

logger = logging.getLogger(__name__)

SMTP_TIMEOUT = 30
SELF = "core.mail.AppEmailBackend"


def current_settings():
    from .models import MailSettings

    try:
        return MailSettings.load()
    except DatabaseError:  # base pas encore migrée : on reste sur le .env
        logger.warning("Configuration de la messagerie illisible, envoi selon le .env")
        return MailSettings()


def env_backend_path():
    path = getattr(settings, "MAIL_ENV_BACKEND", "") or "django.core.mail.backends.console.EmailBackend"
    return "django.core.mail.backends.console.EmailBackend" if path == SELF else path


def build_backend(config):
    """Backend qui fait réellement l'envoi pour cette configuration (None si désactivé)."""
    P = config.Provider
    if config.provider == P.OFF:
        return None
    if config.provider == P.SMTP:
        return SMTPBackend(
            host=config.smtp_host, port=config.smtp_port,
            username=config.smtp_username, password=config.smtp_password,
            use_tls=config.smtp_security == config.Security.STARTTLS,
            use_ssl=config.smtp_security == config.Security.SSL,
            timeout=SMTP_TIMEOUT, fail_silently=False,
        )
    if config.provider == P.GRAPH:
        return GraphEmailBackend(
            tenant_id=config.graph_tenant_id, client_id=config.graph_client_id,
            client_secret=config.graph_client_secret,
            sender=config.graph_sender or parseaddr(config.from_email or settings.DEFAULT_FROM_EMAIL)[1],
        )
    return get_connection(env_backend_path(), fail_silently=False)


class AppEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        from .models import OutgoingMail

        messages = [m for m in email_messages if m.recipients()]
        if not messages:
            return 0
        config = current_settings()
        for message in messages:
            if config.from_email and message.from_email == settings.DEFAULT_FROM_EMAIL:
                message.from_email = config.from_email
            if config.reply_to and not message.reply_to:
                message.reply_to = [config.reply_to]

        def log(message, status, error=""):
            OutgoingMail.objects.create(
                provider=config.provider, sender=message.from_email[:254],
                recipients=", ".join(message.recipients()), subject=(message.subject or "")[:500],
                status=status, error=error[:2000],
            )

        try:
            # Configuration incomplète ou serveur injoignable : rien ne part.
            backend = build_backend(config)
            if backend is not None:
                backend.open()
        except Exception as exc:
            for message in messages:
                log(message, OutgoingMail.Status.FAILED, _describe(exc))
            logger.exception("Messagerie inutilisable (%s)", config.provider)
            if not self.fail_silently:
                raise
            return 0
        if backend is None:
            for message in messages:
                log(message, OutgoingMail.Status.SKIPPED)
            return 0

        sent = 0
        try:
            for message in messages:
                try:
                    backend.send_messages([message])
                except Exception as exc:
                    log(message, OutgoingMail.Status.FAILED, _describe(exc))
                    logger.exception("Échec de l'envoi à %s", ", ".join(message.recipients()))
                    if not self.fail_silently:
                        raise
                else:
                    log(message, OutgoingMail.Status.SENT)
                    sent += 1
        finally:
            try:
                backend.close()
            except Exception:
                logger.warning("Fermeture de la connexion d'envoi impossible", exc_info=True)
        return sent


def _describe(exc):
    return f"{type(exc).__name__} : {exc}"
