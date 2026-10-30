"""Configuration > Messagerie : mode d'envoi, test, journal. Réservé aux admins Aptitude."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from accounts.audit import record
from accounts.models import AuditEvent, Profile

from .forms import MailSettingsForm, MailTestForm
from .mail import env_backend_path
from .models import MailSettings, OutgoingMail


def _require_admin(request):
    if request.user.profile != Profile.APTITUDE_ADMIN:
        raise Http404


@login_required
@require_http_methods(["GET", "POST"])
def mail_settings(request):
    _require_admin(request)
    config = MailSettings.load()
    form = MailSettingsForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        config = form.save(commit=False)
        config.updated_by = request.user
        config.save()
        # Jamais de secret dans l'audit : seulement les champs modifiés.
        record(request, AuditEvent.Action.MAIL_SETTINGS_UPDATED,
               details={"provider": config.provider, "changed": sorted(form.changed_data)})
        messages.success(request, _("Configuration de la messagerie enregistrée."))
        return redirect("mail_settings")
    return render(request, "core/mail_settings.html", {
        "form": form, "config": config, "test_form": MailTestForm(initial={"to": request.user.email}),
        "env_backend": env_backend_path(), "journal": OutgoingMail.objects.all()[:50],
    })


@login_required
@require_POST
def mail_test(request):
    _require_admin(request)
    form = MailTestForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Adresse de test invalide."))
        return redirect("mail_settings")
    config = MailSettings.load()
    try:
        sent = send_mail(
            _("Aptitude Support : email de test"),
            _("Cet email confirme que l'envoi fonctionne (mode : %(mode)s).") % {"mode": config.get_provider_display()},
            None, [form.cleaned_data["to"]],
        )
    except Exception as exc:
        messages.error(request, _("Échec de l'envoi : %(err)s") % {"err": f"{type(exc).__name__} : {exc}"[:400]})
    else:
        if sent:
            messages.success(request, _("Email de test envoyé à %(to)s.") % {"to": form.cleaned_data["to"]})
        else:
            messages.warning(request, _("Messagerie désactivée : l'email a seulement été inscrit au journal."))
    return redirect("mail_settings")
