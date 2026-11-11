"""Règles des rapports : qui voit, qui rédige, qui valide, envoi au client.

Circuit : Brouillon → (soumission) À valider → (supérieur) Validé → (envoi) Envoyé au client.
Le supérieur peut renvoyer le rapport « À corriger » avec un motif. Le rédacteur ne
valide jamais son propre rapport : seul son supérieur hiérarchique (champ « supérieur »
de sa fiche) ou, à défaut, un Manager / Super Admin d'Aptitude peut le faire.
Un rapport n'est visible du client qu'une fois envoyé.
"""
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from accounts.models import Profile, User
from accounts.permissions import visible_contracts
from contracts.notifications import esn_recipients
from core.notify import notify

from . import builders as B
from .models import Report

VALIDATOR_PROFILES = {Profile.APTITUDE_ADMIN, Profile.APTITUDE_MANAGER}


# --- Visibilité et droits ---------------------------------------------------------------------------

def visible_reports(user):
    qs = Report.objects.select_related("contract__client", "end_client", "author", "validator", "ticket")
    contracts = visible_contracts(user)
    qs = qs.filter(contract__in=contracts)
    if user.is_aptitude:
        return qs
    qs = qs.filter(status=Report.Status.SENT)
    org = user.organisation
    if org.is_end_client:
        qs = qs.filter(Q(end_client=org) | Q(end_client__isnull=True))
    return qs


def can_author(user):
    return user.is_authenticated and user.is_aptitude


def can_edit(user, report):
    return report.is_editable and user.is_aptitude and (
        report.author_id == user.pk or user.profile in VALIDATOR_PROFILES)


def can_validate(user, report):
    """Le supérieur du rédacteur ; à défaut de supérieur désigné, un Manager ou Super Admin.
    Jamais le rédacteur lui-même."""
    if report.status != Report.Status.SUBMITTED or user.pk == report.author_id:
        return False
    if user.profile not in VALIDATOR_PROFILES:
        return False
    manager_id = report.author.manager_id
    return manager_id is None or manager_id == user.pk or user.profile == Profile.APTITUDE_ADMIN


def can_send(user, report):
    return report.status == Report.Status.VALIDATED and user.is_aptitude


def can_client_confirm(user, report):
    return (report.status == Report.Status.SENT and user.is_client and user.can_write_tickets
            and not report.client_validated_at)


def validators_for(report):
    if report.author.manager_id and report.author.manager.is_active:
        return [report.author.manager]
    return list(User.objects.filter(profile__in=VALIDATOR_PROFILES, is_active=True).exclude(pk=report.author_id))


def _require(condition, message):
    if not condition:
        raise PermissionDenied(message)


def _mail(subject, body, recipients):
    """Envoie un email sans jamais bloquer le circuit du rapport.

    Une messagerie mal configurée ou injoignable ne doit pas empêcher de soumettre,
    valider ou publier un rapport : l'échec est inscrit au journal des emails
    (Configuration > Messagerie) et signalé à l'utilisateur. Renvoie True si l'email est parti."""
    if not recipients:
        return False
    try:
        return send_mail(subject, body, None, recipients, fail_silently=True) > 0
    except Exception:  # filet de sécurité : aucune erreur d'envoi ne remonte à l'écran
        import logging
        logging.getLogger(__name__).exception("Envoi d'email impossible")
        return False


def _notify(users, report, actor, title, body=""):
    """Notification interne (cloche) liée au rapport ; `title` est évalué dans la langue du destinataire."""
    return notify(users, "report", title, reverse("report_detail", args=[report.pk]), actor=actor, body=body)


def _client_users(report):
    """Mêmes destinataires que l'email d'envoi : admins de l'ESN (à défaut tous ses comptes actifs),
    plus les admins du client final."""
    esn_users = list(User.objects.filter(organisation=report.esn, is_active=True))
    users = [u for u in esn_users if u.profile == Profile.CLIENT_ADMIN] or esn_users
    if report.end_client_id:
        users += list(report.end_client.users.filter(is_active=True, profile=Profile.CLIENT_ADMIN))
    return users


def _absolute(path):
    return f"{settings.SITE_URL.rstrip('/')}{path}" if settings.SITE_URL else path


# --- Création et données extraites ---------------------------------------------------------------------

def create_report(author, kind, contract, end_client=None, ticket=None, year=None, quarter=None):
    _require(can_author(author), _("Seule l'équipe Aptitude rédige les rapports."))
    report = Report(kind=kind, contract=contract, end_client=end_client, ticket=ticket, author=author)
    data = {}
    if kind == Report.Kind.CURATIVE:
        data["title"] = ticket.title
        data["symptoms"] = ticket.description
        data["timeline"] = B.ticket_timeline(ticket)
        data["incident_start"] = B._iso(ticket.created_at)
        report.title = ticket.title
    elif kind == Report.Kind.PREVENTIVE:
        data["equipments"] = B.contract_equipments(contract)
        data["controls"] = B.default_controls()
        data["technician"] = author.display_name
        data["mode"] = "Sur site"
        report.title = _("Maintenance préventive")
    else:
        start, end = B.quarter_bounds(year, quarter)
        report.period_start, report.period_end = start, end
        # Le reste du contenu est déduit des rapports d'intervention validés (B.quarterly_content).
        data["availability_target"] = "99,9"
        data["resolution_target"] = "95"
        report.title = _("Rapport trimestriel %(q)s") % {"q": f"T{quarter} {year}"}
    report.data = data
    report.save()
    return report


def auto_data(report):
    """Données extraites de l'application : figées après validation, calculées en direct avant."""
    snapshot = report.data.get("snapshot")
    if snapshot:
        return snapshot
    if report.kind == Report.Kind.QUARTERLY:
        info = B.quarterly_info(report.contract, report.end_client, report.period_start, report.period_end)
    else:
        info = B.contract_info(report.contract, report.end_client)
    # Fonction des intervenants reprise de leur fiche : rien à saisir dans le rapport.
    info["author_title"] = report.author.title_label
    technician = report.author
    if report.ticket_id:
        info["ticket"] = B.ticket_info(report.ticket)
        technician = report.ticket.assignee or report.author
    info["technician_title"] = technician.title_label
    return info


# --- Circuit de validation ---------------------------------------------------------------------------

def submit(user, report):
    _require(can_edit(user, report), _("Ce rapport ne peut pas être soumis."))
    report.status = Report.Status.SUBMITTED
    report.submitted_at = timezone.now()
    report.rejection_comment = ""
    report.save()
    validators = validators_for(report)
    url = _absolute(reverse("report_detail", args=[report.pk]))
    mailed = _mail(
        _("[Aptitude] Rapport à valider : %(ref)s") % {"ref": report.reference},
        _("%(who)s a soumis le rapport %(ref)s (%(kind)s, %(esn)s) à votre validation.\n\n%(url)s")
        % {"who": report.author.display_name, "ref": report.reference, "kind": report.get_kind_display(),
           "esn": report.esn.name, "url": url},
        [u.email for u in validators])
    _notify(validators, report, user, lambda: _("Rapport à valider : %(ref)s") % {"ref": report.reference},
            lambda: _("%(who)s a soumis le rapport à votre validation.") % {"who": report.author.display_name})
    return validators, mailed


def validate(user, report):
    _require(can_validate(user, report), _("Vous ne pouvez pas valider ce rapport."))
    data = dict(report.data)
    data["snapshot"] = auto_data(report)
    if report.kind == Report.Kind.QUARTERLY:
        # Contenu figé avec le rapport : rubriques déduites, sauf celles saisies par le rédacteur.
        data = B.merged_quarterly(data, data["snapshot"])
    report.data = data
    report.status = Report.Status.VALIDATED
    report.validator = user
    report.validated_at = timezone.now()
    report.fingerprint = report.compute_fingerprint()
    report.save()
    _notify([report.author], report, user, lambda: _("Rapport validé : %(ref)s") % {"ref": report.reference},
            lambda: _("%(who)s a validé votre rapport.") % {"who": user.display_name})


def reject(user, report, comment):
    _require(report.status == Report.Status.SUBMITTED and user.profile in VALIDATOR_PROFILES
             and user.pk != report.author_id, _("Vous ne pouvez pas renvoyer ce rapport."))
    report.status = Report.Status.REJECTED
    report.rejection_comment = comment
    report.save()
    _notify([report.author], report, user, lambda: _("Rapport à corriger : %(ref)s") % {"ref": report.reference},
            comment)
    return _mail(
        _("[Aptitude] Rapport à corriger : %(ref)s") % {"ref": report.reference},
        _("%(who)s demande des corrections sur le rapport %(ref)s :\n\n%(c)s\n\n%(url)s")
        % {"who": user.display_name, "ref": report.reference, "c": comment,
           "url": _absolute(reverse("report_detail", args=[report.pk]))},
        [report.author.email] if report.author.email else [])


def send_to_client(user, report):
    """Envoi au client ESN (et au client final s'il a des comptes) : uniquement un rapport validé."""
    _require(can_send(user, report), _("Seul un rapport validé peut partir chez le client."))
    recipients = list(esn_recipients(report.esn))
    if report.end_client_id:
        recipients += [u.email for u in report.end_client.users.filter(is_active=True,
                                                                      profile=Profile.CLIENT_ADMIN)]
    recipients = sorted(set(recipients))
    if not recipients:
        raise ValidationError(_("Aucun destinataire actif chez %(esn)s : créez d'abord un compte client.")
                              % {"esn": report.esn.name})
    url = _absolute(reverse("report_detail", args=[report.pk]))
    target = report.end_client.name if report.end_client_id else report.esn.name
    mailed = _mail(
        _("Rapport %(kind)s %(ref)s — %(target)s") % {"kind": report.get_kind_display().lower(),
                                                      "ref": report.reference, "target": target},
        _("Bonjour,\n\nLe rapport %(ref)s (%(kind)s) est disponible sur votre portail de support :\n%(url)s\n\n"
          "Vous pouvez le consulter, l'imprimer ou l'enregistrer en PDF, et confirmer sa réception.\n")
        % {"ref": report.reference, "kind": report.get_kind_display(), "url": url},
        recipients)
    # Même sans email, le rapport est publié : le client le retrouve sur son portail.
    report.status = Report.Status.SENT
    report.sent_at = timezone.now()
    report.sent_to = ", ".join(recipients)
    report.save()
    _notify(_client_users(report), report, user,
            lambda: _("Nouveau rapport disponible : %(ref)s") % {"ref": report.reference},
            lambda: _("%(kind)s — à consulter et à confirmer.") % {"kind": report.get_kind_display()})
    return recipients, mailed


def client_confirm(user, report):
    _require(can_client_confirm(user, report), _("Confirmation impossible."))
    report.client_validated_by = user
    report.client_validated_at = timezone.now()
    report.save(update_fields=["client_validated_by", "client_validated_at", "updated_at"])
    _notify([report.author, report.validator], report, user,
            lambda: _("Réception confirmée : %(ref)s") % {"ref": report.reference},
            lambda: _("%(who)s (%(org)s) a confirmé la réception du rapport.")
            % {"who": user.display_name, "org": user.organisation})
