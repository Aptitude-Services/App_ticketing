import base64
from io import BytesIO

import qrcode
import qrcode.image.svg
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.http import Http404
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from . import permissions
from .audit import record
from .forms import ProfileForm, TokenForm, UserManageForm
from .models import AuditEvent, User


def _require_user_manager(request):
    if not request.user.can_manage_users:
        raise Http404


@login_required
def user_list(request):
    _require_user_manager(request)
    users = permissions.manageable_users(request.user).prefetch_related("contract_accesses__contract")
    return render(request, "accounts/user_list.html", {"users": users})


@login_required
@require_http_methods(["GET", "POST"])
def user_create(request):
    _require_user_manager(request)
    form = UserManageForm(request.POST or None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        _send_invitation(request, user)
        record(request, AuditEvent.Action.USER_CREATED, target_user=user,
               details={"profile": user.profile, "organisation": user.organisation.name})
        messages.success(request, _("Utilisateur créé. Un email d'invitation lui a été envoyé."))
        return redirect("user_list")
    return render(request, "accounts/user_form.html", {"form": form, "creating": True})


@login_required
@require_http_methods(["GET", "POST"])
def user_update(request, pk):
    _require_user_manager(request)
    # Hors du périmètre de l'acteur : 404, sans révéler que l'utilisateur existe.
    target = get_object_or_404(permissions.manageable_users(request.user), pk=pk)
    before = {"profile": target.profile, "is_active": target.is_active, "all_contracts": target.all_contracts}
    form = UserManageForm(request.POST or None, instance=target, actor=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        after = {"profile": user.profile, "is_active": user.is_active, "all_contracts": user.all_contracts}
        record(request, AuditEvent.Action.USER_UPDATED, target_user=user, details={"before": before, "after": after})
        messages.success(request, _("Utilisateur mis à jour."))
        return redirect("user_list")
    return render(request, "accounts/user_form.html", {"form": form, "creating": False, "target": target})


def _send_invitation(request, user):
    """Envoie un lien de définition du mot de passe.

    Le formulaire de réinitialisation de Django ignore les comptes sans mot de
    passe : on construit donc le lien nous-mêmes, avec le même générateur de jetons.
    """
    context = {
        "user": user,
        "domain": request.get_host(),
        "protocol": "https" if request.is_secure() else "http",
        "uid": urlsafe_base64_encode(force_bytes(user.pk)),
        "token": default_token_generator.make_token(user),
    }
    with translation.override(user.language):
        subject = "".join(render_to_string("registration/invitation_subject.txt", context).splitlines())
        body = render_to_string("registration/invitation_email.txt", context)
    send_mail(subject, body, None, [user.email])


@login_required
@require_http_methods(["GET", "POST"])
def my_profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Profil enregistré."))
        return redirect("my_profile")
    has_mfa = TOTPDevice.objects.filter(user=request.user, confirmed=True).exists()
    return render(request, "accounts/profile.html", {"form": form, "has_mfa": has_mfa})


# --- MFA -----------------------------------------------------------------------

def _qr_svg(uri):
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    buf = BytesIO()
    img.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


@login_required
@require_http_methods(["GET", "POST"])
def mfa_setup(request):
    if TOTPDevice.objects.filter(user=request.user, confirmed=True).exists():
        return redirect("mfa_verify")
    device, _created = TOTPDevice.objects.get_or_create(
        user=request.user, confirmed=False, defaults={"name": "Application d'authentification"}
    )
    form = TokenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if device.verify_token(form.cleaned_data["token"]):
            device.confirmed = True
            device.save()
            otp_login(request, device)
            record(request, AuditEvent.Action.MFA_ENABLED, target_user=request.user)
            messages.success(request, _("Double authentification activée."))
            return redirect("dashboard")
        form.add_error("token", _("Code invalide. Vérifiez l'heure de votre téléphone et réessayez."))
    return render(request, "accounts/mfa_setup.html", {
        "form": form, "qr": _qr_svg(device.config_url), "secret": base64.b32encode(device.bin_key).decode(),
    })


@login_required
@require_http_methods(["GET", "POST"])
def mfa_verify(request):
    devices = list(TOTPDevice.objects.filter(user=request.user, confirmed=True))
    if not devices:
        return redirect("mfa_setup")
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = ""
    form = TokenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        for device in devices:
            if device.verify_token(form.cleaned_data["token"]):
                otp_login(request, device)
                return redirect(next_url or "dashboard")
        record(request, AuditEvent.Action.LOGIN_FAILED, target_user=request.user, details={"step": "mfa"})
        form.add_error("token", _("Code invalide."))
    return render(request, "accounts/mfa_verify.html", {"form": form, "next": next_url})


@login_required
@require_http_methods(["POST"])
def set_theme(request):
    """Enregistre le thème choisi (clair, sombre ou comme le système)."""
    from django.http import HttpResponse

    theme = request.POST.get("theme", "")
    if theme not in {"light", "dark", "system"}:
        theme = "dark" if request.user.theme != "dark" else "light"
    request.user.theme = theme
    request.user.save(update_fields=["theme"])
    if request.headers.get("X-Requested-With") == "fetch":
        return HttpResponse(status=204)
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = ""
    return redirect(next_url or "dashboard")
