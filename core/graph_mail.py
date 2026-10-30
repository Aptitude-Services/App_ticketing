"""Envoi des emails par l'API Microsoft Graph (remplace SMTP AUTH, coupé fin 2026).

L'application s'authentifie avec son propre secret (flux « client credentials ») et
envoie au nom de la boîte GRAPH_MAIL_SENDER. Elle a besoin de l'autorisation
d'application Mail.Send, limitée à cette boîte par une ApplicationAccessPolicy.

Activation : EMAIL_BACKEND=core.graph_mail.GraphEmailBackend
"""
import base64
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parseaddr

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
SEND_URL = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
TIMEOUT = 30

_token_cache = {}
_token_lock = threading.Lock()


class GraphError(Exception):
    pass


def _post(url, data, headers):
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        # Le corps de la réponse d'erreur dit pourquoi (secret expiré, droit manquant…).
        raise GraphError(f"HTTP {exc.code} sur {url.split('?')[0]} : {exc.read()[:500]!r}") from exc
    except urllib.error.URLError as exc:
        raise GraphError(f"Microsoft Graph injoignable : {exc.reason}") from exc


def _recipients(addresses):
    result = []
    for address in addresses:
        name, email = parseaddr(address)
        entry = {"emailAddress": {"address": email}}
        if name:
            entry["emailAddress"]["name"] = name
        result.append(entry)
    return result


class GraphEmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.tenant_id = settings.GRAPH_TENANT_ID
        self.client_id = settings.GRAPH_CLIENT_ID
        self.client_secret = settings.GRAPH_CLIENT_SECRET
        self.sender = settings.GRAPH_MAIL_SENDER or parseaddr(settings.DEFAULT_FROM_EMAIL)[1]
        if not (self.tenant_id and self.client_id and self.client_secret and self.sender):
            raise ImproperlyConfigured(
                "Envoi Graph : GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET et "
                "GRAPH_MAIL_SENDER (ou DEFAULT_FROM_EMAIL) doivent être définis."
            )

    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages:
            if not message.recipients():
                continue
            try:
                self._send(message)
                sent += 1
            except GraphError:
                logger.exception("Échec de l'envoi Graph à %s", ", ".join(message.recipients()))
                if not self.fail_silently:
                    raise
        return sent

    def _token(self):
        key = (self.tenant_id, self.client_id)
        with _token_lock:
            cached = _token_cache.get(key)
            if cached and cached[1] > time.time() + 60:
                return cached[0]
            data = urllib.parse.urlencode({
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            }).encode()
            _status, body = _post(
                TOKEN_URL.format(tenant=self.tenant_id), data,
                {"Content-Type": "application/x-www-form-urlencoded"},
            )
            payload = json.loads(body)
            _token_cache[key] = (payload["access_token"], time.time() + int(payload.get("expires_in", 3600)))
            return payload["access_token"]

    def _payload(self, message):
        content_type, content = "Text", message.body
        if message.content_subtype == "html":
            content_type = "HTML"
        for alternative, mimetype in getattr(message, "alternatives", []):
            if mimetype == "text/html":
                content_type, content = "HTML", alternative
        graph_message = {
            "subject": message.subject,
            "body": {"contentType": content_type, "content": content},
            "toRecipients": _recipients(message.to),
            "ccRecipients": _recipients(message.cc),
            "bccRecipients": _recipients(message.bcc),
        }
        if message.reply_to:
            graph_message["replyTo"] = _recipients(message.reply_to)
        attachments = []
        for attachment in message.attachments:
            if isinstance(attachment, tuple):
                filename, data, mimetype = attachment
            else:  # pièce jointe MIME déjà construite
                filename = attachment.get_filename()
                data = attachment.get_payload(decode=True)
                mimetype = attachment.get_content_type()
            if isinstance(data, str):
                data = data.encode()
            attachments.append({
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": filename or "piece-jointe",
                "contentType": mimetype or "application/octet-stream",
                "contentBytes": base64.b64encode(data).decode(),
            })
        if attachments:
            graph_message["attachments"] = attachments
        return {"message": graph_message, "saveToSentItems": True}

    def _send(self, message):
        _post(
            SEND_URL.format(sender=urllib.parse.quote(self.sender)),
            json.dumps(self._payload(message)).encode(),
            {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"},
        )
