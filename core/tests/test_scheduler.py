"""Planificateur intégré : les tâches partent seules, sans cron."""
import datetime
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command

from core.management.commands import run_scheduler as S

pytestmark = pytest.mark.django_db
ABJ = ZoneInfo("Africa/Abidjan")


def at(hour, minute=0, day=12):
    return datetime.datetime(2026, 11, day, hour, minute, tzinfo=ABJ)


@pytest.fixture
def calls(monkeypatch):
    done = []
    monkeypatch.setattr(S, "_close_tickets", lambda: done.append("close") or "ok")
    monkeypatch.setattr(S, "_license_alerts", lambda: done.append("licences") or "ok")
    return done


def test_license_alerts_run_in_daytime_once_per_hour(calls):
    last = {}
    S.run_due_jobs(at(9), last)
    assert calls == ["close", "licences"]
    S.run_due_jobs(at(9, 30), last)
    assert calls == ["close", "licences"], "pas deux fois dans la même heure"
    S.run_due_jobs(at(10), last)
    assert calls == ["close", "licences", "close", "licences"]


def test_no_license_email_at_night(calls):
    S.run_due_jobs(at(3), {})
    S.run_due_jobs(at(20), {})
    assert calls == ["close", "close"]


def test_failing_job_is_retried_and_does_not_stop_the_others(monkeypatch):
    done = []

    def broken():
        raise RuntimeError("messagerie injoignable")

    monkeypatch.setattr(S, "_license_alerts", broken)
    monkeypatch.setattr(S, "_close_tickets", lambda: done.append("close") or "ok")
    last = {}
    S.run_due_jobs(at(9), last)
    assert done == ["close"] and "license_alerts" not in last, "retentée à la vérification suivante"


def test_command_once_really_sends_license_alerts(monkeypatch):
    """De bout en bout : la commande appelle bien l'envoi des alertes de licence."""
    import contracts.notifications as N
    sent = []
    monkeypatch.setattr(N, "notify_expiring_licenses", lambda: sent.append(1) or (0, 0))
    monkeypatch.setattr(S.timezone, "localtime", lambda: at(9))
    call_command("run_scheduler", "--once")
    assert sent == [1]
