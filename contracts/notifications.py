"""Alertes d'expiration de licence.

Réglages (seuils, destinataires, plage d'envoi, activation) : fiche « Paramètres des alertes
de licence » de l'administration (modèle LicenseAlertSettings). Par défaut : trois alertes,
5 mois, 3 mois puis 1 mois avant l'échéance. Deux emails : un interne (ESN vendeur + managers,
offre de renouvellement à envoyer) et un pour le client final (expiration + offre à venir).
Deux déclencheurs :
- automatique : le planificateur intégré (service « scheduler », commande ``run_scheduler``)
  vérifie chaque heure dans la plage d'envoi (``notify_license_expiry`` reste disponible
  pour un lancement manuel) ;
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

from .models import Contract, LicenseAlertSettings, LicenseNotice, Solution


class LicenseMailError(Exception):
    """L'email d'alerte n'a pas pu partir (messagerie mal configurée ou injoignable)."""

    def __init__(self, recipients):
        super().__init__(", ".join(recipients))
        self.recipients = recipients


def esn_recipients(esn):
    """Administrateurs de l'ESN ; à défaut, tous ses utilisateurs actifs.

    Vente directe (vendeur = Aptitude) : personne ici, l'équipe interne n'est pas une ESN ;
    les managers Aptitude sont prévenus par leur propre réglage (notify_managers)."""
    if esn.is_operator:
        return []
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


def threshold_for(license_end, today, conf=None):
    """Plus proche seuil atteint, exprimé en jours (un mois compte pour 30) ; None avant le
    premier seuil ou après l'échéance. Seuils par défaut : 5, 3 et 1 mois → 150, 90 ou 30."""
    conf = conf or LicenseAlertSettings.get()
    if license_end < today:
        return None
    if conf.unit == LicenseAlertSettings.Unit.MONTHS:
        reached = [v for v in conf.threshold_values() if today >= months_before(license_end, v)]
    else:
        reached = [v for v in conf.threshold_values() if today >= license_end - datetime.timedelta(days=v)]
    return conf.threshold_days(min(reached)) if reached else None


def expiring_solutions(today=None, horizon=None):
    today = today or timezone.localdate()
    if horizon is None:
        horizon = LicenseAlertSettings.get().horizon_days()
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
    if days == 1:
        return _("demain")
    if days >= 28:
        months = round(days / 30.4)
        return _("dans environ %(m)d mois (%(d)d jours)") % {"m": months, "d": days}
    return _("dans %(d)d jours") % {"d": days}


def _end_names(solutions):
    return ", ".join(e.name for e in solutions[0].contract.end_clients.all()) or "—"


def _license_lines(sol, today, extra=()):
    """Bloc d'une licence : nom, échéance, contrat, (lignes internes), client final, lien."""
    contract = sol.contract
    return [
        sol.name,
        f"• {_('Fin de licence')} : {sol.license_end:%d/%m/%Y}, {_when((sol.license_end - today).days)}",
        f"• {_('Contrat')} : {contract.reference}",
        *extra,
        f"• {_('Client final')} : {_end_names([sol])}",
        f"• {_('Voir le contrat')} : {_contract_url(contract)}",
        "",
    ]


def _client_subject(solutions):
    if len(solutions) == 1:
        return _("Expiration prochaine de votre licence")
    return _("Expiration prochaine de vos licences")


def _client_body(solutions, today):
    """Mail au client final : information + annonce de l'offre de renouvellement."""
    intro = (_("La licence ci-dessous, couverte par votre contrat de support, arrive bientôt à expiration :")
             if len(solutions) == 1 else
             _("Les licences ci-dessous, couvertes par vos contrats de support, arrivent bientôt à expiration :"))
    lines = [_("Bonjour,"), "", intro, ""]
    for sol in solutions:
        lines += _license_lines(sol, today)
    lines += [
        _("Pour que votre service continue sans interruption, nous vous ferons parvenir une offre "
          "de renouvellement dans les plus brefs délais."),
        "",
        _("Cordialement,"),
        _("L'équipe Aptitude Support"),
    ]
    return "\n".join(lines)


def _internal_subject(solutions):
    soonest = min(s.license_end for s in solutions)
    return _("[Action requise] Offre de renouvellement à envoyer : %(c)s, échéance le %(d)s") % {
        "c": _end_names(solutions), "d": soonest.strftime("%d/%m/%Y")}


def _internal_body(esn, solutions, today, client_emails):
    """Mail au vendeur (ESN ou Propriétaire) et aux managers : l'offre promise au client reste à envoyer."""
    head = (_("La licence ci-dessous arrive à expiration.") if len(solutions) == 1 else
            _("Les licences ci-dessous arrivent à expiration."))
    if client_emails:
        tail = _("Le client final a été informé ce jour qu'une offre de renouvellement lui sera transmise "
                 "dans les plus brefs délais.")
    else:
        tail = _("Le client final n'a pas été prévenu par email (aucun destinataire).")
    lines = [_("Bonjour,"), "", f"{head} {tail}", ""]
    for sol in solutions:
        lines += _license_lines(sol, today, [f"• {_('Vendeur')} : {esn.name}"])
    if client_emails:
        # Même(s) client(s) final(aux) pour tout le groupe : une seule mention.
        lines += [f"{_('Client prévenu')} : {', '.join(client_emails)}", ""]
    lines += [
        _("Action attendue : préparer et envoyer l'offre de renouvellement au client final."),
        "",
        _("Cordialement,"),
        _("L'équipe Aptitude Support"),
    ]
    return "\n".join(lines)


def _send(subject, body, recipients):
    if not recipients:
        return
    try:
        sent = send_mail(subject, body, None, recipients, fail_silently=True)
    except Exception:
        sent = 0
    if not sent:
        # Échec d'envoi (inscrit au journal des emails) : rien n'est tracé, l'alerte sera retentée.
        raise LicenseMailError(recipients)


def send_license_notice(esn, solutions, actor=None, threshold=0, manual=False, today=None):
    """Envoie l'alerte puis la trace. Deux emails distincts :
    - interne, au vendeur (admins de l'ESN) et aux managers Aptitude : offre de renouvellement à envoyer ;
    - client, aux clients finaux concernés : expiration annoncée, offre à venir.

    Un envoi par groupe de clients finaux : un client final ne reçoit que ses licences.
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
    if not solutions:
        return []
    conf = LicenseAlertSettings.get()
    internal = []
    if conf.notify_esn:
        internal += esn_recipients(esn)
    if conf.notify_managers:
        internal += manager_recipients()
    internal = list(dict.fromkeys(internal))
    clients = list(dict.fromkeys(end_client_recipients(solutions[0].contract))) if conf.notify_end_client else []
    clients = [e for e in clients if e not in internal]
    recipients = internal + clients
    if not recipients:
        return []
    # L'équipe interne d'abord : le client ne reçoit la promesse d'une offre que si le vendeur est prévenu.
    _send(_internal_subject(solutions), _internal_body(esn, solutions, today, clients), internal)
    _send(_client_subject(solutions), _client_body(solutions, today), clients)
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
    conf = LicenseAlertSettings.get()
    if not conf.enabled:
        return 0, 0
    by_esn = defaultdict(list)
    for sol in expiring_solutions(today, conf.horizon_days()):
        threshold = threshold_for(sol.license_end, today, conf)
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
