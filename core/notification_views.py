"""Cloche de notifications : liste, ouverture (marque lue puis redirige), tout marquer lu, compteur."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from .models import Notification

PANEL_SIZE = 8


def panel_context(user):
    qs = Notification.objects.filter(recipient=user)
    return {"notif_unread": qs.filter(read_at__isnull=True).count(),
            "notif_items": list(qs.select_related("actor")[:PANEL_SIZE])}


@login_required
def notification_list(request):
    page = Paginator(Notification.objects.filter(recipient=request.user).select_related("actor"), 30)
    return render(request, "core/notifications.html", {"page": page.get_page(request.GET.get("page"))})


@login_required
@require_GET
def notification_open(request, pk):
    n = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if n.read_at is None:
        n.read_at = timezone.now()
        n.save(update_fields=["read_at"])
    url = n.url if url_has_allowed_host_and_scheme(n.url, allowed_hosts={request.get_host()}) else "/"
    return redirect(url)


@login_required
@require_POST
def notification_read_all(request):
    Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(read_at=timezone.now())
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({"unread": 0})
    nxt = request.POST.get("next") or "/"
    return redirect(nxt if url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}) else "/")


@login_required
@require_GET
def notification_panel(request):
    """Compteur et contenu de la liste déroulante, rafraîchis périodiquement par la page."""
    ctx = panel_context(request.user)
    html = render_to_string("_notif_items.html", ctx, request=request)
    return JsonResponse({"unread": ctx["notif_unread"], "html": html})
