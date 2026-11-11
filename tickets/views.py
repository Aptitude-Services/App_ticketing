from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Case, F, IntegerField, Q, Value, When
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from accounts.models import Organisation, User
from contracts.status import coverage_status
from sla.models import PRIORITY_NAMES, Priority

from . import services as S
from .forms import CommentForm, TicketCreateForm
from .models import OPEN_STATUSES, Attachment, Event, Status

TABS = [
    ("ouverts", _("Ouverts"), set(OPEN_STATUSES)),
    ("nouveaux", _("Nouveaux"), {Status.NEW}),
    ("en-cours", _("En cours"), {Status.ACKNOWLEDGED, Status.IN_PROGRESS}),
    ("en-attente", _("En attente"), {Status.WAITING_CLIENT, Status.WAITING_PREREQ}),
    ("resolus", _("Résolus et clos"), {Status.RESOLVED, Status.CLOSED}),
    ("tous", _("Tous"), None),
]


def _messages_from(error):
    if isinstance(error, ValidationError):
        return error.messages
    return [str(error) or _("Action non autorisée.")]


def annotate_sla(tickets, now=None):
    now = now or timezone.now()
    rows = list(tickets)
    for t in rows:
        t.sla = S.sla_status(t, now)
    return rows


def urgency_order(qs):
    """Les échéances les plus proches d'abord ; les tickets sans échéance à la fin."""
    return qs.annotate(
        due=Case(When(acknowledged_at__isnull=True, then=F("response_due")), default=F("resolution_due")),
        paused=Case(When(status__in=[Status.WAITING_CLIENT, Status.WAITING_PREREQ], then=Value(1)),
                    default=Value(0), output_field=IntegerField()),
    ).order_by("paused", F("due").asc(nulls_last=True), "priority", "-created_at")


@login_required
def ticket_list(request):
    user = request.user
    base = S.visible_tickets(user)
    tab_key = request.GET.get("vue", "ouverts")
    tab = next((t for t in TABS if t[0] == tab_key), TABS[0])
    counts = {key: (base.filter(status__in=st).count() if st else base.count()) for key, _l, st in TABS}

    qs = base.filter(status__in=tab[2]) if tab[2] else base
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(reference__icontains=q) | Q(title__icontains=q) | Q(solutions__name__icontains=q)).distinct()
    prio = request.GET.get("priorite", "")
    if prio.isdigit():
        qs = qs.filter(priority=int(prio))
    who = request.GET.get("assigne", "")
    if user.is_aptitude and who == "moi":
        qs = qs.filter(assignee=user)
    elif user.is_aptitude and who == "personne":
        qs = qs.filter(assignee__isnull=True)
    client_id = request.GET.get("client", "")
    if user.is_aptitude and client_id.isdigit():
        qs = qs.filter(contract__client_id=int(client_id))

    qs = urgency_order(qs) if tab[0] not in ("resolus",) else qs.order_by("-resolved_at", "-created_at")
    tickets = annotate_sla(qs[:300])
    clients = (Organisation.objects.filter(kind=Organisation.Kind.CLIENT, contracts__in=base.values("contract")).distinct()
               if user.is_aptitude else [])
    return render(request, "tickets/ticket_list.html", {
        "tickets": tickets, "tabs": [(k, l, counts[k]) for k, l, _s in TABS], "tab": tab[0],
        "q": q, "prio": prio, "who": who, "client_id": client_id, "clients": clients,
        "priorities": Priority.choices, "can_create": S.can_write(user),
    })


@login_required
def ticket_create(request):
    user = request.user
    if not S.can_write(user):
        raise Http404
    form = TicketCreateForm(request.POST or None, request.FILES or None, actor=user)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            ticket = S.create_ticket(user, d["contract"], d["title"], d["description"], d["solutions"],
                                     priority=d["priority"], requester=d.get("requester"))
            if d["files"]:
                S.add_comment(user, ticket, "", files=d["files"])
        except (ValidationError, PermissionDenied) as e:
            for m in _messages_from(e):
                form.add_error(None, m)
        else:
            messages.success(request, _("Ticket %(ref)s créé. Vous serez informé de chaque étape.") % {"ref": ticket.reference})
            return redirect("ticket_detail", ref=ticket.reference)

    contracts = list(form.fields["contract"].queryset)
    coverage = {c.pk: coverage_status(c) for c in contracts}
    return render(request, "tickets/ticket_form.html", {
        "form": form,
        "contracts": [{"c": c, "cov": coverage[c.pk]} for c in contracts],
        "solutions": form.fields["solutions"].queryset.select_related("contract"),
        "selected_solutions": [int(x) for x in request.POST.getlist("solutions") if x.isdigit()],
        "priority_names": PRIORITY_NAMES,
        "forfaits": {c.pk: (c.contract_type.name if c.contract_type_id else "") for c in contracts},
    })


def _get_ticket(request, ref):
    return get_object_or_404(S.visible_tickets(request.user), reference=ref)


def _timeline(ticket, user):
    show_internal = user.is_aptitude
    comments = ticket.comments.select_related("author__organisation").prefetch_related("attachments")
    events = ticket.events.select_related("actor").exclude(kind=Event.Kind.COMMENT)
    if not show_internal:
        comments = comments.filter(is_internal=False)
        events = events.filter(is_internal=False)
    items = [{"type": "comment", "at": c.created_at, "c": c} for c in comments]
    for e in events:
        text = _event_text(e)
        if text:
            items.append({"type": "event", "at": e.created_at, "e": e, "text": text})
    return sorted(items, key=lambda x: x["at"])


def _event_text(e):
    d = e.data or {}
    labels = dict(Status.choices)
    if e.kind == Event.Kind.CREATED:
        return _("a ouvert le ticket")
    if e.kind == Event.Kind.STATUS:
        new = labels.get(d.get("new"), d.get("new"))
        return (_("Statut passé à « %(s)s » automatiquement") if d.get("automatic") else _("a passé le statut à « %(s)s »")) % {"s": new}
    if e.kind == Event.Kind.PRIORITY:
        txt = _("a changé la priorité de P%(a)s à P%(b)s") % {"a": d.get("old"), "b": d.get("new")}
        return txt + (f" : {d['justification']}" if d.get("justification") else "")
    if e.kind == Event.Kind.ASSIGNED and d.get("escalated"):
        return _("a escaladé le ticket à %(u)s : %(r)s") % {"u": d.get("new"), "r": d.get("reason", "")}
    if e.kind == Event.Kind.ASSIGNED:
        return _("a assigné le ticket à %(u)s") % {"u": d["new"]} if d.get("new") else _("a retiré l'assignation")
    if e.kind == Event.Kind.SLA and d.get("note") == "created_out_of_coverage":
        return _("Ticket créé hors couverture (contrat 8x5) : il figurera dans le rapport mensuel du contrat.")
    return None


@login_required
def ticket_detail(request, ref):
    ticket = _get_ticket(request, ref)
    user = request.user
    return render(request, "tickets/ticket_detail.html", {
        "t": ticket,
        "sla": S.sla_status(ticket),
        "timeline": _timeline(ticket, user),
        "comment_form": CommentForm(actor=user) if S.can_write(user) and ticket.status != Status.CLOSED else None,
        "statuses": [(s, dict(Status.choices)[s]) for s in S.allowed_statuses(user, ticket)],
        "priorities": [(p, f"P{p} — {PRIORITY_NAMES[p]}") for p in S.allowed_priorities(user, ticket)],
        "assignees": S.assignable_users(ticket) if user.is_aptitude and not user.is_engineer and S.can_write(user) else [],
        "escalation_targets": S.escalation_targets(user, ticket) if user.is_aptitude else [],
        "can_escalate": user.is_aptitude and user.is_engineer and S.can_write(user) and ticket.is_open,
        "solutions": ticket.solutions.all(),
        "attachments": [a for a in ticket.attachments.select_related("comment") if user.is_aptitude or not a.is_internal],
        "target": ticket.contract.sla.target(ticket.priority) if ticket.contract.sla else None,
    })


def _act(request, ref, fn):
    ticket = _get_ticket(request, ref)
    try:
        msg = fn(ticket)
        if msg:
            messages.success(request, msg)
    except (ValidationError, PermissionDenied) as e:
        for m in _messages_from(e):
            messages.error(request, m)
    return redirect("ticket_detail", ref=ticket.reference)


@login_required
@require_POST
def ticket_comment(request, ref):
    def run(ticket):
        form = CommentForm(request.POST, request.FILES, actor=request.user)
        if not form.is_valid():
            raise ValidationError([e for errs in form.errors.values() for e in errs])
        d = form.cleaned_data
        S.add_comment(request.user, ticket, d["body"], internal=d.get("internal", False), files=d["files"])
        return _("Note interne ajoutée.") if d.get("internal") else _("Message envoyé.")
    return _act(request, ref, run)


@login_required
@require_POST
def ticket_status(request, ref):
    def run(ticket):
        S.change_status(request.user, ticket, request.POST.get("status", ""))
        return _("Statut mis à jour : %(s)s.") % {"s": ticket.get_status_display()}
    return _act(request, ref, run)


@login_required
@require_POST
def ticket_priority(request, ref):
    def run(ticket):
        value = request.POST.get("priority", "")
        if not value.isdigit():
            raise ValidationError(_("Choisissez une priorité."))
        S.change_priority(request.user, ticket, int(value), request.POST.get("justification", ""))
        return _("Priorité passée en P%(p)s.") % {"p": ticket.priority}
    return _act(request, ref, run)


@login_required
@require_POST
def ticket_assign(request, ref):
    def run(ticket):
        uid = request.POST.get("assignee", "")
        user = User.objects.filter(pk=uid).first() if uid.isdigit() else None
        S.assign(request.user, ticket, user)
        return _("Assignation mise à jour.")
    return _act(request, ref, run)


@login_required
@require_POST
def ticket_escalate(request, ref):
    def run(ticket):
        uid = request.POST.get("manager", "")
        user = User.objects.filter(pk=uid).first() if uid.isdigit() else None
        S.escalate(request.user, ticket, user, request.POST.get("reason", ""))
        return _("Ticket escaladé à %(u)s.") % {"u": user.display_name}
    return _act(request, ref, run)


@login_required
def attachment_download(request, ref, pk):
    ticket = _get_ticket(request, ref)
    att = get_object_or_404(Attachment.objects.select_related("comment"), pk=pk, ticket=ticket)
    if att.is_internal and not request.user.is_aptitude:
        raise Http404
    resp = FileResponse(att.file.open("rb"), as_attachment=True, filename=att.name)
    resp["X-Content-Type-Options"] = "nosniff"
    return resp
