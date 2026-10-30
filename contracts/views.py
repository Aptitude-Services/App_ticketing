from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from accounts.permissions import visible_contracts, visible_solutions
from sla.models import PRIORITY_DEFINITIONS, PRIORITY_NAMES, Holiday

from .models import Contract
from .status import coverage_status, with_coverage


@login_required
def contract_list(request):
    status = request.GET.get("statut", "active")
    qs = visible_contracts(request.user).annotate(
        n_solutions=Count("solutions", filter=Q(solutions__is_active=True), distinct=True))
    if status in Contract.Status.values:
        qs = qs.filter(status=status)
    else:
        status = "all"
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(reference__icontains=q) | Q(title__icontains=q) | Q(client__name__icontains=q))
    return render(request, "contracts/contract_list.html", {
        "contracts": with_coverage(qs.order_by("client__name", "reference")),
        "status": status, "q": q, "statuses": Contract.Status.choices,
    })


@login_required
def contract_detail(request, pk):
    # Hors périmètre : 404, sans révéler l'existence du contrat.
    contract = get_object_or_404(visible_contracts(request.user), pk=pk)
    sla = contract.sla
    targets = [{"target": t, "name": PRIORITY_NAMES.get(t.priority, ""), "definition": PRIORITY_DEFINITIONS.get(t.priority, "")}
               for t in (sla.targets.all() if sla else [])]
    now = timezone.now()
    return render(request, "contracts/contract_detail.html", {
        "contract": contract,
        "sla": sla,
        "targets": targets,
        "solutions": visible_solutions(request.user).filter(contract=contract),
        "coverage_now": coverage_status(contract, now),
        "upcoming_holidays": Holiday.objects.filter(date__gte=now.date())[:4] if sla and not sla.is_24x7 else [],
    })
