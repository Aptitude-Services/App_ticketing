"""Page COMEX : choix du client final et de la période, téléchargement du PowerPoint.

Réservée au Super Admin et aux Managers d'Aptitude : le fichier est relu dans PowerPoint
avant d'être remis au client.
"""
import datetime
import re

from django import forms
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_http_methods

from accounts.models import Organisation, Profile

from ..builders import quarter_bounds
from .data import comex_data
from .deck import build_comex

ALLOWED = {Profile.APTITUDE_ADMIN, Profile.APTITUDE_MANAGER}
MAX_DAYS = 2 * 366
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def scope_choices():
    """« ESN → client final », pour chaque client final rattaché à une ESN active."""
    choices = []
    for esn in Organisation.objects.filter(kind=Organisation.Kind.CLIENT, is_active=True).order_by("name"):
        for end in esn.end_clients.filter(is_active=True).order_by("name"):
            choices.append((f"{esn.pk}:{end.pk}", f"{esn.name} → {end.name}"))
    return choices


class ComexForm(forms.Form):
    scope = forms.ChoiceField(label=gettext_lazy("Client final"),
                              help_text=gettext_lazy("ESN → client final : le COMEX couvre tous les contrats "
                                                     "de l'ESN pour ce client."))
    start = forms.DateField(label=gettext_lazy("Du"), widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    end = forms.DateField(label=gettext_lazy("Au"), widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["scope"].choices = [("", "—")] + scope_choices()

    def clean(self):
        data = super().clean()
        start, end = data.get("start"), data.get("end")
        if start and end:
            if start > end:
                raise forms.ValidationError(_("La date de début doit précéder la date de fin."))
            if (end - start).days > MAX_DAYS:
                raise forms.ValidationError(_("La période est limitée à deux ans."))
        if data.get("scope"):
            esn_id, end_id = (int(x) for x in data["scope"].split(":"))
            esn = Organisation.objects.filter(pk=esn_id, kind=Organisation.Kind.CLIENT).first()
            end_client = esn.end_clients.filter(pk=end_id).first() if esn else None
            if not end_client:
                raise forms.ValidationError(_("Client final inconnu pour cette ESN."))
            data["esn"], data["end_client"] = esn, end_client
        return data


def shortcuts(today):
    q = (today.month - 1) // 3 + 1
    current = quarter_bounds(today.year, q)
    prev = quarter_bounds(today.year - (q == 1), 4 if q == 1 else q - 1)
    three = (today - datetime.timedelta(days=91) + datetime.timedelta(days=1), today)
    return [
        (_("3 derniers mois"), *three),
        (_("Trimestre en cours (T%(q)d)") % {"q": q}, current[0], min(current[1], today)),
        (_("Trimestre précédent (T%(q)d)") % {"q": (q - 2) % 4 + 1}, *prev),
        (_("Année %(y)d") % {"y": today.year}, datetime.date(today.year, 1, 1), today),
    ]


def _filename(end_client, start, end):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", end_client.name).strip("-")[:40] or "client"
    return f"COMEX_{slug}_{start:%Y%m%d}-{end:%Y%m%d}.pptx"


@login_required
@require_http_methods(["GET", "POST"])
def comex(request):
    if request.user.profile not in ALLOWED:
        raise Http404
    today = timezone.localdate()
    cuts = shortcuts(today)
    if request.method == "POST":
        form = ComexForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            content = build_comex(comex_data(d["esn"], d["end_client"], d["start"], d["end"]))
            response = HttpResponse(content, content_type=PPTX)
            response["Content-Disposition"] = f'attachment; filename="{_filename(d["end_client"], d["start"], d["end"])}"'
            return response
    else:
        start, end = cuts[0][1], cuts[0][2]
        try:
            start = datetime.date.fromisoformat(request.GET.get("du", "")) or start
            end = datetime.date.fromisoformat(request.GET.get("au", "")) or end
        except ValueError:
            pass
        form = ComexForm(initial={"start": start, "end": end, "scope": request.GET.get("perimetre", "")})
    return render(request, "reports/comex.html", {"form": form, "shortcuts": cuts,
                                                   "scope": request.POST.get("scope") or request.GET.get("perimetre", "")})
