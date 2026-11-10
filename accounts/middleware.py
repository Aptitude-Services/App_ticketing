from django.shortcuts import redirect
from django.urls import reverse
from django.utils import translation
from django_otp.plugins.otp_totp.models import TOTPDevice

EXEMPT_PREFIXES = ("/static/", "/favicon.ico", "/manifest.webmanifest", "/sw.js", "/hors-ligne/")
EXEMPT_URL_NAMES = ("login", "logout", "mfa_setup", "mfa_verify", "password_reset", "password_reset_done",
                    "password_reset_confirm", "password_reset_complete", "set_language")


class UserLanguageMiddleware:
    """Applique la langue choisie dans le profil de l'utilisateur connecté."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.language:
            translation.activate(user.language)
            request.LANGUAGE_CODE = user.language
        return self.get_response(request)


class MFARequiredMiddleware:
    """Exige une session validée par TOTP pour tout compte Aptitude,
    et pour tout compte client qui a activé la MFA."""

    def __init__(self, get_response):
        self.get_response = get_response
        self._exempt_paths = None

    def _exempt(self, path):
        if path.startswith(EXEMPT_PREFIXES):
            return True
        if self._exempt_paths is None:
            paths = []
            for name in EXEMPT_URL_NAMES:
                try:
                    paths.append(reverse(name))
                except Exception:
                    pass
            # Les liens de réinitialisation contiennent des jetons : on exempte leur préfixe
            # (/compte/mot-de-passe/definir/), et lui seul. Surtout pas tout /compte/mot-de-passe/ :
            # le changement de mot de passe (…/changer/) doit rester derrière la double authentification.
            confirm = reverse("password_reset_confirm", kwargs={"uidb64": "u", "token": "t"})
            paths.append(confirm[: -len("u/t/")])
            self._exempt_paths = tuple(paths)
        return path.startswith(self._exempt_paths)

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not self._exempt(request.path):
            if not user.is_verified():
                has_device = TOTPDevice.objects.filter(user=user, confirmed=True).exists()
                if has_device:
                    return redirect(f"{reverse('mfa_verify')}?next={request.get_full_path()}")
                if user.mfa_required:
                    return redirect("mfa_setup")
        return self.get_response(request)
