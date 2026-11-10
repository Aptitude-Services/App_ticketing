"""Commande delete_user : supprime un compte vierge, désactive un compte qui a un historique."""
import pytest
from django.core.management import CommandError, call_command

from accounts.models import User
from reports.tests.test_reports import w  # noqa: F401  (fixture partagée)

pytestmark = pytest.mark.django_db


def test_unused_account_is_deleted(w):
    call_command("delete_user", w["other_mgr"].email.upper())
    assert not User.objects.filter(pk=w["other_mgr"].pk).exists()


def test_account_with_history_is_deactivated_not_deleted(w):
    call_command("delete_user", w["end_user"].email)  # a ouvert un ticket
    w["end_user"].refresh_from_db()
    assert w["end_user"].is_active is False


def test_unknown_email(w):
    with pytest.raises(CommandError):
        call_command("delete_user", "inconnu@nulle-part.ci")
