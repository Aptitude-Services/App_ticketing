"""Formulaires des rapports.

- Création : choix du contrat / client final (et du ticket ou du trimestre) ;
- Saisie : champs non disponibles dans l'application, décrits par SCHEMA et rangés
  dans ``report.data``. Les tableaux se saisissent une ligne par entrée, colonnes
  séparées par « | » (ex. « 08:42 | Ouverture du ticket »).
"""
import datetime
import json
import re

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.permissions import visible_contracts
from tickets.models import Status as TicketStatus
from tickets.services import visible_tickets

from .builders import RESULTS
from .models import Report

LEVELS = [("", "—"), ("N1", "N1"), ("N2", "N2"), ("N3", "N3"), ("N3 constructeur", _("N3 constructeur"))]
MODES = [("À distance", _("À distance")), ("Sur site", _("Sur site"))]
CAUSE_STATES = [("Cause identifiée", _("Cause identifiée")), ("Cause probable", _("Cause probable")),
                ("Cause non déterminée", _("Cause non déterminée"))]
WORKAROUND_STATES = [("Non nécessaire", _("Non nécessaire")), ("Appliquée", _("Appliquée")),
                     ("Non applicable", _("Non applicable"))]
FIX_STATES = [("Appliquée", _("Appliquée")), ("Planifiée", _("Planifiée")), ("En attente", _("En attente"))]

# (clé, libellé, type, options) — type : text, textarea, datetime, date, int, choice, lines
SCHEMA = {
    Report.Kind.CURATIVE: [
        (_("Intervention"), [
            ("title", _("Intitulé du rapport"), "text", {"help": _("Ex. Authentification / Accès distant")}),
            ("site", _("Site concerné"), "text", {}),
            ("level", _("Niveau de traitement"), "choice", {"choices": LEVELS}),
            ("technician_title", _("Fonction de l'intervenant"), "text",
             {"help": _("Ex. Ingénieure support N2")}),
        ]),
        (_("Description et impact"), [
            ("symptoms", _("Symptômes"), "textarea", {}),
            ("incident_start", _("Début de l'incident"), "datetime", {}),
            ("interruption", _("Durée de l'interruption"), "text", {"help": _("Ex. 2 h 50")}),
            ("users_impacted", _("Utilisateurs touchés"), "text", {"help": _("Ex. 120 sur 212")}),
            ("services_impacted", _("Services indisponibles ou dégradés"), "text", {}),
        ]),
        (_("Chronologie"), [
            ("timeline", _("Chronologie"), "lines", {"columns": [_("Date"), _("Heure"), _("Action")],
                                                     "editor": ["date", "time", "text"],
                                                     "help": _("Préremplie depuis l'historique du ticket.")}),
        ]),
        (_("Diagnostic et solution"), [
            ("diagnosis_category", _("Catégorie de la cause"), "text",
             {"help": _("Ex. Certificat expiré, Configuration, Défaut matériel… (reprise dans le trimestriel)")}),
            ("cause_state", _("État du diagnostic"), "choice", {"choices": CAUSE_STATES}),
            ("diagnosis", _("Diagnostic"), "textarea", {}),
            ("workaround_state", _("Solution temporaire"), "choice", {"choices": WORKAROUND_STATES}),
            ("workaround", _("Détail de la solution temporaire"), "textarea", {}),
            ("fix_state", _("Correction définitive"), "choice", {"choices": FIX_STATES}),
            ("fix", _("Détail de la correction définitive"), "textarea", {}),
        ]),
        (_("Tests, temps passé et suivi"), [
            ("tests", _("Tests de validation"), "lines", {"columns": [_("Test"), _("Résultat")],
                                                         "help": _("Résultat : Validé ou Échec.")}),
            ("time_spent", _("Temps passé"), "lines",
             {"columns": [_("Phase"), _("Durée"), _("Couverture")],
              "help": _("Ex. Diagnostic | 0 h 45 | Contrat")}),
            ("time_note", _("Commentaire sur le temps passé"), "text", {}),
            ("followups", _("Actions de suivi"), "lines",
             {"columns": [_("Action"), _("Responsable"), _("Échéance"), _("Ticket")]}),
        ]),
        (_("Clôture"), [
            ("closure_reason", _("Motif de clôture"), "textarea", {}),
            ("recurrence", _("Récurrence"), "text", {}),
            ("client_confirmation", _("Confirmation du client"), "text",
             {"help": _("Ex. Confirmé par J. Exemple le 04/11/2026 à 11:20.")}),
            ("client_rep_name", _("Représentant du client"), "text", {}),
            ("client_rep_title", _("Fonction du représentant"), "text", {}),
            ("annexes", _("Annexes jointes"), "lines", {"columns": [_("Annexe")]}),
        ]),
    ],
    Report.Kind.PREVENTIVE: [
        (_("Contexte de l'intervention"), [
            ("site", _("Site concerné"), "text", {}),
            ("visit_no", _("Visite n°"), "int", {}),
            ("visit_total", _("Nombre de visites prévues"), "int", {}),
            ("periodicity", _("Périodicité"), "text", {"help": _("Ex. trimestrielle")}),
            ("planned_at", _("Date / heure planifiée"), "datetime", {}),
            ("started_at", _("Début d'intervention"), "datetime", {}),
            ("ended_at", _("Fin d'intervention"), "datetime", {}),
            ("mode", _("Mode d'intervention"), "choice", {"choices": MODES}),
            ("level", _("Niveau"), "choice", {"choices": LEVELS}),
            ("technician", _("Technicien(s) intervenant(s)"), "text", {}),
            ("technician_title", _("Fonction de l'intervenant"), "text", {}),
            ("equipments", _("Équipements ou services concernés"), "lines",
             {"columns": [_("Équipement")], "help": _("Prérempli avec les solutions du contrat.")}),
        ]),
        (_("Synthèse"), [
            ("summary", _("Synthèse"), "textarea", {}),
        ]),
        (_("Contrôles réalisés"), [
            ("controls", _("Contrôles"), "lines",
             {"columns": [_("Catégorie"), _("Contrôle"), _("Équipement"), _("Résultat"), _("Commentaire")],
              "help": _("Résultat : %(r)s. Une annexe se cite dans le commentaire (ex. « A1 »).")
              % {"r": ", ".join(RESULTS)}, "rows": 18}),
        ]),
        (_("Opérations, anomalies et indicateurs"), [
            ("operations", _("Opérations de maintenance exécutées"), "lines",
             {"columns": [_("Heure"), _("Opération"), _("Équipement")]}),
            ("recommendations", _("Anomalies et recommandations"), "lines",
             {"columns": [_("Recommandation"), _("Priorité"), _("Responsable"), _("Échéance"), _("Ticket curatif")],
              "help": _("Priorité : Haute, Moyenne ou Basse.")}),
            ("indicators", _("Indicateurs avant / après"), "lines",
             {"columns": [_("Indicateur"), _("Avant"), _("Après")]}),
        ]),
        (_("Suite et validation"), [
            ("next_date", _("Prochaine intervention"), "date", {}),
            ("next_scope", _("Objet de la prochaine intervention"), "textarea", {}),
            ("client_rep_name", _("Représentant du client"), "text", {}),
            ("client_rep_title", _("Fonction du représentant"), "text", {}),
            ("annexes", _("Annexes jointes"), "lines", {"columns": [_("Annexe")]}),
        ]),
    ],
    Report.Kind.QUARTERLY: [
        (_("Synthèse exécutive"), [
            ("headline", _("Appréciation générale"), "text",
             {"help": _("Ex. Parc globalement sain, points d'attention ciblés")}),
            ("availability", _("Disponibilité des services critiques (%)"), "text", {"help": _("Ex. 99,92")}),
            ("availability_target", _("Objectif de disponibilité (%)"), "text", {}),
            ("availability_months", _("Disponibilité par mois"), "lines",
             {"columns": [_("Mois"), _("Disponibilité %")]}),
            ("resolution_target", _("Objectif de résolution dans les délais (%)"), "text", {}),
            ("highlights", _("Faits marquants"), "lines", {"columns": [_("Fait marquant")]}),
            ("attention", _("Points d'attention"), "lines", {"columns": [_("Point d'attention")]}),
        ]),
        (_("Maintenances préventives"), [
            ("visits_planned", _("Visites préventives planifiées"), "int",
             {"help": _("Les visites réalisées sont reprises des rapports préventifs validés.")}),
            ("visits_note", _("Commentaire"), "text", {}),
        ]),
        (_("Engagements et incidents"), [
            ("overruns", _("Dépassements du trimestre"), "lines", {"columns": [_("Dépassement")]}),
            ("recurring", _("Incidents récurrents"), "lines",
             {"columns": [_("Incident"), _("Occurrences"), _("Action")]}),
        ]),
        (_("Actions"), [
            ("done_kpis", _("Chiffres clés des actions réalisées"), "lines",
             {"columns": [_("Valeur"), _("Libellé")], "help": _("Ex. 42 | correctifs de sécurité appliqués")}),
            ("done_actions", _("Actions réalisées"), "lines", {"columns": [_("Action")]}),
            ("pending", _("Actions en attente"), "lines",
             {"columns": [_("Action ou anomalie"), _("Attendue de"), _("Situation")],
              "help": _("Préremplies avec les recommandations et actions de suivi des rapports de la période.")}),
        ]),
        (_("Recommandations et plan d'action"), [
            ("recommendations", _("Recommandations"), "lines",
             {"columns": [_("Mesure"), _("Justification"), _("Impact"), _("Effort")],
              "help": _("Impact : élevé ou moyen. Effort : faible, moyen ou élevé.")}),
            ("action_plan", _("Plan d'action"), "lines",
             {"columns": [_("Action"), _("Priorité"), _("Responsable"), _("Échéance"), _("Statut")]}),
        ]),
    ],
}


def parse_lines(text, ncols):
    rows = []
    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        cells = [c.strip() for c in raw.split("|")]
        if len(cells) > ncols:  # le dernier champ peut contenir des « | »
            cells = cells[:ncols - 1] + [" | ".join(cells[ncols - 1:])]
        rows.append(cells + [""] * (ncols - len(cells)))
    return rows


def format_lines(rows):
    return "\n".join(" | ".join(str(c) for c in row).rstrip(" |") for row in rows or [])


def _iso_day(value):
    """« 2026-11-04 » ou « 04/11/2026 » → « 2026-11-04 » ; None si la date est invalide."""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(value.strip(), fmt).date().isoformat()
        except (ValueError, AttributeError):
            continue
    return None


def timeline_rows(rows, created_at=None):
    """Chronologie au format date | heure | action. Convertit l'ancien format à deux
    colonnes (« 04/11 08:42 » | action) en reprenant l'année du rapport."""
    year = (created_at or timezone.now()).year
    out = []
    for row in rows or []:
        if len(row) >= 3:
            out.append(list(row[:3]))
            continue
        moment, action = (list(row) + ["", ""])[:2]
        m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\s+(\d{1,2}:\d{2})\s*", moment or "")
        if m:
            day = datetime.date(int(m.group(3) or year), int(m.group(2)), int(m.group(1))).isoformat()
            out.append([day, m.group(4).zfill(5), action])
        else:
            out.append(["", (moment or "").strip(), action])
    return out


def fields_of(kind):
    return [f for _section, fields in SCHEMA[kind] for f in fields]


class ReportContentForm(forms.Form):
    """Champs saisis par le rédacteur, construits depuis SCHEMA."""

    def __init__(self, *args, report, **kwargs):
        self.report = report
        initial = {}
        for key, _label, ftype, opts in fields_of(report.kind):
            value = report.data.get(key, "")
            if key == "timeline":
                value = timeline_rows(value, report.created_at)
            initial[key] = format_lines(value) if ftype == "lines" else value
        super().__init__(*args, initial=initial, **kwargs)
        for key, label, ftype, opts in fields_of(report.kind):
            self.fields[key] = self._build(label, ftype, opts)

    @staticmethod
    def _build(label, ftype, opts):
        common = {"label": label, "required": False, "help_text": opts.get("help", "")}
        if ftype == "textarea":
            return forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), **common)
        if ftype == "lines" and opts.get("editor"):
            # Tableau de saisie (date, heure, texte…) : le JS remplace la zone de texte,
            # qui reste le support envoyé au serveur (colonnes séparées par « | »).
            spec = [{"label": str(label), "type": kind} for label, kind in zip(opts["columns"], opts["editor"])]
            return forms.CharField(widget=forms.Textarea(attrs={
                "rows": 4, "class": "mono", "data-row-editor": json.dumps(spec, ensure_ascii=False),
                "data-add-label": str(_("Ajouter une étape")),
            }), **common)
        if ftype == "lines":
            cols = " | ".join(str(c) for c in opts["columns"])
            hint = _("Une ligne par entrée") if len(opts["columns"]) == 1 else                 _("Une ligne par entrée, colonnes séparées par « | » : %(c)s") % {"c": cols}
            common["help_text"] = f"{hint}. {opts.get('help', '')}".strip()
            return forms.CharField(widget=forms.Textarea(attrs={"rows": opts.get("rows", 4), "placeholder": cols,
                                                                "class": "mono"}), **common)
        if ftype == "datetime":
            return forms.CharField(widget=forms.DateTimeInput(attrs={"type": "datetime-local"}), **common)
        if ftype == "date":
            return forms.CharField(widget=forms.DateInput(attrs={"type": "date"}), **common)
        if ftype == "int":
            return forms.IntegerField(min_value=0, **common)
        if ftype == "choice":
            return forms.ChoiceField(choices=[("", "—")] + [c for c in opts["choices"] if c[0]], **common)
        return forms.CharField(max_length=300, **common)

    def clean_timeline(self):
        """Date au format AAAA-MM-JJ (ou JJ/MM/AAAA), heure HH:MM ; une erreur indique la ligne."""
        rows = parse_lines(self.cleaned_data.get("timeline"), 3)
        out, errors = [], []
        for n, (day, hour, action) in enumerate(rows, start=1):
            iso = _iso_day(day)
            if day and iso is None:
                errors.append(_("Étape %(n)d : date invalide « %(d)s ».") % {"n": n, "d": day})
            if hour and not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", hour):
                errors.append(_("Étape %(n)d : heure invalide « %(h)s » (HH:MM).") % {"n": n, "h": hour})
            if (day or hour) and not action:
                errors.append(_("Étape %(n)d : décrivez l'action.") % {"n": n})
            out.append([iso or day, hour.zfill(5) if hour else "", action])
        if errors:
            raise forms.ValidationError(errors)
        return format_lines(out)

    def sections(self):
        """Champs liés regroupés par section, pour l'affichage."""
        return [(title, [self[key] for key, *_rest in fields]) for title, fields in SCHEMA[self.report.kind]]

    def apply(self):
        data = dict(self.report.data)
        for key, _label, ftype, opts in fields_of(self.report.kind):
            value = self.cleaned_data.get(key)
            if ftype == "lines":
                value = parse_lines(value, len(opts["columns"]))
            data[key] = "" if value is None else value
        self.report.data = data
        if data.get("title"):
            self.report.title = data["title"][:200]


# --- Création ------------------------------------------------------------------------------------

def _combo(contract, end_client):
    return f"{contract.pk}:{end_client.pk if end_client else 0}"


def contract_choices(user):
    """« Contrat — ESN → client final » : une entrée par client final couvert."""
    choices = []
    for c in visible_contracts(user).filter(status__in=["active", "expired"]).prefetch_related("end_clients") \
            .order_by("client__name", "reference"):
        ends = list(c.end_clients.all()) or [None]
        for e in ends:
            label = f"{c.reference} — {c.client.name} → {e.name if e else _('sans client final')}"
            choices.append((_combo(c, e), label))
    return choices


def ticket_choices(user):
    choices = []
    qs = (visible_tickets(user).filter(status__in=[TicketStatus.RESOLVED, TicketStatus.CLOSED,
                                                   TicketStatus.IN_PROGRESS, TicketStatus.ACKNOWLEDGED])
          .select_related("contract__client").prefetch_related("contract__end_clients").order_by("-created_at")[:300])
    for t in qs:
        ends = list(t.contract.end_clients.all()) or [None]
        for e in ends:
            label = f"{t.reference} — {t.title[:60]} · {t.contract.client.name} → {e.name if e else '—'}"
            choices.append((f"{t.pk}:{e.pk if e else 0}", label))
    return choices


def quarter_choices():
    today = timezone.localdate()
    year, q = today.year, (today.month - 1) // 3 + 1
    out = []
    for _i in range(6):
        q -= 1
        if q == 0:
            year, q = year - 1, 4
        out.append((f"{year}-{q}", f"T{q} {year}"))
    current = (today.month - 1) // 3 + 1
    return [(f"{today.year}-{current}", f"T{current} {today.year} (en cours)")] + out


class ReportCreateForm(forms.Form):
    ticket = forms.ChoiceField(label=_("Ticket traité"), required=False)
    contract = forms.ChoiceField(label=_("Contrat et client final"), required=False)
    quarter = forms.ChoiceField(label=_("Trimestre"), required=False)

    def __init__(self, *args, user, kind, **kwargs):
        super().__init__(*args, **kwargs)
        self.user, self.kind = user, kind
        if kind == Report.Kind.CURATIVE:
            del self.fields["contract"], self.fields["quarter"]
            self.fields["ticket"].choices = [("", "—")] + ticket_choices(user)
            self.fields["ticket"].required = True
        else:
            del self.fields["ticket"]
            self.fields["contract"].choices = [("", "—")] + contract_choices(user)
            self.fields["contract"].required = True
            if kind == Report.Kind.QUARTERLY:
                self.fields["quarter"].choices = quarter_choices()
                self.fields["quarter"].initial = quarter_choices()[1][0]
                self.fields["quarter"].required = True
            else:
                del self.fields["quarter"]

    def clean(self):
        from contracts.models import Contract
        from tickets.models import Ticket

        data = super().clean()
        self.ticket_obj = self.contract_obj = self.end_client_obj = None
        try:
            if self.kind == Report.Kind.CURATIVE and data.get("ticket"):
                tid, eid = (int(x) for x in data["ticket"].split(":"))
                self.ticket_obj = visible_tickets(self.user).get(pk=tid)
                self.contract_obj = self.ticket_obj.contract
            elif data.get("contract"):
                cid, eid = (int(x) for x in data["contract"].split(":"))
                self.contract_obj = visible_contracts(self.user).get(pk=cid)
            else:
                return data
        except (ValueError, Ticket.DoesNotExist, Contract.DoesNotExist):
            raise forms.ValidationError(_("Sélection invalide."))
        if eid:
            self.end_client_obj = self.contract_obj.end_clients.filter(pk=eid).first()
            if self.end_client_obj is None:
                raise forms.ValidationError(_("Ce client final n'est pas couvert par le contrat."))
        if self.kind == Report.Kind.QUARTERLY and data.get("quarter"):
            year, q = (int(x) for x in data["quarter"].split("-"))
            self.year, self.q = year, q
        return data


class RejectForm(forms.Form):
    comment = forms.CharField(label=_("Corrections demandées"), widget=forms.Textarea(attrs={"rows": 3}))
