"""Extraction automatique des données des rapports depuis les contrats, tickets et rapports.

Tout ce qui sort d'ici est sérialisable en JSON (dates en chaînes ISO, heure locale) :
à la validation, le résultat est figé tel quel dans ``report.data["snapshot"]``.
"""
import datetime
import re
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
    """Chronologie proposée au rédacteur (modifiable) : événements publics du ticket,
    en lignes date (AAAA-MM-JJ) | heure (HH:MM) | action."""
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
        at = timezone.localtime(e.created_at)
        rows.append([at.date().isoformat(), at.strftime("%H:%M"), str(text)])
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


def solutions_site(solutions):
    """Site déduit de la « localisation » des solutions : les localisations distinctes, dans
    l'ordre, séparées par des virgules (ex. « Siège Plateau, Agence Cocody »)."""
    seen = []
    for sol in solutions:
        loc = (sol.location or "").strip()
        if loc and loc not in seen:
            seen.append(loc)
    return ", ".join(seen)[:300]


def report_site_auto(report):
    """Site d'un rapport curatif ou préventif : localisation des solutions du ticket (curatif)
    ou des équipements listés dans le rapport (préventif)."""
    if report.ticket_id:
        return solutions_site(report.ticket.solutions.all())
    names = [row[0] for row in report.data.get("equipments") or [] if row and row[0]]
    order = {name: i for i, name in enumerate(names)}
    sols = sorted(report.contract.solutions.filter(name__in=names), key=lambda s: order.get(s.name, 0))
    return solutions_site(sols)


def report_site(report):
    """Site d'un rapport validé (figé à la validation), à défaut celui saisi à la main."""
    return ((report.data.get("snapshot") or {}).get("site") or report.data.get("site") or "").strip()


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
    """Synthèse du trimestre, construite uniquement à partir des rapports d'intervention
    validés de la période : les tickets pris en compte sont ceux des rapports curatifs."""
    from tickets.models import OPEN_STATUSES, Status, Ticket

    from .models import Report

    sla = contract.sla
    preventives = period_reports(contract, end_client, start, end, Report.Kind.PREVENTIVE)
    curatives = period_reports(contract, end_client, start, end, Report.Kind.CURATIVE)
    ticket_ids = {r.ticket_id for r in curatives if r.ticket_id}
    tickets = list(Ticket.objects.filter(pk__in=ticket_ids).order_by("created_at").prefetch_related("solutions"))
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
    visits, health = [], []
    total_controls = Counter()
    anomalies, pending = 0, []
    for r in preventives:
        counts = control_counts(r.data.get("controls"))
        for k in ("total", "ok", "watch", "ko", "na"):
            total_controls[k] += counts[k]
        anomalies += counts["watch"] + counts["ko"]
        label = report_site(r) or r.reference
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

    sites = Counter(report_site(r) for r in curatives + preventives if report_site(r))

    derived = quarterly_content(start, end, tickets, curatives, preventives, total_controls, pending,
                                resolution_pct)

    return {
        "derived": derived,
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


# --- Contenu du trimestriel déduit des rapports d'intervention ----------------------------------------

def duration_minutes(text):
    """« 2 h 50 », « 45 min », « 1 j 3 h », « 1:30 » → minutes ; None si illisible."""
    text = (text or "").lower().replace(",", ".")
    if not text.strip():
        return None
    m = re.fullmatch(r"\s*(\d+):(\d{2})\s*", text)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    total, found, after_hours = 0.0, False, False
    for value, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(j|jours?|h|heures?|min|mn|minutes?)?", text):
        found = True
        if unit.startswith("j"):
            total += float(value) * 1440
        elif unit.startswith("h"):
            total += float(value) * 60
        elif unit.startswith("m"):
            total += float(value)
        elif after_hours:
            total += float(value)  # « 2 h 50 » : les minutes suivent les heures sans unité
        else:
            total += float(value) * 60  # nombre seul : des heures
        after_hours = unit.startswith("h")
    return int(round(total)) if found else None


def _fmt_pct(value):
    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _ticket_of(report):
    return (report.data.get("snapshot") or {}).get("ticket") or {}


def quarterly_content(start, end, tickets, curatives, preventives, controls, pending, resolution_pct):
    """Rubriques du rapport trimestriel déduites des rapports curatifs et préventifs validés :
    rien n'est à saisir. Le rédacteur peut encore remplacer l'appréciation générale, la
    disponibilité et les décisions attendues du COMEX."""
    out = {}

    # Disponibilité estimée : durées d'interruption des rapports curatifs, sur 24 h × 7 j.
    days = (end - start).days + 1
    down_by_month = Counter()
    for r in curatives:
        minutes = duration_minutes(r.data.get("interruption"))
        if minutes:
            when = (_ticket_of(r).get("created_at") or r.data.get("incident_start") or start.isoformat())[:7]
            down_by_month[when] += minutes
    out["availability"] = _fmt_pct(max(0.0, 100 - sum(down_by_month.values()) * 100 / (days * 1440)))
    months, m = [], start
    while m <= end:
        nxt = datetime.date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        month_days = (min(nxt - datetime.timedelta(days=1), end) - m).days + 1
        down = down_by_month.get(m.isoformat()[:7], 0)
        months.append([MONTHS[m.month - 1], _fmt_pct(max(0.0, 100 - down * 100 / (month_days * 1440)))])
        m = nxt
    out["availability_months"] = months

    # Visites prévues : le plus grand « nombre de visites prévues » des rapports préventifs.
    planned = [int(str(r.data.get("visit_total"))) for r in preventives
               if str(r.data.get("visit_total") or "").isdigit()]
    out["visits_planned"] = max(planned + [len(preventives)]) if preventives else ""

    # Dépassements : rapports curatifs dont un engagement de service n'a pas été tenu.
    overruns = []
    for r in curatives:
        t = _ticket_of(r)
        late = [str(label) for key, label in (("response", _("prise en charge")), ("resolution", _("résolution")))
                if (t.get(key) or {}).get("met") is False]
        if late:
            overruns.append([str(_("P%(p)s · %(ref)s : %(title)s — %(what)s hors délai.") % {
                "p": t.get("priority", ""), "ref": t.get("reference", r.reference),
                "title": (t.get("title") or "")[:70], "what": ", ".join(late)})])
    out["overruns"] = overruns

    # Incidents récurrents : même catégorie de cause sur au moins deux rapports curatifs.
    by_cause = OrderedDict()
    for r in curatives:
        cat = (r.data.get("diagnosis_category") or "").strip()
        if cat:
            by_cause.setdefault(cat, []).append(r)
    out["recurring"] = [[cat, str(len(rs)), (rs[-1].data.get("fix") or rs[-1].data.get("recurrence") or "")
                         .strip()[:160]] for cat, rs in by_cause.items() if len(rs) >= 2]

    # Actions réalisées : opérations des visites préventives et corrections appliquées.
    operations = [row for r in preventives for row in r.data.get("operations") or [] if len(row) > 1 and row[1]]
    fixes = [r for r in curatives
             if r.data.get("fix_state") == "Appliquée" and (r.data.get("fix") or "").strip()]
    kpis = [(len(curatives), _("incident(s) traité(s)")), (len(preventives), _("visite(s) préventive(s)")),
            (controls.get("total", 0), _("contrôles effectués")), (len(operations), _("opérations de maintenance")),
            (len(fixes), _("corrections définitives appliquées"))]
    out["done_kpis"] = [[str(n), str(label)] for n, label in kpis if n]
    done = [row[1] + (f" ({row[2]})" if len(row) > 2 and row[2] else "") for row in operations]
    done += [f"{_ticket_of(r).get('reference', r.reference)} : {r.data['fix'].strip().splitlines()[0][:140]}"
             for r in fixes]
    out["done_actions"] = [[x] for x in done]

    # Faits marquants et points d'attention.
    resolved = [t for t in tickets if t.resolved_at or t.closed_at]
    highlights = []
    if tickets:
        highlights.append(_("%(r)d incident(s) résolu(s) sur %(n)d traité(s).") % {"r": len(resolved),
                                                                                   "n": len(tickets)})
    if resolution_pct is not None:
        highlights.append(_("Résolution dans les délais : %(p)s %%.") % {"p": _fmt_pct(resolution_pct)})
    if preventives:
        highlights.append(_("%(v)d visite(s) préventive(s), %(c)d contrôles dont %(ok)d conformes.") % {
            "v": len(preventives), "c": controls.get("total", 0), "ok": controls.get("ok", 0)})
    if fixes:
        highlights.append(_("%(n)d correction(s) définitive(s) appliquée(s).") % {"n": len(fixes)})
    out["highlights"] = [[str(x)] for x in highlights]
    attention = []
    for r in preventives:
        where = report_site(r) or r.reference
        for row in r.data.get("controls") or []:
            row = (list(row) + [""] * 5)[:5]
            if row[3] in ("Non conforme", "À surveiller"):
                attention.append(f"{row[3]} : {row[1]}" + (f" ({row[2]})" if row[2] else "") + f" — {where}")
    open_tickets = len(tickets) - len(resolved)
    if open_tickets:
        attention.append(str(_("%(n)d incident(s) encore ouvert(s) en fin de période.") % {"n": open_tickets}))
    if overruns:
        attention.append(str(_("%(n)d engagement(s) de service non tenu(s).") % {"n": len(overruns)}))
    out["attention"] = [[x] for x in attention[:8]]

    # Recommandations (mesure, justification, impact, effort) et plan d'action.
    recs, plan = [], []
    for r in preventives:
        for row in r.data.get("recommendations") or []:
            row = (list(row) + [""] * 5)[:5]
            if row[0].strip():
                impact = "élevé" if row[1] == "Haute" else "moyen"
                recs.append([row[0], str(_("Visite %(ref)s") % {"ref": r.reference}), impact, "moyen"])
                plan.append([row[0], row[1], row[2], row[3], str(_("À planifier"))])
    for r in curatives:
        for row in r.data.get("followups") or []:
            row = (list(row) + [""] * 4)[:4]
            if row[0].strip():
                plan.append([row[0], "", row[1], row[2], str(_("En cours"))])
    out["recommendations"] = recs
    out["action_plan"] = plan
    out["pending"] = pending

    # Appréciation générale proposée et prochain point.
    if not tickets and not preventives:
        headline = _("Aucune intervention sur la période")
    elif overruns:
        headline = _("Engagements globalement tenus, délais à surveiller")
    elif attention:
        headline = _("Parc globalement sain, points d'attention ciblés")
    else:
        headline = _("Engagements de service tenus, parc sain")
    out["headline"] = str(headline)
    q = (start.month - 1) // 3 + 1
    nq, ny = (1, start.year + 1) if q == 4 else (q + 1, start.year)
    out["next_point"] = str(_("Prochain point : rapport trimestriel T%(q)d %(y)d.") % {"q": nq, "y": ny})
    return out


def merged_quarterly(data, auto):
    """Contenu affiché : valeurs déduites des rapports, remplacées par celles saisies (non vides)."""
    merged = dict(auto.get("derived") or {})
    merged.update({k: v for k, v in data.items() if v not in (None, "", [])})
    return merged


def format_period(start, end):
    return f"{date_format(start, 'd/m/Y')} – {date_format(end, 'd/m/Y')}"
