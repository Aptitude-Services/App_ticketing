import datetime

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone

from django.utils.translation import gettext as _

from accounts.permissions import visible_contracts
from contracts.models import Contract, Solution
from contracts.status import with_coverage
from tickets import services as S
from tickets.models import OPEN_STATUSES, Event, Status
from tickets.views import _event_text, annotate_sla, urgency_order


def _series(qs, field, days, now):
    """Nombre d'objets par jour sur `days` jours, du plus ancien au plus récent."""
    start = (timezone.localtime(now) - datetime.timedelta(days=days - 1)).date()
    counts = {d: 0 for d in (start + datetime.timedelta(days=i) for i in range(days))}
    for dt in qs.filter(**{f"{field}__date__gte": start}).values_list(field, flat=True):
        day = timezone.localtime(dt).date()
        if day in counts:
            counts[day] += 1
    return list(counts.keys()), list(counts.values())


def _path(values, w, h, top=None):
    top = top or max(values + [1])
    step = w / max(len(values) - 1, 1)
    pts = [(round(i * step, 1), round(h - (v / top) * (h - 4), 1)) for i, v in enumerate(values)]
    line = "M" + "L".join(f"{x} {y}" for x, y in pts)
    return line, f"{line}L{w} {h}L0 {h}Z"


def _compliance(qs):
    total = qs.count()
    ok = qs.filter(response_breached=False, resolution_breached=False).count()
    return {"ok": ok, "total": total, "pct": round(ok * 100 / total) if total else None}


@login_required
def dashboard(request):
    user = request.user
    now = timezone.now()
    tickets = S.visible_tickets(user)
    open_qs = tickets.filter(status__in=OPEN_STATUSES)
    open_rows = annotate_sla(urgency_order(open_qs)[:500], now)
    states = [t.sla["state"] for t in open_rows]
    month_ago = now - datetime.timedelta(days=30)
    resolved_30 = tickets.filter(resolved_at__gte=month_ago)
    ctx = {
        "now": now,
        "n_open": len(open_rows),
        "n_unassigned": sum(1 for t in open_rows if t.assignee_id is None),
        "n_risk": states.count("risk"),
        "n_late": states.count("late"),
        "compliance": _compliance(resolved_30),
        "urgent": [t for t in open_rows if t.sla["state"] in ("late", "risk", "ok")][:8],
    }

    if user.is_aptitude:
        days, created = _series(tickets, "created_at", 30, now)
        _d, resolved = _series(tickets, "resolved_at", 30, now)
        top = max(created + resolved + [1])
        ctx["chart"] = {
            "open_line": _path(created, 600, 170, top)[0], "open_area": _path(created, 600, 170, top)[1],
            "done_line": _path(resolved, 600, 170, top)[0],
            "ticks": [days[i] for i in (0, 7, 14, 21, 29)],
            "n_created": sum(created), "n_resolved": sum(resolved),
        }
        durations = [(t.resolved_at - t.created_at).total_seconds() for t in resolved_30.select_related(None).only("resolved_at", "created_at")]
        if durations:
            avg = int(sum(durations) / len(durations) // 60)
            ctx["chart"]["avg_resolution"] = f"{avg // 60} h {avg % 60:02d}" if avg >= 60 else f"{avg} min"
        _d, spark_open = _series(tickets, "created_at", 14, now)
        ctx["spark_open"] = _path(spark_open, 200, 34)
        ctx["health"] = [
            {"name": "Contrats 24x7", "c": _compliance(resolved_30.filter(contract__contract_type__sla__coverage="24x7"))},
            {"name": "Contrats 8x5", "c": _compliance(resolved_30.filter(contract__contract_type__sla__coverage="8x5"))},
        ]
        ctx["n_out_of_coverage"] = tickets.filter(out_of_coverage=True, created_at__gte=month_ago).count()
        by_client = (open_qs.values("contract__client__name").annotate(n=Count("id")).order_by("-n")[:6])
        top_c = max([r["n"] for r in by_client] + [1])
        ctx["by_client"] = [{"name": r["contract__client__name"], "n": r["n"], "pct": round(r["n"] * 100 / top_c)} for r in by_client]
        by_sol = (Solution.objects.filter(tickets__in=tickets.filter(created_at__gte=month_ago))
                  .annotate(n=Count("tickets", distinct=True)).select_related("contract__client").order_by("-n")[:6])
        top_s = max([s.n for s in by_sol] + [1])
        ctx["by_solution"] = [{"s": s, "n": s.n, "pct": round(s.n * 100 / top_s)} for s in by_sol]
        ctx["team"] = (open_qs.exclude(assignee__isnull=True).values("assignee__first_name", "assignee__last_name")
                       .annotate(n=Count("id")).order_by("-n")[:6])
        events = (Event.objects.filter(ticket__in=tickets).select_related("actor", "ticket")
                  .exclude(kind=Event.Kind.SLA).order_by("-created_at")[:8])
        ctx["feed"] = [{"e": e, "text": _event_text(e) if e.kind != Event.Kind.COMMENT else
                        (_("a ajouté une note interne") if e.is_internal else _("a répondu"))} for e in events]
        return render(request, "core/dashboard_console.html", ctx)

    # Portail client
    ctx["waiting_me"] = [t for t in open_rows if t.status == Status.WAITING_CLIENT]
    ctx["my_open"] = open_rows[:10]
    start_month = timezone.localtime(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_resolved = tickets.filter(resolved_at__gte=start_month)
    ctx["month"] = _compliance(month_resolved)
    ctx["recent_resolved"] = tickets.filter(status__in=[Status.RESOLVED, Status.CLOSED]).order_by("-resolved_at")[:4]
    contracts = visible_contracts(user).filter(status=Contract.Status.ACTIVE).annotate(
        n_solutions=Count("solutions", filter=Q(solutions__is_active=True), distinct=True)).order_by("reference")
    ctx["contracts"] = with_coverage(contracts)
    ctx["can_create"] = S.can_write(user)
    return render(request, "core/dashboard_portal.html", ctx)
