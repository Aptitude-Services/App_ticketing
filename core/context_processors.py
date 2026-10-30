def navigation(request):
    """Compteurs de la navigation (tickets ouverts visibles)."""
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return {}
    from tickets.models import OPEN_STATUSES, Status
    from tickets.services import visible_tickets
    qs = visible_tickets(user)
    return {
        "nav_open_tickets": qs.filter(status__in=OPEN_STATUSES).count(),
        "nav_waiting_me": qs.filter(status=Status.WAITING_CLIENT).count() if user.is_client else 0,
    }
