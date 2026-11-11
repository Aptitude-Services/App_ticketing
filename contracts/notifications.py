"""Alertes d'expiration de licence.

Destinataires : le client ESN, le client final couvert par le contrat et les managers
d'Aptitude. Deux déclencheurs :
- automatique : la commande ``notify_license_expiry`` (tâche planifiée quotidienne)
  envoie trois alertes, 5 mois, 3 mois puis 1 mois avant l'échéance ;
- manuel : l'action « Notifier l'ESN » de l'administration (solutions ou contrats).

Un email par ESN et par client final : chaque client final ne voit que ses licences.
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

# Alertes à 5, 3 puis 1 mois de l'échéance (mois calendaires). Le seuil tracé sur
# LicenseNotice est exprimé en jours : 150, 90 et 30.
THRESHOLD_MONTHS = (5, 3, 1)
THRESHOLDS = tuple(m * 30 for m in THRESHOLD_MONTHS)
HORIZON = 155  # jours : couvre les 5 mois calendaires les plus longs


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


def end_client_recipients(contract):
    """Administrateurs des clients finaux du contrat ; à défaut, leurs utilisateurs actifs."""
    emails = []
    for end in contract.end_clients.all():
        users = User.objects.filter(organisation=end, is_active=True)
        emails += [u.email for u in users.filter(profile=Profile.CLIENT_ADMIN)] or [u.email for u in users]
    return emails


def manager_recipients():
    return list(User.objects.filter(profile=Profile.APTITUDE_MANAGER, is_active=True).values_list("email", flat=True))


def months_before(day, months):
    """Même jour, `months` mois plus tôt (borné à la fin du mois : 31/07 - 5 mois → 28/02)."""
    import calendar
    y, m = divmod(day.year * 12 + day.month - 1 - months, 12)
    m += 1
    return datetime.date(y, m, min(day.day, calendar.monthrange(y, m)[1]))


def threshold_for(license_end, today):
    """Plus proche alerte atteinte, en jours (150, 90 ou 30) ; None avant les 5 mois ou après l'échéance."""
    if license_end < today:
        return None
    reached = [m for m in THRESHOLD_MONTHS if today >= months_before(license_end, m)]
    return min(reached) * 30 if reached else None


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


def _when(days):
    if days == 0:
        return _("aujourd'hui")
    if days >= 28:
        months = round(days / 30.4)
        return _("dans environ %(m)d mois (%(d)d jours)") % {"m": months, "d": days}
    return _("dans %(d)d jour(s)") % {"d": days}


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
        when = _when((sol.license_end - today).days)
        lines.append(f"- {sol.name} ({sol.category_label}) — {_('fin de licence le')} "
                     f"{sol.license_end:%d/%m/%Y}, {when}")
        lines.append(f"  {_('Contrat')} {contract.reference} · {_('Client final')} : {ends}")
        lines.append(f"  {_contract_url(contract)}")
    lines += [
        "",
        _("Pensez à engager le renouvellement pour éviter toute interruption de service."),
        "",
        _("L'équipe Aptitude Support"),
    ]
    return "\n".join(lines)


def send_license_notice(esn, solutions, actor=None, threshold=0, manual=False, today=None):
    """Envoie l'alerte au client ESN, aux clients finaux concernés et aux managers, puis la trace.

    Un email par groupe de clients finaux : un client final ne reçoit que ses licences.
    Renvoie la liste des destinataires (vide si personne). Lève LicenseMailError si un envoi échoue."""
    today = today or timezone.localdate()
    by_end = defaultdict(list)
    for sol in solutions:
        key = tuple(sorted(e.pk for e in sol.contract.end_clients.all()))
        by_end[key].append(sol)
    sent_to = []
    for group in by_end.values():
        sent_to += _send_group(esn, group, actor, threshold, manual, today)
    return list(dict.fromkeys(sent_to))


def _send_group(esn, solutions, actor, threshold, manual, today):
    solutions = list(solutions)
    recipients = esn_recipients(esn)
    if not solutions or not recipients:
        return []
    recipients = list(dict.fromkeys(recipients + end_client_recipients(solutions[0].contract)
                                    + manager_recipients()))
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
        threshold = threshold_for(sol.license_end, today)
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
