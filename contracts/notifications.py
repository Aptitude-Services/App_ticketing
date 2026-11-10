"""Alertes d'expiration de licence envoyées au client ESN.

Deux déclencheurs :
- automatique : la commande ``notify_license_expiry`` (tâche planifiée quotidienne)
  prévient l'ESN à 60, 30, 15 et 7 jours de l'échéance, puis le jour même ;
- manuel : l'action « Notifier l'ESN » de l'administration (solutions ou contrats).

Un seul email par ESN et par envoi, qui liste toutes ses licences concernées.
"""
import datetime
from collections import defaultdict

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from accounts.models import Profile, User

from .models import Contract, LicenseNotice, Solution

THRESHOLDS = (60, 30, 15, 7, 0)
HORIZON = max(THRESHOLDS)


class LicenseMailError(Exception):
    """L'email d'alerte n'a pas pu partir (messagerie mal configurée ou injoignable)."""

    def __init__(self, recipients):
        super().__init__(", ".join(recipients))
        self.recipients = recipients


def esn_recipients(esn):
    """Administrateurs de l'ESN ; à défaut, tous ses utilisateurs actifs."""
    users = User.objects.filter(organisation=esn, is_active=True)
    admins = [u.email for u in users.filter(profile=Profile.CLIENT_ADMIN)]
    return admins or [u.email for u in users]


def threshold_for(days_left):
    """Plus petit seuil atteint : 45 jours restants → seuil 60 ; 10 jours → seuil 15."""
    reached = [t for t in THRESHOLDS if days_left <= t]
    return min(reached) if reached else None


def expiring_solutions(today=None, horizon=HORIZON):
    today = today or timezone.localdate()
    return (Solution.objects.filter(
        is_active=True, license_end__isnull=False,
        license_end__gte=today, license_end__lte=today + datetime.timedelta(days=horizon),
        contract__status__in=[Contract.Status.ACTIVE, Contract.Status.DRAFT],
    ).select_related("contract__client").prefetch_related("contract__end_clients").order_by("license_end"))


def _contract_url(contract):
    path = reverse("contract_detail", args=[contract.pk])
    return f"{settings.SITE_URL.rstrip('/')}{path}" if settings.SITE_URL else path


def _body(esn, solutions, today):
    lines = [
        _("Bonjour,"),
        "",
        _("Les licences suivantes, couvertes par vos contrats de support, arrivent bientôt à expiration :"),
        "",
    ]
    for sol in solutions:
        contract = sol.contract
        ends = ", ".join(e.name for e in contract.end_clients.all()) or "—"
        days = (sol.license_end - today).days
        when = _("aujourd'hui") if days == 0 else _("dans %(d)d jour(s)") % {"d": days}
        lines.append(f"- {sol.name} ({sol.category_label}) — {_('fin de licence le')} "
                     f"{sol.license_end:%d/%m/%Y}, {when}")
        lines.append(f"  {_('Contrat')} {contract.reference} · {_('Client final')} : {ends}")
        lines.append(f"  {_contract_url(contract)}")
    lines += [
        "",
        _("Pensez à engager le renouvellement auprès de vos clients finaux pour éviter toute interruption de service."),
        "",
        _("L'équipe Aptitude Support"),
    ]
    return "\n".join(lines)


def send_license_notice(esn, solutions, actor=None, threshold=0, manual=False, today=None):
    """Envoie l'alerte à l'ESN et la trace. Renvoie la liste des destinataires (vide si personne)."""
    today = today or timezone.localdate()
    solutions = list(solutions)
    recipients = esn_recipients(esn)
    if not solutions or not recipients:
        return []
    soonest = min(s.license_end for s in solutions)
    subject = _("[Aptitude] %(n)d licence(s) expirent bientôt — première échéance le %(d)s") % {
        "n": len(solutions), "d": soonest.strftime("%d/%m/%Y")}
    try:
        sent = send_mail(subject, _body(esn, solutions, today), None, recipients, fail_silently=True)
    except Exception:
        sent = 0
    if not sent:
        # Échec d'envoi (inscrit au journal des emails) : rien n'est tracé, l'alerte sera retentée.
        raise LicenseMailError(recipients)
    LicenseNotice.objects.bulk_create([
        LicenseNotice(solution=s, license_end=s.license_end, threshold=threshold if not manual else
                      max(0, (s.license_end - today).days), manual=manual,
                      recipients=", ".join(recipients), sent_by=actor)
        for s in solutions
    ])
    return recipients


def notify_expiring_licenses(today=None):
    """Alertes automatiques : une par solution et par seuil atteint. Renvoie (emails, solutions)."""
    today = today or timezone.localdate()
    by_esn = defaultdict(list)
    for sol in expiring_solutions(today):
        threshold = threshold_for((sol.license_end - today).days)
        if threshold is None:
            continue
        already = LicenseNotice.objects.filter(solution=sol, license_end=sol.license_end, manual=False,
                                               threshold__lte=threshold).exists()
        if already:
            continue
        sol._threshold = threshold
        by_esn[sol.contract.client].append(sol)

    emails = solutions = 0
    for esn, sols in by_esn.items():
        # Un email par seuil, pour que la trace reflète l'échéance réellement annoncée.
        by_threshold = defaultdict(list)
        for s in sols:
            by_threshold[s._threshold].append(s)
        for threshold, group in sorted(by_threshold.items()):
            try:
                ok = send_license_notice(esn, group, threshold=threshold, today=today)
            except LicenseMailError:
                continue
            if ok:
                emails += 1
                solutions += len(group)
    return emails, solutions
