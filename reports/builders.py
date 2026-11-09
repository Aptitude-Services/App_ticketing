"""Extraction automatique des données des rapports depuis les contrats, tickets et rapports.

Tout ce qui sort d'ici est sérialisable en JSON (dates en chaînes ISO, heure locale) :
à la validation, le résultat est figé tel quel dans ``report.data["snapshot"]``.
"""
import datetime
from collections import Counter, OrderedDict

from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from sla import engine
from sla.models import PRIORITY_NAMES, Priority

PROVIDER = "Aptitude"
RESULTS = ["Conforme", "À surveiller", "Non conforme", "N/A"]
MONTHS = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre",
          "Novembre", "Décembre"]


def _iso(dt):
    if not dt:
        return ""
    if isinstance(dt, datetime.datetime):
        return timezone.localtime(dt).strftime("%Y-%m-%dT%H:%M")
    return dt.isoformat()


def fmt_minutes(minutes):
    if minutes is None:
        return "—"
    minutes = max(0, int(minutes))
    h, m = divmod(minutes, 60)
    if h >= 48:
        d, h = divmod(h, 24)
        return f"{d} j {h} h" if h else f"{d} j"
    if h and m:
        return f"{h} h {m:02d}"
    return f"{h} h" if h else f"{m} min"


def _covered_minutes(sla, start, end):
    if not (start and end) or end <= start:
        return 0
    if sla and not sla.is_24x7:
        return engine.elapsed_minutes(sla, start, end)
    return int((end - start).total_seconds() // 60)


# --- Contrat ----------------------------------------------------------------------------------

def contract_info(contract, end_client=None):
    sla = contract.sla
    formula = contract.contract_type.name if contract.contract_type_id else ""
    sla_desc = f"{sla.name} · {sla.get_coverage_display()}" if sla else ""
    ends = [end_client.name] if end_client else [e.name for e in contract.end_clients.all()]
    return {
        "esn": contract.client.name,
        "esn_code": contract.client.code,
        "end_client": ", ".join(ends),
        "contract_ref": contract.reference,
        "contract_title": contract.title,
        "formula": formula,
        "sla": sla_desc,
        "contract_desc": " — ".join(x for x in (formula, sla_desc) if x),
        "provider": PROVIDER,
    }


# --- Ticket (rapport curatif) -------------------------------------------------------------------

def _commitment(elapsed, target, met):
    pct = min(100, round(elapsed * 100 / target)) if target else 0
    return {"elapsed": fmt_minutes(elapsed), "target": fmt_minutes(target) if target else "—",
            "met": met, "pct": pct}


def ticket_info(ticket):
    sla = ticket.contract.sla
    target = sla.target(ticket.priority) if sla else None
    response = resolution = None
    if ticket.acknowledged_at:
        elapsed = _covered_minutes(sla, ticket.created_at, ticket.acknowledged_at)
        response = _commitment(elapsed, target.response_minutes if target else None, not ticket.response_breached)
    end = ticket.resolved_at or ticket.closed_at
    if end:
        elapsed = _covered_minutes(sla, ticket.created_at, end)
        resolution = _commitment(elapsed, target.resolution_minutes if target else None,
                                 not ticket.resolution_breached)
    return {
        "reference": ticket.reference,
        "title": ticket.title,
        "description": ticket.description,
        "priority": ticket.priority,
        "priority_label": f"P{ticket.priority} · {PRIORITY_NAMES.get(ticket.priority, '')}".strip(" ·"),
        "status_label": str(ticket.get_status_display()),
        "channel": str(ticket.get_channel_display()),
        "requester": ticket.requester.display_name,
        "assignee": ticket.assignee.display_name if ticket.assignee_id else "",
        "created_at": _iso(ticket.created_at),
        "acknowledged_at": _iso(ticket.acknowledged_at),
        "resolved_at": _iso(ticket.resolved_at),
        "closed_at": _iso(ticket.closed_at or ticket.resolved_at),
        "solutions": [s.name for s in ticket.solutions.all()],
        "response": response,
        "resolution": resolution,
    }


def ticket_timeline(ticket):
    """Chronologie proposée au rédacteur (modifiable) : événements publics du ticket."""
    from tickets.models import Event, Status

    labels = dict(Status.choices)
    rows = []
    for e in ticket.events.filter(is_internal=False).select_related("actor").order_by("created_at"):
        who = e.actor.display_name if e.actor_id else _("le système")
        if e.kind == Event.Kind.CREATED:
            text = _("Ouverture du ticket par %(who)s (%(ch)s).") % {"who": who, "ch": ticket.get_channel_display()}
        elif e.kind == Event.Kind.STATUS:
            text = _("Statut « %(s)s » (%(who)s).") % {"s": labels.get(e.data.get("new"), e.data.get("new")),
                                                         "who": who}
        elif e.kind == Event.Kind.ASSIGNED and e.data.get("new"):
            text = _("Prise en charge par %(who)s.") % {"who": e.data["new"]}
        elif e.kind == Event.Kind.PRIORITY:
            text = _("Priorité passée en P%(p)s.") % {"p": e.data.get("new")}
        else:
            continue
        rows.append([timezone.localtime(e.created_at).strftime("%d/%m %H:%M"), str(text)])
    return rows


# --- Rapport préventif ----------------------------------------------------------------------------

DEFAULT_CONTROLS = [
    ("Sauvegardes", "Taux de réussite des sauvegardes (30 jours)"),
    ("Sauvegardes", "Test de restauration d'un échantillon"),
    ("Sauvegardes", "Copie hors site / immuable"),
    ("Sauvegardes", "Rétention conforme à la politique"),
    ("Mises à jour et correctifs", "Correctifs critiques serveurs Windows"),
    ("Mises à jour et correctifs", "Correctifs critiques serveurs Linux"),
    ("Mises à jour et correctifs", "Firmware pare-feu et commutateurs"),
    ("Mises à jour et correctifs", "Hyperviseurs"),
    ("Sécurité", "Antivirus / EDR : agents actifs et à jour"),
    ("Sécurité", "Règles du pare-feu : revue des exceptions"),
    ("Sécurité", "Certificats TLS : dates d'expiration"),
    ("Sécurité", "Journaux de sécurité : alertes non traitées"),
    ("Sécurité", "MFA des comptes à privilèges"),
    ("Disponibilité et performances", "Disponibilité des services critiques (30 jours)"),
    ("Disponibilité et performances", "Charge CPU / mémoire des serveurs"),
    ("Disponibilité et performances", "Supervision : alertes de la période"),
    ("Capacité et stockage", "Espace disque des volumes système"),
    ("Capacité et stockage", "Occupation de la baie de stockage"),
    ("Capacité et stockage", "État des disques (SMART / RAID)"),
    ("Comptes et accès", "Comptes inactifs depuis plus de 90 jours"),
    ("Comptes et accès", "Revue des comptes administrateurs"),
    ("Comptes et accès", "Politique de mots de passe"),
    ("Comptes et accès", "Droits des comptes de service"),
]

HEALTH_CATEGORIES = OrderedDict([
    ("Sauvegardes", "Sauvegardes"),
    ("Mises à jour et correctifs", "Correctifs"),
    ("Sécurité", "Sécurité"),
    ("Disponibilité et performances", "Disponibilité"),
    ("Capacité et stockage", "Capacité"),
    ("Comptes et accès", "Comptes"),
])


def default_controls():
    return [[cat, label, "", "", ""] for cat, label in DEFAULT_CONTROLS]


def contract_equipments(contract):
    return [[s.name] for s in contract.solutions.filter(is_active=True).order_by("category", "name")]


def control_counts(controls):
    """Comptage des résultats ; une ligne sans résultat compte comme « à renseigner »."""
    counts = Counter()
    for row in controls or []:
        result = (row[3] if len(row) > 3 else "").strip()
        counts[result if result in RESULTS else "?"] += 1
    total = sum(counts.values())
    return {
        "total": total, "ok": counts["Conforme"], "watch": counts["À surveiller"], "ko": counts["Non conforme"],
        "na": counts["N/A"], "todo": counts["?"],
        "pct_ok": round(counts["Conforme"] * 100 / total) if total else 0,
        "pct_watch": round(counts["À surveiller"] * 100 / total) if total else 0,
        "pct_ko": round(counts["Non conforme"] * 100 / total) if total else 0,
        "pct_na": round(counts["N/A"] * 100 / total) if total else 0,
    }


def _health(controls):
    """État par grande catégorie : OK, Attention (à surveiller / non conforme) ou N/A."""
    state = {}
    for row in controls or []:
        if len(row) < 4:
            continue
        key = HEALTH_CATEGORIES.get(row[0].strip())
        if not key:
            continue
        result = row[3].strip()
        current = state.get(key)
        if result in ("À surveiller", "Non conforme"):
            state[key] = "Attention"
        elif result == "Conforme" and current != "Attention":
            state[key] = "OK"
        elif result == "N/A" and current is None:
            state[key] = "N/A"
    return [state.get(k, "—") for k in HEALTH_CATEGORIES.values()]


# --- Rapport trimestriel ----------------------------------------------------------------------------

def quarter_bounds(year, quarter):
    start = datetime.date(year, 3 * (quarter - 1) + 1, 1)
    end_month = start.month + 2
    end = (datetime.date(year + (end_month == 12), (end_month % 12) + 1, 1) - datetime.timedelta(days=1))
    return start, end


def _pct(num, den):
    return round(num * 100 / den, 1) if den else None


def _in_period(value, start, end):
    try:
        day = datetime.date.fromisoformat((value or "")[:10])
    except ValueError:
        return False
    return start <= day <= end


def period_reports(contract, end_client, start, end, kind):
    from .models import Report

    qs = Report.objects.filter(contract=contract, kind=kind,
                               status__in=[Report.Status.VALIDATED, Report.Status.SENT]).select_related("ticket")
    if end_client:
        qs = qs.filter(end_client=end_client)
    rows = []
    for r in qs:
        when = None
        if kind == Report.Kind.PREVENTIVE:
            when = r.data.get("started_at") or r.data.get("planned_at")
        elif r.ticket_id:
            when = _iso(r.ticket.created_at)
        when = when or _iso(r.created_at)
        if _in_period(when, start, end):
            rows.append((when, r))
    return [r for _w, r in sorted(rows, key=lambda x: x[0])]


def quarterly_info(contract, end_client, start, end):
    from tickets.models import OPEN_STATUSES, Status, Ticket

    from .models import Report

    sla = contract.sla
    tickets = list(Ticket.objects.filter(contract=contract, created_at__date__gte=start, created_at__date__lte=end)
                   .prefetch_related("solutions"))
    resolved_statuses = {Status.RESOLVED, Status.CLOSED}
    resolved = [t for t in tickets if t.status in resolved_statuses]

    # Par mois
    months = []
    m = start
    while m <= end:
        opened_m = [t for t in tickets if timezone.localtime(t.created_at).month == m.month]
        months.append({"label": MONTHS[m.month - 1], "opened": len(opened_m),
                       "resolved": len([t for t in opened_m if t.status in resolved_statuses])})
        m = datetime.date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    peak = max([1] + [max(x["opened"], x["resolved"]) for x in months])
    for x in months:
        x["h_opened"] = round(x["opened"] * 100 / peak)
        x["h_resolved"] = round(x["resolved"] * 100 / peak)

    # Par priorité, avec engagements
    priorities = []
    for p in Priority.values:
        pt = [t for t in tickets if t.priority == p]
        target = sla.target(p) if sla else None
        acks = [_covered_minutes(sla, t.created_at, t.acknowledged_at) for t in pt if t.acknowledged_at]
        res = [t for t in pt if t.status in resolved_statuses and (t.resolved_at or t.closed_at)]
        res_min = [_covered_minutes(sla, t.created_at, t.resolved_at or t.closed_at) for t in res]
        priorities.append({
            "label": f"P{p} {PRIORITY_NAMES.get(p, '')}".strip(),
            "opened": len(pt), "resolved": len(res),
            "target_response": fmt_minutes(target.response_minutes) if target else "—",
            "avg_response": fmt_minutes(sum(acks) / len(acks)) if acks else "—",
            "target_resolution": fmt_minutes(target.resolution_minutes) if target else "—",
            "avg_resolution": fmt_minutes(sum(res_min) / len(res_min)) if res_min else "—",
            "on_time": len([t for t in res if not t.resolution_breached]),
        })

    acknowledged = [t for t in tickets if t.acknowledged_at]
    response_pct = _pct(len([t for t in acknowledged if not t.response_breached]), len(acknowledged))
    resolution_pct = _pct(len([t for t in resolved if not t.resolution_breached]), len(resolved))

    equipment = Counter(s.name for t in tickets for s in t.solutions.all())
    top_eq = equipment.most_common(6)
    eq_peak = max([1] + [n for _e, n in top_eq])

    # Rapports de la période
    preventives = period_reports(contract, end_client, start, end, Report.Kind.PREVENTIVE)
    curatives = period_reports(contract, end_client, start, end, Report.Kind.CURATIVE)

    visits, health = [], []
    total_controls = Counter()
    anomalies, pending = 0, []
    for r in preventives:
        counts = control_counts(r.data.get("controls"))
        for k in ("total", "ok", "watch", "ko", "na"):
            total_controls[k] += counts[k]
        anomalies += counts["watch"] + counts["ko"]
        label = r.data.get("site") or r.reference
        when = (r.data.get("started_at") or r.data.get("planned_at") or "")[:10]
        visits.append({"site": label, "date": when, "reference": r.reference, **counts})
        health.append({"site": label, "states": _health(r.data.get("controls"))})
        for row in r.data.get("recommendations") or []:
            if row and row[0]:
                pending.append([row[0], row[2] if len(row) > 2 else "", _("Recommandation %(ref)s") % {
                    "ref": r.reference}])
    causes = Counter((r.data.get("diagnosis_category") or "").strip() or _("Cause non déterminée") for r in curatives)
    for r in curatives:
        for row in r.data.get("followups") or []:
            if row and row[0]:
                pending.append([row[0], row[1] if len(row) > 1 else "", _("Suivi %(ref)s") % {"ref": r.reference}])
    cause_peak = max([1] + list(causes.values()))

    sites = Counter((r.data.get("site") or "").strip() for r in curatives + preventives if r.data.get("site"))

    return {
        **contract_info(contract, end_client),
        "period_start": start.isoformat(), "period_end": end.isoformat(),
        "tickets_total": len(tickets),
        "tickets_resolved": len(resolved),
        "tickets_open": len([t for t in tickets if t.status in OPEN_STATUSES]),
        "tickets_in_progress": len([t for t in tickets if t.status in {Status.NEW, Status.ACKNOWLEDGED,
                                                                      Status.IN_PROGRESS}]),
        "tickets_waiting_client": len([t for t in tickets if t.status == Status.WAITING_CLIENT]),
        "tickets_waiting_prereq": len([t for t in tickets if t.status == Status.WAITING_PREREQ]),
        "months": months,
        "priorities": priorities,
        "response_pct": response_pct,
        "resolution_pct": resolution_pct,
        "equipment": [{"name": n, "count": c, "pct": round(c * 100 / eq_peak)} for n, c in top_eq],
        "visits": visits,
        "visits_done": len(preventives),
        "health_columns": list(HEALTH_CATEGORIES.values()),
        "health": health,
        "controls": dict(total_controls),
        "anomalies": anomalies,
        "causes": [{"name": n, "count": c, "pct": round(c * 100 / cause_peak)} for n, c in causes.most_common()],
        "curative_reports": [r.reference for r in curatives],
        "preventive_reports": [r.reference for r in preventives],
        "pending_suggestions": pending,
        "sites": [{"name": n, "count": c} for n, c in sites.most_common()],
    }


def format_period(start, end):
    return f"{date_format(start, 'd/m/Y')} – {date_format(end, 'd/m/Y')}"
