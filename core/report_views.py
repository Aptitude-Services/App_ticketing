"""Rapports : préventif, curatif, trimestriel. Pages réservées à l'équipe Aptitude, contenu à venir."""
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

REPORTS = {
    "preventif": {
        "title": _("Rapport préventif"),
        "lead": _("Interventions planifiées : maintenances, revues firewall, durcissement."),
    },
    "curatif": {
        "title": _("Rapport curatif"),
        "lead": _("Incidents traités : volumes, priorités, délais tenus et dépassés."),
    },
    "trimestriel": {
        "title": _("Rapport trimestriel"),
        "lead": _("Synthèse du trimestre par client, pour le comité de pilotage."),
    },
}


@login_required
def report(request, kind):
    if not request.user.is_aptitude or kind not in REPORTS:
        raise Http404
    return render(request, "core/report.html", {"report": REPORTS[kind], "kind": kind})
