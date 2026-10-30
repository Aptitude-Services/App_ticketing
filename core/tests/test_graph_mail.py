"""Envoi par l'API Microsoft Graph : jeton, message, erreurs (sans appel réseau)."""
import base64
import io
import json
import urllib.error

import pytest
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMultiAlternatives

from core import graph_mail

BACKEND = "core.graph_mail.GraphEmailBackend"


@pytest.fixture
def graph(settings, monkeypatch):
    settings.EMAIL_BACKEND = BACKEND
    settings.GRAPH_TENANT_ID = "tenant-id"
    settings.GRAPH_CLIENT_ID = "client-id"
    settings.GRAPH_CLIENT_SECRET = "secret"
    settings.GRAPH_MAIL_SENDER = ""
    settings.DEFAULT_FROM_EMAIL = "Aptitude Support <support@aptitudes.net>"
    graph_mail._token_cache.clear()
    calls = []

    def fake_post(url, data, headers):
        calls.append((url, data, headers))
        if "oauth2" in url:
            return 200, json.dumps({"access_token": "jeton", "expires_in": 3600}).encode()
        return 202, b""

    monkeypatch.setattr(graph_mail, "_post", fake_post)
    return calls


def test_invitation_is_sent_through_graph(graph):
    mail.send_mail("Votre accès", "Bonjour", None, ["Awa Koné <awa@client.ci>"])

    token_call, send_call = graph
    assert token_call[0] == "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/token"
    assert b"grant_type=client_credentials" in token_call[1]
    assert send_call[0] == "https://graph.microsoft.com/v1.0/users/support%40aptitudes.net/sendMail"
    assert send_call[2]["Authorization"] == "Bearer jeton"
    message = json.loads(send_call[1])["message"]
    assert message["subject"] == "Votre accès"
    assert message["body"] == {"contentType": "Text", "content": "Bonjour"}
    assert message["toRecipients"] == [{"emailAddress": {"address": "awa@client.ci", "name": "Awa Koné"}}]


def test_token_is_reused_between_messages(graph):
    mail.send_mail("Un", "corps", None, ["a@client.ci"])
    mail.send_mail("Deux", "corps", None, ["b@client.ci"])
    assert sum("oauth2" in url for url, _data, _headers in graph) == 1


def test_html_alternative_and_attachment(graph):
    message = EmailMultiAlternatives("Rapport", "texte", to=["a@client.ci"], cc=["b@client.ci"])
    message.attach_alternative("<p>html</p>", "text/html")
    message.attach("rapport.txt", b"contenu", "text/plain")
    message.send()

    sent = json.loads(graph[-1][1])["message"]
    assert sent["body"] == {"contentType": "HTML", "content": "<p>html</p>"}
    assert sent["ccRecipients"] == [{"emailAddress": {"address": "b@client.ci"}}]
    assert sent["attachments"][0]["name"] == "rapport.txt"
    assert base64.b64decode(sent["attachments"][0]["contentBytes"]) == b"contenu"


def test_missing_configuration_is_reported(graph, settings):
    settings.GRAPH_CLIENT_SECRET = ""
    with pytest.raises(ImproperlyConfigured):
        mail.send_mail("Sujet", "corps", None, ["a@client.ci"])


def test_graph_error_is_raised_unless_fail_silently(settings, monkeypatch):
    settings.EMAIL_BACKEND = BACKEND
    settings.GRAPH_TENANT_ID, settings.GRAPH_CLIENT_ID, settings.GRAPH_CLIENT_SECRET = "t", "c", "s"
    graph_mail._token_cache.clear()

    def refused(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b"invalid_client"))

    monkeypatch.setattr(graph_mail.urllib.request, "urlopen", refused)
    with pytest.raises(graph_mail.GraphError, match="HTTP 401.*invalid_client"):
        mail.send_mail("Sujet", "corps", None, ["a@client.ci"])
    assert mail.send_mail("Sujet", "corps", None, ["a@client.ci"], fail_silently=True) == 0
