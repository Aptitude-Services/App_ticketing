from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .models import AuditEvent, User


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def record(request, action, target_user=None, details=None, actor=None):
    actor = actor or (request.user if request is not None and request.user.is_authenticated else None)
    org = (target_user or actor).organisation if (target_user or actor) else None
    return AuditEvent.objects.create(
        actor=actor, action=action, target_user=target_user, organisation=org,
        ip_address=client_ip(request), details=details or {},
    )


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    record(request, AuditEvent.Action.LOGIN, target_user=user, actor=user)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        record(request, AuditEvent.Action.LOGOUT, target_user=user, actor=user)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    email = (credentials or {}).get("username", "")
    target = User.objects.filter(email__iexact=email).first()
    AuditEvent.objects.create(
        action=AuditEvent.Action.LOGIN_FAILED, target_user=target,
        organisation=target.organisation if target else None,
        ip_address=client_ip(request), details={"email": email[:254]},
    )
