import datetime
import json

from django import forms
from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, render
from django.urls import path
from django.utils.translation import gettext_lazy as _

from core.admin_cascade import SuperAdminCascadeDeleteMixin
from core.assets import versioned

from accounts.models import Organisation, Profile, User
from .models import (Contract, ContractAccess, ContractType, LicenseAlertSettings, LicenseNotice, ServiceFeature,
                     Solution)
from .widgets import FeatureChecklist


# --- Import Excel des solutions -------------------------------------------------
# Deux étapes : lire et vérifier le fichier (sans rien enregistrer), puis enregistrer.
# Le formulaire de création de contrat vérifie le fichier avant d'enregistrer quoi que ce soit.

CATEGORY_ALIASES = {
    "software": "software", "logiciel": "software",
    "hardware": "hardware", "matériel": "hardware", "materiel": "hardware",
    "vm": "vm", "machine virtuelle": "vm", "virtual machine": "vm",
    "cloud": "cloud", "saas": "cloud",
    "other": "other", "autre": "other",
}
HEADER_ALIASES = {
    "contrat": "contract", "catégorie": "category", "categorie": "category",
    "éditeur": "vendor", "editeur": "vendor", "vendor": "vendor",
    "modèle": "model", "modele": "model", "model": "model",
    "nom": "name", "name": "name",
    "n° de série": "serial_number", "n de série": "serial_number", "numero de serie": "serial_number",
    "serial": "serial_number", "serial_number": "serial_number",
    "localisation": "location", "lieu": "location", "location": "location",
    "début de licence": "license_start", "debut de licence": "license_start", "license_start": "license_start",
    "fin de licence": "license_end", "license_end": "license_end",
    "notes": "notes", "note": "notes", "commentaire": "notes",
    "actif": "is_active", "active": "is_active",
}
_TEXT_FIELDS = ("vendor", "model", "serial_number", "location", "notes")
_DATE_FIELDS = ("license_start", "license_end")


def _parse_date(value):
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date) or value is None:
        return value
    try:
        return datetime.datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError:
        return datetime.date.fromisoformat(value)


def read_solution_rows(uploaded):
    """Lit un fichier .xlsx sans rien enregistrer.

    Renvoie (lignes, erreurs, fatal) : chaque ligne est (numéro, valeurs) ;
    `fatal` vaut True si le fichier est inexploitable (illisible, vide, colonnes manquantes).
    """
    from openpyxl import load_workbook

    try:
        wb = load_workbook(uploaded, read_only=True, data_only=True)
    except Exception:
        return [], [_("Fichier Excel illisible (.xlsx attendu).")], True
    rows = wb.active.iter_rows(values_only=True)
    try:
        header = [str(h).strip().lower() if h is not None else "" for h in next(rows)]
    except StopIteration:
        return [], [_("Fichier vide.")], True
    cols = {}
    for i, h in enumerate(header):
        key = HEADER_ALIASES.get(h.replace("  ", " "))
        if key and key not in cols:
            cols[key] = i
    if "name" not in cols or "category" not in cols:
        return [], [_("Colonnes requises manquantes : « nom » et « catégorie ».")], True

    parsed, errors = [], []
    for lineno, row in enumerate(rows, start=2):
        if not row or all(v is None or str(v).strip() == "" for v in row):
            continue

        def get(key):
            return row[cols[key]] if key in cols and cols[key] < len(row) else None

        name = str(get("name") or "").strip()
        category = CATEGORY_ALIASES.get(str(get("category") or "").strip().lower())
        if not name:
            errors.append(_("Ligne %(n)d : nom manquant.") % {"n": lineno})
            continue
        if not category:
            errors.append(_("Ligne %(n)d : catégorie « %(c)s » inconnue (logiciel, matériel, machine virtuelle, "
                            "cloud, autre).") % {"n": lineno, "c": get("category")})
            continue
        values = {"name": name[:200], "category": category}
        for field in _TEXT_FIELDS:
            value = get(field)
            values[field] = str(value).strip() if value is not None else ""
        try:
            for field in _DATE_FIELDS:
                value = get(field)
                if isinstance(value, str):
                    value = value.strip() or None
                values[field] = _parse_date(value)
        except ValueError:
            errors.append(_("Ligne %(n)d : date invalide « %(d)s » (JJ/MM/AAAA attendu).")
                          % {"n": lineno, "d": value})
            continue
        active = get("is_active")
        if active is not None and str(active).strip():
            values["is_active"] = str(active).strip().lower() not in ("non", "no", "false", "0", "n")
        parsed.append((lineno, values))
    return parsed, errors, False


def apply_solution_rows(rows, contract):
    """Enregistre les lignes lues : une solution de même nom sur le contrat est mise à jour."""
    from django.core.exceptions import ValidationError

    created = updated = 0
    errors = []
    for lineno, values in rows:
        sol = Solution.objects.filter(contract=contract, name=values["name"]).first()
        was_created = sol is None
        if sol is None:
            sol = Solution(contract=contract)
        for field, value in values.items():
            setattr(sol, field, value)
        try:
            sol.full_clean()
        except ValidationError as e:
            errors.append(_("Ligne %(n)d : %(msg)s") % {"n": lineno, "msg": "; ".join(e.messages)})
            continue
        sol.save()
        if was_created:
            created += 1
        else:
            updated += 1
    return created, updated, errors


def _no_add_related(form, *names):
    """Retire le bouton « + » (création d'un critère en popup) : les critères se gèrent
    dans le menu « Critères de service », pas depuis une formule ou un contrat."""
    for name in names:
        field = form.base_fields.get(name)
        if field is not None and hasattr(field.widget, "can_add_related"):
            field.widget.can_add_related = False


@admin.register(ServiceFeature)
class ServiceFeatureAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "code", "order", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name", "code", "description")
    ordering = ("category", "order", "name")


class ContractTypeForm(forms.ModelForm):
    class Meta:
        model = ContractType
        fields = "__all__"
        widgets = {
            "features": FeatureChecklist(mode="catalogue"),
        }
        labels = {
            "features": _("Critères de la formule"),
        }


@admin.register(ContractType)
class ContractTypeAdmin(admin.ModelAdmin):
    form = ContractTypeForm
    list_display = ("name", "sla", "allowance_tickets", "is_active")
    list_filter = ("sla__coverage", "is_active")
    search_fields = ("name", "description")
    # Bloc « Positionnement & Commercial » retiré de la fiche (jugé inutile) ;
    # les colonnes restent en base tant que la page contrat les affiche.
    fieldsets = (
        (None, {"fields": ("name", "description", "sla", "allowance_tickets", "is_active")}),
        (_("Critères & Prestations incluses"), {
            "fields": ("features",),
        }),
    )

    class Media:
        css = {"all": (versioned("css/admin_features.css"),)}
        js = (versioned("js/feature_checklist.js"),)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        _no_add_related(form, "features")
        return form


class CategorySelect(forms.Select):
    """Liste des catégories avec un descriptif au survol de chaque option."""

    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        hint = Solution.CATEGORY_HELP.get(str(value))
        if hint:
            option["attrs"]["title"] = str(hint)
        return option


def category_help():
    return " · ".join(f"{label} : {Solution.CATEGORY_HELP[value]}" for value, label in Solution.Category.choices)


class SolutionInline(admin.TabularInline):
    model = Solution
    extra = 0
    add_another_label = _("Ajouter une solution supplémentaire")
    # Ajoute au-dessus du tableau l'import Excel et le modèle de fichier à télécharger.
    template = "admin/contracts/contract/solution_inline.html"
    fields = ("category", "vendor", "model", "name", "serial_number", "location",
              "license_start", "license_end", "is_active")

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == "category":
            kwargs["widget"] = CategorySelect
            kwargs["help_text"] = category_help()
        return super().formfield_for_choice_field(db_field, request, **kwargs)


ENGINEER_PROFILES = (Profile.TECH_ALL, Profile.TECH_ASSIGNED)


class ContractAccessInline(admin.TabularInline):
    """Ingénieurs qui traitent le contrat. Les Engineers voient déjà tous les contrats :
    l'affectation désigne qui s'en occupe. La liste ne propose que des ingénieurs actifs."""

    model = ContractAccess
    extra = 0
    add_another_label = _("Ajouter une affectation supplémentaire")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "user":
            kwargs["queryset"] = User.objects.filter(profile__in=ENGINEER_PROFILES, is_active=True).order_by(
                "first_name", "last_name")
            kwargs["label"] = _("Ingénieur")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        # Une simple liste d'ingénieurs : pas de boutons créer / modifier / voir l'utilisateur.
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "user" and hasattr(field.widget, "can_add_related"):
            field.widget.can_add_related = field.widget.can_change_related = False
            field.widget.can_view_related = field.widget.can_delete_related = False
        return field


class ContractForm(forms.ModelForm):
    solutions_file = forms.FileField(
        label=_("Fichier Excel des solutions"), required=False,
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}),
    )

    def clean_solutions_file(self):
        """Vérifie le fichier avant tout enregistrement : en cas d'erreur, ni le contrat
        ni les solutions ne sont enregistrés, et le formulaire indique les lignes fautives."""
        uploaded = self.cleaned_data.get("solutions_file")
        self.solution_rows = []
        if not uploaded:
            return uploaded
        rows, errors, _fatal = read_solution_rows(uploaded)
        if errors:
            raise forms.ValidationError(errors)
        if not rows:
            raise forms.ValidationError(_("Le fichier ne contient aucune solution."))
        self.solution_rows = rows
        return uploaded

    class Meta:
        model = Contract
        fields = "__all__"
        widgets = {
            "extra_features": FeatureChecklist(mode="contract"),
            "excluded_features": FeatureChecklist(mode="exclusions"),
        }
        labels = {
            "extra_features": _("Critères et suppléments"),
            "excluded_features": _("Critères retirés"),
        }
        help_texts = {
            "extra_features": _("Grisés : inclus dans la formule. Cochez les suppléments à ajouter pour ce client."),
            "excluded_features": _("Exceptionnel : cochez un critère de la formule à retirer pour ce contrat."),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        client = self._selected("client", Organisation)
        contract_type = self._selected("contract_type", ContractType)

        # Clients finaux proposés : uniquement ceux rattachés à l'ESN choisie.
        if client is not None:
            qs = client.end_clients.all() if client.is_esn else Organisation.objects.none()
            if self.instance.pk:
                qs = qs | self.instance.end_clients.all()
            self.fields["end_clients"].queryset = qs.distinct()
        self._end_client_dropdown()

        # Critères : tout le catalogue actif est listé ; ceux de la formule choisie
        # sont affichés cochés et grisés (non modifiables), les autres sont les
        # suppléments cochables. Le JS met l'affichage à jour au changement de formule.
        active = ServiceFeature.objects.filter(is_active=True)
        extra_qs, excluded_qs = active, active
        if self.instance.pk:
            extra_qs = extra_qs | self.instance.extra_features.all()
            excluded_qs = excluded_qs | self.instance.excluded_features.all()
        self.fields["extra_features"].queryset = extra_qs.distinct()
        if "excluded_features" in self.fields:
            self.fields["excluded_features"].queryset = excluded_qs.distinct()
        widget = self.fields["extra_features"].widget
        widget = getattr(widget, "widget", widget)  # l'admin l'enveloppe (bouton « + »)
        widget.included = self._formula_ids(contract_type)

    def _end_client_dropdown(self):
        """Client final : une liste déroulante (un contrat = une ESN et un client final).

        Un contrat existant qui couvre déjà plusieurs clients finaux garde la liste
        multiple, pour ne rien perdre à l'enregistrement."""
        field = self.fields.get("end_clients")
        if field is None or (self.instance.pk and self.instance.end_clients.count() > 1):
            if field is not None:
                field.help_text = ""
            return
        self.fields["end_clients"] = forms.ModelChoiceField(
            queryset=field.queryset, required=False, label=_("Client final"),
            empty_label=_("— Choisissez d'abord le vendeur —"),
        )
        if self.instance.pk:
            first = self.instance.end_clients.first()
            self.initial["end_clients"] = first.pk if first else None

    def clean_end_clients(self):
        """Toujours une liste pour l'enregistrement de la relation (plusieurs à plusieurs)."""
        value = self.cleaned_data.get("end_clients")
        if value is None:
            return []
        return list(value) if hasattr(value, "__iter__") else [value]

    @staticmethod
    def _formula_ids(contract_type):
        if contract_type is None:
            return set()
        return set(contract_type.features.values_list("pk", flat=True))

    def _selected(self, name, model):
        """Objet choisi dans les données POST, ou valeur actuelle de l'instance."""
        raw = self.data.get(self.add_prefix(name)) if self.is_bound else None
        if raw:
            return model.objects.filter(pk=raw).first()
        if self.instance.pk:
            return getattr(self.instance, name)
        return None

    def clean(self):
        data = super().clean()
        client = data.get("client")
        end_clients = data.get("end_clients") or []
        if end_clients:
            if client is None or not client.is_vendor:
                self.add_error("end_clients", _("Choisissez d'abord le vendeur (ESN ou Propriétaire)."))
            else:
                allowed = set(client.end_clients.values_list("pk", flat=True))
                invalid = [e.name for e in end_clients if e.pk not in allowed]
                if invalid:
                    self.add_error("end_clients",
                                   _("Ces clients finaux ne sont pas rattachés à %(client)s : %(names)s")
                                   % {"client": client.name, "names": ", ".join(invalid)})

        formula_ids = self._formula_ids(data.get("contract_type"))
        # Un critère déjà inclus dans la formule n'est jamais enregistré comme supplément.
        if data.get("extra_features") is not None:
            data["extra_features"] = [f for f in data["extra_features"] if f.pk not in formula_ids]
        stray = [f.name for f in data.get("excluded_features") or [] if f.pk not in formula_ids]
        if stray:
            self.add_error("excluded_features",
                           _("Seuls des critères inclus dans la formule peuvent être retirés : %(names)s")
                           % {"names": ", ".join(stray)})
        return data


@admin.register(Contract)
class ContractAdmin(SuperAdminCascadeDeleteMixin, admin.ModelAdmin):
    form = ContractForm
    change_form_template = "admin/contracts/contract/change_form.html"
    list_display = ("reference", "title", "client", "channel", "contract_type", "status", "start_date", "end_date")
    list_filter = ("status", "contract_type", "contract_type__sla__coverage", "client")

    @admin.display(description=_("canal"), ordering="client__is_operator")
    def channel(self, obj):
        return _("Vente directe") if obj.is_direct else _("Via ESN")
    search_fields = ("reference", "title", "client__name")
    list_select_related = ("client", "contract_type")
    exclude = ("allowance_hours",)  # forfait d'heures : non utilisé, masqué
    fieldsets = (
        (None, {
            "fields": ("reference", "title", "client", "end_clients", "contract_type", "status", "start_date", "end_date",
                       "allowance_tickets"),
        }),
        (_("Composition du contrat"), {
            "fields": ("extra_features",),
        }),
        (_("Dérogations (exceptionnel)"), {
            "classes": ("collapse",),
            "fields": ("excluded_features",),
        }),
    )
    # « solutions_file » (champ déclaré du formulaire) n'est dans aucun bloc : il s'affiche
    # dans la zone « Solutions », au-dessus du tableau (solution_inline.html).
    inlines = [SolutionInline, ContractAccessInline]
    actions = ["notify_esn_licenses"]

    def cascade_querysets(self, objs):
        """Super Admin : un contrat (de test) part avec ses rapports puis ses tickets."""
        from reports.models import Report
        from tickets.models import Ticket
        return [Report.objects.filter(contract__in=objs), Ticket.objects.filter(contract__in=objs)]

    @admin.action(description=_("Notifier l'ESN : licences arrivant à échéance (premier seuil de rappel)"))
    def notify_esn_licenses(self, request, queryset):
        from .notifications import expiring_solutions
        _notify_esn(self, request, expiring_solutions().filter(contract__in=queryset))

    def get_readonly_fields(self, request, obj=None):
        # Référence attribuée automatiquement, jamais saisie.
        return ("reference",) if obj else ()

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if obj is None:
            # À la création, la référence n'existe pas encore : on ne l'affiche pas.
            main = dict(fieldsets[0][1])
            main["fields"] = tuple(f for f in main["fields"] if f != "reference")
            fieldsets = ((fieldsets[0][0], main), *fieldsets[1:])
        if obj is None or not obj.excluded_features.exists():
            # Les dérogations ne sont plus proposées : seul un contrat qui en porte déjà
            # garde le bloc, pour pouvoir les retirer.
            fieldsets = tuple(fs for fs in fieldsets if "excluded_features" not in fs[1]["fields"])
        return fieldsets

    def get_inline_formsets(self, request, formsets, inline_instances, obj=None):
        """Libellé du lien d'ajout de ligne : « Ajouter une solution supplémentaire » plutôt
        que le « Ajouter un objet Solution supplémentaire » générique de Django."""
        inline_formsets = super().get_inline_formsets(request, formsets, inline_instances, obj)
        for inline_formset in inline_formsets:
            label = getattr(inline_formset.opts, "add_another_label", None)
            if label:
                data = json.loads(inline_formset.inline_formset_data())
                data["options"]["addText"] = str(label)
                payload = json.dumps(data)
                inline_formset.inline_formset_data = lambda payload=payload: payload
        return inline_formsets

    def save_model(self, request, obj, form, change):
        if not obj.reference:
            obj.assign_reference()
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # Solutions du fichier Excel joint (déjà vérifié par le formulaire) : après le
        # tableau des solutions, pour qu'une ligne du fichier mette à jour une saisie manuelle.
        rows = getattr(form, "solution_rows", None)
        if not rows:
            return
        created, updated, errors = apply_solution_rows(rows, form.instance)
        self.message_user(request, _("Import Excel : %(c)d solution(s) créée(s), %(u)d mise(s) à jour.")
                          % {"c": created, "u": updated}, messages.SUCCESS)
        for error in errors:
            self.message_user(request, error, messages.WARNING)

    class Media:
        css = {"all": (versioned("css/admin_features.css"),)}
        js = (versioned("js/feature_checklist.js"), versioned("js/contract_admin.js"))

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path("modele-import-solutions.xlsx",
                 self.admin_site.admin_view(self.import_template_view), name="contracts_contract_import_template"),
            path("lire-solutions/",
                 self.admin_site.admin_view(self.read_solutions_view), name="contracts_contract_read_solutions"),
            path("<path:object_id>/import-solutions/",
                 self.admin_site.admin_view(self.import_solutions_view), name="contracts_contract_import_solutions"),
        ]
        return custom + urls

    IMPORT_COLUMNS = ("Catégorie", "Nom", "Éditeur", "Modèle", "N° de série", "Localisation",
                      "Début de licence", "Fin de licence", "Notes", "Actif")

    def import_template_view(self, request):
        """Modèle Excel prêt à remplir : colonnes reconnues par l'import, une ligne d'exemple
        et la liste des catégories acceptées."""
        import io

        from django.core.exceptions import PermissionDenied
        from django.http import HttpResponse
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        if not self.has_view_permission(request):
            raise PermissionDenied
        wb = Workbook()
        ws = wb.active
        ws.title = "Solutions"
        ws.append(self.IMPORT_COLUMNS)
        ws.append(["Matériel", "Pare-feu siège", "Fortinet", "FortiGate 100F", "FG100F0000000",
                   "Salle serveurs Plateau", "01/01/2026", "31/12/2026", "Exemple : à remplacer", "Oui"])
        header_fill = PatternFill("solid", fgColor="1F2A44")
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
        for col, width in zip("ABCDEFGHIJ", (14, 28, 18, 20, 18, 24, 16, 16, 28, 8)):
            ws.column_dimensions[col].width = width
        ws.freeze_panes = "A2"

        cats = wb.create_sheet("Catégories acceptées")
        cats.append(["Valeur à saisir", "Équivalents acceptés"])
        for value, aliases in (("Logiciel", "software"), ("Matériel", "hardware, materiel"),
                               ("Machine virtuelle", "vm, virtual machine"), ("Cloud", "saas"),
                               ("Autre", "other")):
            cats.append([value, aliases])
        for cell in cats[1]:
            cell.font = Font(bold=True)
        cats.column_dimensions["A"].width = 20
        cats.column_dimensions["B"].width = 28

        buf = io.BytesIO()
        wb.save(buf)
        response = HttpResponse(
            buf.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="modele-import-solutions.xlsx"'
        return response

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Cartes JSON pour le JS : client ESN → ses clients finaux ;
        # formule → ses critères (pour masquer ceux déjà inclus).
        esn_map = {
            str(o.pk): [e.pk for e in o.end_clients.all()]
            for o in Organisation.objects.filter(kind=Organisation.Kind.CLIENT).prefetch_related("end_clients")
        }
        formulas = list(ContractType.objects.prefetch_related("features"))
        type_map = {str(t.pk): [f.pk for f in t.features.all()] for t in formulas}
        # formule → forfait de tickets par défaut (null = illimité)
        allowance_map = {str(t.pk): t.allowance_tickets for t in formulas}
        form.base_fields["client"].widget.attrs["data-end-clients"] = json.dumps(esn_map)
        form.base_fields["contract_type"].widget.attrs["data-features"] = json.dumps(type_map)
        form.base_fields["contract_type"].widget.attrs["data-allowances"] = json.dumps(allowance_map)
        _no_add_related(form, "extra_features", "excluded_features")
        return form

    INLINE_FIELDS = ("category", "vendor", "model", "name", "serial_number", "location",
                     "license_start", "license_end", "is_active")

    def read_solutions_view(self, request):
        """Lit le fichier Excel sans rien enregistrer et renvoie les solutions en JSON :
        la fiche contrat s'en sert pour remplir le tableau des solutions avant l'enregistrement."""
        from django.core.exceptions import PermissionDenied
        from django.http import JsonResponse
        from django.utils.formats import localize_input

        if request.method != "POST":
            return JsonResponse({"ok": False, "errors": [_("Méthode non autorisée.")]}, status=405)
        if not (self.has_add_permission(request) or self.has_change_permission(request)):
            raise PermissionDenied
        uploaded = request.FILES.get("file")
        if not uploaded:
            return JsonResponse({"ok": False, "errors": [_("Aucun fichier reçu.")]}, status=400)
        if not uploaded.name.lower().endswith(".xlsx"):
            return JsonResponse({"ok": False, "errors": [_("Fichier Excel .xlsx attendu.")]}, status=400)
        rows, errors, fatal = read_solution_rows(uploaded)
        if fatal:
            return JsonResponse({"ok": False, "errors": errors}, status=400)
        out = []
        for lineno, values in rows:
            row = {"line": lineno}
            for field in self.INLINE_FIELDS:
                value = values.get(field, True if field == "is_active" else "")
                if field in _DATE_FIELDS:
                    value = localize_input(value) if value else ""
                row[field] = value
            out.append(row)
        return JsonResponse({"ok": True, "rows": out, "errors": [str(e) for e in errors]})

    def import_solutions_view(self, request, object_id):
        """Importe des solutions depuis un fichier Excel (.xlsx) pour ce contrat."""
        contract = get_object_or_404(self.get_queryset(request), pk=object_id)
        if not self.has_change_permission(request, contract):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied

        result = None
        if request.method == "POST" and request.FILES.get("file"):
            result = self._import_solutions(request.FILES["file"], contract)

        return render(request, "admin/contracts/contract/import_solutions.html", {
            "contract": contract, "opts": self.model._meta, "result": result,
            "title": _("Importer des solutions"),
        })

    def _import_solutions(self, uploaded, contract):
        """Page d'import : lit le fichier puis enregistre les lignes valides."""
        rows, errors, fatal = read_solution_rows(uploaded)
        if fatal:
            return {"ok": False, "errors": errors}
        created, updated, save_errors = apply_solution_rows(rows, contract)
        return {"ok": True, "created": created, "updated": updated, "errors": errors + save_errors}


def _notify_esn(modeladmin, request, solutions):
    """Envoie, pour chaque ESN concernée, un email listant ses licences sélectionnées."""
    from collections import defaultdict

    from .notifications import LicenseMailError, send_license_notice

    by_esn = defaultdict(list)
    for sol in solutions:
        if sol.license_end:
            by_esn[sol.contract.client].append(sol)
    if not by_esn:
        modeladmin.message_user(request, _("Aucune licence avec date de fin dans la sélection."), messages.WARNING)
        return
    for esn, sols in by_esn.items():
        try:
            recipients = send_license_notice(esn, sols, actor=request.user, manual=True)
        except LicenseMailError as e:
            modeladmin.message_user(request, _("%(esn)s : l'email à %(to)s n'a pas pu partir. Vérifiez "
                                               "Configuration > Messagerie (journal des emails).")
                                    % {"esn": esn.name, "to": ", ".join(e.recipients)}, messages.ERROR)
            continue
        if recipients:
            modeladmin.message_user(request, _("%(esn)s prévenue (%(n)d licence(s)) : %(to)s.")
                                    % {"esn": esn.name, "n": len(sols), "to": ", ".join(recipients)}, messages.SUCCESS)
        else:
            modeladmin.message_user(request, _("%(esn)s n'a aucun utilisateur actif : alerte non envoyée.")
                                    % {"esn": esn.name}, messages.ERROR)


class LicenseExpiryFilter(admin.SimpleListFilter):
    title = _("fin de licence")
    parameter_name = "licence"

    def lookups(self, request, model_admin):
        return [("expired", _("Expirée")), ("30", _("Dans 30 jours")), ("60", _("Dans 60 jours")),
                ("90", _("Dans 90 jours"))]

    def queryset(self, request, queryset):
        from django.utils import timezone
        today = timezone.localdate()
        if self.value() == "expired":
            return queryset.filter(license_end__lt=today)
        if self.value() in ("30", "60", "90"):
            return queryset.filter(license_end__gte=today,
                                   license_end__lte=today + datetime.timedelta(days=int(self.value())))
        return queryset


@admin.register(Solution)
class SolutionAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "contract", "vendor", "model", "license_end", "is_active")
    list_filter = (LicenseExpiryFilter, "category", "is_active", "contract__client")
    actions = ["notify_esn"]

    @admin.action(description=_("Notifier l'ESN de l'expiration de licence"))
    def notify_esn(self, request, queryset):
        _notify_esn(self, request, queryset.select_related("contract__client"))
    exclude = ("version",)  # champ retiré de la saisie (colonne conservée en base)
    search_fields = ("name", "vendor", "model", "serial_number", "contract__reference")
    autocomplete_fields = ("contract",)


@admin.register(LicenseAlertSettings)
class LicenseAlertSettingsAdmin(admin.ModelAdmin):
    """Fiche unique : la liste ouvre directement les paramètres."""

    fieldsets = (
        (None, {"fields": ("enabled", "last_run_display")}),
        (_("Rappels"), {"fields": ("thresholds", "unit", "schedule_preview")}),
        (_("Destinataires"), {"fields": ("notify_esn", "notify_end_client", "notify_managers")}),
        (_("Plage d'envoi"), {"fields": ("start_hour", "end_hour")}),
    )
    readonly_fields = ("last_run_display", "schedule_preview")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        from django.shortcuts import redirect
        obj = LicenseAlertSettings.get()
        return redirect("admin:contracts_licensealertsettings_change", obj.pk)

    @admin.display(description=_("Dernier passage du planificateur"))
    def last_run_display(self, obj):
        from django.utils import timezone
        from django.utils.formats import date_format
        if not obj.last_run:
            return _("Jamais : vérifiez que le service « scheduler » est démarré (docker compose ps scheduler).")
        when = date_format(timezone.localtime(obj.last_run), "d/m/Y H:i")
        stale = timezone.now() - obj.last_run > datetime.timedelta(days=1, hours=1)
        if stale:
            return _("%(d)s — plus d'un jour sans passage : le service « scheduler » est-il arrêté ?") % {"d": when}
        return when

    @admin.display(description=_("Calendrier des rappels"))
    def schedule_preview(self, obj):
        try:
            values = obj.threshold_values()
        except ValueError:
            return "—"
        unit = obj.get_unit_display()
        parts = [str(_("le jour de l'expiration")) if v == 0 else f"{v} {unit}" for v in values]
        return _("%(n)d rappel(s) : %(list)s avant la fin de licence.") % {"n": len(values), "list": ", ".join(parts)}

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        self.message_user(request, _("Paramètres enregistrés : ils s'appliquent dès le prochain passage du "
                                     "planificateur (dans l'heure)."), messages.SUCCESS)

    def response_change(self, request, obj):
        from django.shortcuts import redirect
        if "_continue" in request.POST or "_save" in request.POST:
            return redirect("admin:contracts_licensealertsettings_change", obj.pk)
        return super().response_change(request, obj)


@admin.register(LicenseNotice)
class LicenseNoticeAdmin(admin.ModelAdmin):
    list_display = ("sent_at", "solution", "license_end", "threshold", "manual", "recipients", "sent_by")
    list_filter = ("manual", "threshold")
    search_fields = ("solution__name", "solution__contract__reference", "recipients")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ContractAccess)
class ContractAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "contract", "created_at")
    search_fields = ("user__email", "contract__reference")
    autocomplete_fields = ("user", "contract")
