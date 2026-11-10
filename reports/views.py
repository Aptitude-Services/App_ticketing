from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from . import services as S
from .builders import control_counts
from .forms import RejectForm, ReportContentForm, ReportCreateForm
from .models import Report

KIND_LEADS = {
    Report.Kind.CURATIVE: gettext_lazy("Un rapport par incident traité : données du ticket et du contrat reprises automatiquement."),
    Report.Kind.PREVENTIVE: gettext_lazy("Un rapport par visite de maintenance planifiée : contrôles, opérations, recommandations."),
    Report.Kind.QUARTERLY: gettext_lazy("Synthèse du trimestre, consolidée à partir des tickets et des rapports validés."),
}
STATUS_TABS = [
    ("tous", gettext_lazy("Tous"), None),
    ("brouillons", gettext_lazy("Brouillons"), [Report.Status.DRAFT, Report.Status.REJECTED]),
    ("a-valider", gettext_lazy("À valider"), [Report.Status.SUBMITTED]),
    ("valides", gettext_lazy("Validés"), [Report.Status.VALIDATED]),
    ("envoyes", gettext_lazy("Envoyés"), [Report.Status.SENT]),
]


ALL = "tous"
MAIL_WARNING = gettext_lazy("L'email de notification n'a pas pu partir : vérifiez Configuration > Messagerie "
                            "(le journal des emails indique l'erreur).")


def _kind_or_404(kind, allow_all=False):
    if allow_all and kind == ALL:
        return ALL
    if kind not in Report.Kind.values:
        raise Http404
    return Report.Kind(kind)


def _visible_or_404(request, pk):
    return get_object_or_404(S.visible_reports(request.user), pk=pk)


@login_required
def report_list(request, kind):
    kind = _kind_or_404(kind, allow_all=True)
    base = S.visible_reports(request.user)
    if kind != ALL:
        base = base.filter(kind=kind)
    tabs = STATUS_TABS if request.user.is_aptitude else STATUS_TABS[:1]
    tab_key = request.GET.get("vue", "tous")
    tab = next((t for t in tabs if t[0] == tab_key), tabs[0])
    qs = base.filter(status__in=tab[2]) if tab[2] else base
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(reference__icontains=q) | qs.filter(title__icontains=q) | qs.filter(
            contract__client__name__icontains=q) | qs.filter(end_client__name__icontains=q)
    to_validate = [r for r in base.filter(status=Report.Status.SUBMITTED) if S.can_validate(request.user, r)]
    return render(request, "reports/report_list.html", {
        "kind": kind, "kind_label": Report.Kind(kind).label if kind != ALL else _("Rapports"),
        "lead": KIND_LEADS.get(kind, _("Rapports d'intervention et synthèses trimestrielles de vos contrats.")),
        "kinds": Report.Kind.choices, "can_create": S.can_author(request.user) and kind != ALL,
        "reports": qs.distinct()[:300], "tabs": [(k, l, base.filter(status__in=st).count() if st else base.count())
                                                 for k, l, st in tabs],
        "tab": tab[0], "q": q, "to_validate": to_validate,
    })


@login_required
def report_create(request, kind):
    kind = _kind_or_404(kind)
    if not S.can_author(request.user):
        raise PermissionDenied
    form = ReportCreateForm(request.POST or None, user=request.user, kind=kind)
    if request.method == "POST" and form.is_valid():
        report = S.create_report(
            request.user, kind, form.contract_obj, end_client=form.end_client_obj, ticket=form.ticket_obj,
            year=getattr(form, "year", None), quarter=getattr(form, "q", None))
        messages.success(request, _("Rapport %(ref)s créé : complétez les informations manquantes.")
                         % {"ref": report.reference})
        return redirect("report_edit", report.pk)
    return render(request, "reports/report_create.html", {
        "form": form, "kind": kind, "kind_label": Report.Kind(kind).label, "lead": KIND_LEADS[kind]})


@login_required
def report_edit(request, pk):
    report = _visible_or_404(request, pk)
    if not S.can_edit(request.user, report):
        messages.error(request, _("Ce rapport n'est plus modifiable."))
        return redirect("report_detail", report.pk)
    form = ReportContentForm(request.POST or None, report=report)
    if request.method == "POST" and form.is_valid():
        form.apply()
        report.save()
        if "submit" in request.POST:
            try:
                validators, mailed = S.submit(request.user, report)
            except PermissionDenied as e:
                messages.error(request, str(e))
            else:
                names = ", ".join(u.display_name for u in validators) or _("aucun validateur disponible")
                messages.success(request, _("Rapport soumis à validation (%(v)s).") % {"v": names})
                if validators and not mailed:
                    messages.warning(request, MAIL_WARNING)
                return redirect("report_detail", report.pk)
        else:
            messages.success(request, _("Brouillon enregistré."))
        if "preview" in request.POST:
            return redirect("report_detail", report.pk)
        return redirect("report_edit", report.pk)
    return render(request, "reports/report_edit.html", {
        "report": report, "form": form, "auto": S.auto_data(report), "kind": report.kind})


@login_required
def report_detail(request, pk):
    report = _visible_or_404(request, pk)
    auto = S.auto_data(report)
    user = request.user
    ctx = {
        "report": report, "auto": auto, "m": report.data, "esn": report.esn,
        "logo": report.esn.logo_data_uri(),
        "can_edit": S.can_edit(user, report), "can_validate": S.can_validate(user, report),
        "can_send": S.can_send(user, report), "can_client_confirm": S.can_client_confirm(user, report),
        "reject_form": RejectForm(), "fingerprint_short": report.fingerprint[:24], "kind": report.kind,
    }
    if report.kind == Report.Kind.PREVENTIVE:
        ctx["counts"] = control_counts(report.data.get("controls"))
        ctx["control_groups"] = _group_controls(report.data.get("controls"))
    if report.kind == Report.Kind.QUARTERLY:
        ctx.update(_quarterly_ctx(report.data, auto))
    return render(request, f"reports/print_{report.kind}.html", ctx)


def _num(value):
    try:
        return float(str(value).replace(",", ".").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _gauge(label, value, target, floor=0.0):
    """Jauge : valeur et repère d'objectif sur une échelle [floor, 100]."""
    def scale(v):
        return None if v is None else max(0, min(100, round((v - floor) * 100 / (100 - floor))))
    target_n = _num(target)
    return {"label": label, "value": value, "target": target,
            "ok": value is not None and target_n is not None and value >= target_n,
            "width": scale(value) or 0, "mark": scale(target_n)}


def _quarterly_ctx(m, auto):
    avail, avail_target = _num(m.get("availability")), m.get("availability_target")
    res_target = m.get("resolution_target")
    floor = 99.0 if (avail or 100) >= 99 else 90.0
    months = []
    for row in m.get("availability_months") or []:
        v = _num(row[1] if len(row) > 1 else None)
        if v is None:
            continue
        g = _gauge(row[0], v, avail_target, floor)
        months.append({"label": row[0], "raw": row[1], "ok": g["ok"], "width": g["width"]})
    impacts = [("élevé", _("Impact élevé")), ("moyen", _("Impact moyen"))]
    efforts = ["faible", "moyen", "élevé"]
    matrix = [{"label": label, "cells": [[i for i, r in enumerate(m.get("recommendations") or [], 1)
                                          if len(r) > 3 and r[2].strip().lower() == imp and r[3].strip().lower() == eff]
                                         for eff in efforts]} for imp, label in impacts]
    return {
        "avail": avail, "avail_ok": avail is not None and _num(avail_target) is not None and avail >= _num(avail_target),
        "resolution_ok": auto.get("resolution_pct") is not None and _num(res_target) is not None
        and auto["resolution_pct"] >= _num(res_target),
        "gauges": [
            _gauge(_("Prise en charge"), auto.get("response_pct"), res_target),
            _gauge(_("Résolution"), auto.get("resolution_pct"), res_target),
            _gauge(_("Disponibilité"), avail, avail_target, floor),
        ],
        "months_avail": months, "matrix": matrix,
    }


def _group_controls(rows):
    groups = []
    for row in rows or []:
        cat = row[0] if row else ""
        if not groups or groups[-1][0] != cat:
            groups.append((cat, []))
        groups[-1][1].append(row)
    return groups


@login_required
@require_POST
def report_action(request, pk, action):
    report = _visible_or_404(request, pk)
    user = request.user
    try:
        if action == "soumettre":
            validators, mailed = S.submit(user, report)
            messages.success(request, _("Rapport soumis à validation."))
            if validators and not mailed:
                messages.warning(request, MAIL_WARNING)
        elif action == "valider":
            S.validate(user, report)
            messages.success(request, _("Rapport validé et verrouillé."))
        elif action == "corriger":
            form = RejectForm(request.POST)
            if not form.is_valid():
                messages.error(request, _("Indiquez les corrections attendues."))
            else:
                mailed = S.reject(user, report, form.cleaned_data["comment"])
                messages.success(request, _("Rapport renvoyé au rédacteur."))
                if not mailed:
                    messages.warning(request, MAIL_WARNING)
        elif action == "envoyer":
            recipients, mailed = S.send_to_client(user, report)
            if mailed:
                messages.success(request, _("Rapport envoyé à %(to)s.") % {"to": ", ".join(recipients)})
            else:
                messages.warning(request, _("Rapport publié sur le portail du client, mais l'email à %(to)s n'a pas "
                                            "pu partir : vérifiez Configuration > Messagerie.")
                                 % {"to": ", ".join(recipients)})
        elif action == "confirmer":
            S.client_confirm(user, report)
            messages.success(request, _("Merci, la réception du rapport est confirmée."))
        else:
            raise Http404
    except (PermissionDenied, ValidationError) as e:
        messages.error(request, " ".join(getattr(e, "messages", [str(e)])))
    return redirect("report_detail", report.pk)
