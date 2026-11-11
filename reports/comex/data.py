"""Données du COMEX : un client final d'une ESN, sur une période libre.

Deux sources :
- calculées : tickets, engagements de délai, équipements, rapports préventifs et curatifs
  validés de la période, sur tous les contrats de l'ESN qui couvrent ce client final ;
- saisies : les rapports trimestriels validés (ou envoyés) dont la période recoupe celle du
  COMEX — appréciation, disponibilité, faits marquants, recommandations, plan d'action,
  décisions. Les valeurs simples viennent du plus récent ; les listes sont cumulées.

Quand une rubrique saisie manque, une valeur calculée la remplace si c'est possible ;
sinon la diapositive correspondante est omise.
"""
import datetime
from collections import Counter

from django.db.models import Q
from django.utils import timezone

from sla.models import PRIORITY_NAMES, Priority

from .. import builders as B

MONTHS_SHORT = ["Janv.", "Févr.", "Mars", "Avr.", "Mai", "Juin", "Juil.", "Août", "Sept.", "Oct.", "Nov.", "Déc."]
MAX_MONTHS_CHART = 12


def contracts_for(esn, end_client):
    from contracts.models import Contract

    return (Contract.objects.filter(client=esn, end_clients=end_client)
            .select_related("client", "contract_type__sla").distinct().order_by("start_date", "pk"))


def _num(text):
    """« 99,92 » → 99.92 ; None si illisible."""
    try:
        return float(str(text).replace("%", "").replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def fmt_pct(value, digits=1):
    if value is None:
        return "—"
    text = f"{value:.{digits}f}".replace(".", ",")
    return f"{text} %"


def quarter_of(start, end):
    """(trimestre, année) si la période est exactement un trimestre civil, sinon None."""
    if start.day != 1 or start.month not in (1, 4, 7, 10):
        return None
    q = (start.month - 1) // 3 + 1
    return (q, start.year) if B.quarter_bounds(start.year, q) == (start, end) else None


def month_starts(start, end):
    m = start.replace(day=1)
    out = []
    while m <= end:
        out.append(m)
        m = datetime.date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    return out


def _quarterly_reports(contracts, end_client, start, end):
    from ..models import Report

    qs = (Report.objects.filter(contract__in=contracts, kind=Report.Kind.QUARTERLY,
                                status__in=[Report.Status.VALIDATED, Report.Status.SENT],
                                period_start__lte=end, period_end__gte=start)
          .filter(Q(end_client=end_client) | Q(end_client__isnull=True)))
    return sorted(qs, key=lambda r: (r.period_end or datetime.date.min, r.pk), reverse=True)


def _rows(reports, key, ncols=1):
    """Lignes d'une rubrique « lignes », cumulées sur les rapports, sans doublon."""
    seen, out = set(), []
    for r in reports:
        for row in r.data.get(key) or []:
            row = (list(row) + [""] * ncols)[:ncols]
            if not row[0].strip() or tuple(row) in seen:
                continue
            seen.add(tuple(row))
            out.append(row)
    return out


def _first(reports, key):
    for r in reports:
        value = r.data.get(key)
        if value not in (None, ""):
            return value
    return ""


def comex_data(esn, end_client, start, end, now=None):
    from tickets.models import OPEN_STATUSES, Status, Ticket

    from ..models import Report

    now = now or timezone.now()
    contracts = list(contracts_for(esn, end_client))
    all_tickets = list(Ticket.objects.filter(contract__in=contracts, created_at__date__gte=start,
                                             created_at__date__lte=end)
                       .select_related("contract", "requester__organisation").prefetch_related("solutions").order_by("created_at"))
    # Un ticket n'est rattaché qu'à son contrat. Sur un contrat partagé entre plusieurs clients finaux,
    # seuls comptent les tickets ouverts par un utilisateur de ce client final ; ceux ouverts par l'ESN
    # ou par Aptitude ne peuvent être attribués à aucun client et sont écartés (comptés à part).
    shared = {c.pk for c in contracts if c.end_clients.count() > 1}
    tickets = [t for t in all_tickets
               if t.contract_id not in shared or t.requester.organisation_id == end_client.pk]
    excluded_shared = len([t for t in all_tickets if t.contract_id in shared
                           and not t.requester.organisation.is_end_client])
    resolved_statuses = {Status.RESOLVED, Status.CLOSED}
    resolved = [t for t in tickets if t.status in resolved_statuses]
    open_ = [t for t in tickets if t.status in OPEN_STATUSES]

    # --- Tickets par mois (au-delà de 12 mois : les 12 derniers)
    months = []
    for m in month_starts(start, end)[-MAX_MONTHS_CHART:]:
        in_m = [t for t in tickets
                if (timezone.localtime(t.created_at).year, timezone.localtime(t.created_at).month) == (m.year, m.month)]
        label = MONTHS_SHORT[m.month - 1] if start.year == end.year else f"{MONTHS_SHORT[m.month - 1]} {m:%y}"
        months.append({"label": label, "opened": len(in_m),
                       "resolved": len([t for t in in_m if t.status in resolved_statuses])})

    statuses = [
        ("Résolus", len(resolved)),
        ("En cours", len([t for t in tickets if t.status in {Status.NEW, Status.ACKNOWLEDGED,
                                                              Status.IN_PROGRESS}])),
        ("Attente client", len([t for t in tickets if t.status == Status.WAITING_CLIENT])),
        ("Attente prérequis", len([t for t in tickets if t.status == Status.WAITING_PREREQ])),
    ]
    priorities = [{"code": f"P{p}", "name": str(PRIORITY_NAMES.get(p, "")),
                   "opened": len([t for t in tickets if t.priority == p]),
                   "resolved": len([t for t in resolved if t.priority == p])} for p in Priority.values]

    acknowledged = [t for t in tickets if t.acknowledged_at]
    response_pct = B._pct(len([t for t in acknowledged if not t.response_breached]), len(acknowledged))
    resolution_pct = B._pct(len([t for t in resolved if not t.resolution_breached]), len(resolved))
    breached = [t for t in resolved if t.resolution_breached] + [
        t for t in open_ if t.resolution_due and t.resolution_due < now]

    equipment = Counter(s.name for t in tickets for s in t.solutions.all()).most_common(6)

    # --- Rapports préventifs et curatifs validés de la période
    preventives, curatives = [], []
    for c in contracts:
        preventives += B.period_reports(c, end_client, start, end, Report.Kind.PREVENTIVE)
        curatives += B.period_reports(c, end_client, start, end, Report.Kind.CURATIVE)
    controls = Counter()
    health = []
    for r in preventives:
        counts = B.control_counts(r.data.get("controls"))
        for k in ("total", "ok", "watch", "ko", "na"):
            controls[k] += counts[k]
        health.append({"site": B.report_site(r) or r.reference, "states": B._health(r.data.get("controls"))})
    causes = Counter((r.data.get("diagnosis_category") or "").strip() or "Cause non déterminée"
                     for r in curatives).most_common(6)

    # --- Saisies des rapports trimestriels
    quarterlies = _quarterly_reports(contracts, end_client, start, end)
    availability = _num(_first(quarterlies, "availability"))
    availability_target = _num(_first(quarterlies, "availability_target")) or 99.9
    resolution_target = _num(_first(quarterlies, "resolution_target")) or 95.0
    response_target = resolution_target
    visits_planned = sum(int(_num(r.data.get("visits_planned")) or 0) for r in quarterlies) or None
    availability_months = [(row[0], _num(row[1])) for row in _rows(quarterlies, "availability_months", 2)
                           if _num(row[1]) is not None]

    highlights = [r[0] for r in _rows(quarterlies, "highlights")]
    attention = [r[0] for r in _rows(quarterlies, "attention")]
    if not highlights:
        highlights = [f"{len(resolved)} tickets résolus sur {len(tickets)} ouverts sur la période."]
        if response_pct is not None:
            highlights.append(f"Prise en charge dans les délais : {fmt_pct(response_pct)}.")
        if preventives:
            highlights.append(f"{len(preventives)} visite(s) préventive(s) réalisée(s), "
                              f"{controls['total']} contrôles effectués.")
    if not attention:
        if resolution_pct is not None and resolution_pct < resolution_target:
            attention.append(f"Résolution dans les délais à {fmt_pct(resolution_pct)} "
                             f"pour un objectif de {fmt_pct(resolution_target)}.")
        if open_:
            attention.append(f"{len(open_)} ticket(s) encore ouvert(s) en fin de période.")
        if controls["watch"] + controls["ko"]:
            attention.append(f"{controls['watch'] + controls['ko']} anomalie(s) relevée(s) "
                             "lors des visites préventives.")

    overruns = [r[0] for r in _rows(quarterlies, "overruns")] or [
        f"P{t.priority} · {t.reference} : {t.title[:60]} — résolution hors délai." for t in breached[:4]]
    recurring = [{"name": r[0], "count": r[1], "action": r[2]} for r in _rows(quarterlies, "recurring", 3)]

    headline = _first(quarterlies, "headline")
    if not headline:
        if not tickets:
            headline = "Aucun incident sur la période"
        elif resolution_pct is None or resolution_pct >= resolution_target:
            headline = "Engagements de service tenus sur la période"
        else:
            headline = "Engagements globalement tenus, délai de résolution à surveiller"

    action_plan = [dict(zip(("action", "priority", "owner", "due", "status"), r))
                   for r in _rows(quarterlies, "action_plan", 5)]
    if not action_plan:
        for r in preventives:
            for row in r.data.get("recommendations") or []:
                row = (list(row) + [""] * 4)[:4]
                if row[0].strip():
                    action_plan.append({"action": row[0], "priority": row[1], "owner": row[2], "due": row[3],
                                        "status": "À planifier"})
        for r in curatives:
            for row in r.data.get("followups") or []:
                row = (list(row) + [""] * 3)[:3]
                if row[0].strip():
                    action_plan.append({"action": row[0], "priority": "", "owner": row[1], "due": row[2],
                                        "status": "En cours"})

    decisions = [{"title": r[0], "detail": r[1]} for r in _rows(quarterlies, "decisions", 2)]

    return {
        "esn": esn.name, "esn_logo": esn.logo_data_uri() if hasattr(esn, "logo_data_uri") else "",
        "end_client": end_client.name,
        "contracts": [c.reference for c in contracts],
        "start": start, "end": end, "quarter": quarter_of(start, end),
        "headline": headline,
        "tickets_total": len(tickets), "tickets_resolved": len(resolved), "tickets_open": len(open_),
        "months": months, "statuses": statuses, "priorities": priorities,
        "response_pct": response_pct, "resolution_pct": resolution_pct,
        "response_target": response_target, "resolution_target": resolution_target,
        "availability": availability, "availability_target": availability_target,
        "availability_months": availability_months,
        "overruns": overruns,
        "equipment": equipment, "causes": causes, "recurring": recurring,
        "visits_done": len(preventives), "visits_planned": visits_planned,
        "visits_note": _first(quarterlies, "visits_note"),
        "controls": dict(controls), "health": health,
        "health_columns": list(B.HEALTH_CATEGORIES.values()),
        "highlights": highlights, "attention": attention,
        "done_kpis": [{"value": r[0], "label": r[1]} for r in _rows(quarterlies, "done_kpis", 2)],
        "done_actions": [r[0] for r in _rows(quarterlies, "done_actions")],
        "recommendations": [dict(zip(("title", "why", "impact", "effort"), r))
                            for r in _rows(quarterlies, "recommendations", 4)],
        "action_plan": action_plan,
        "decisions": decisions,
        "next_point": _first(quarterlies, "next_point"),
        "quarterly_reports": [r.reference for r in quarterlies],
        "excluded_shared": excluded_shared,
    }
