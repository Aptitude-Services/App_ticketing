import json

from django import forms
from django.contrib import admin
from django.shortcuts import get_object_or_404, render
from django.urls import path
from django.utils.translation import gettext_lazy as _

from accounts.models import Organisation
from .models import Contract, ContractAccess, ContractType, ServiceFeature, Solution
from .widgets import FeatureChecklist


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
            "description": _(
                "Activez les critères compris dans cette formule. Dans chaque contrat qui l'utilise, ils "
                "apparaîtront « Inclus » et les autres seront proposés en suppléments."
            ),
        }),
    )

    class Media:
        css = {"all": ("css/admin_features.css",)}
        js = ("js/feature_checklist.js",)

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
    fields = ("category", "vendor", "model", "version", "name", "serial_number", "location",
              "license_start", "license_end", "is_active")

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == "category":
            kwargs["widget"] = CategorySelect
            kwargs["help_text"] = category_help()
        return super().formfield_for_choice_field(db_field, request, **kwargs)


class ContractAccessInline(admin.TabularInline):
    model = ContractAccess
    extra = 0
    autocomplete_fields = ("user",)


class ContractForm(forms.ModelForm):
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

        # Critères : tout le catalogue actif est listé ; ceux de la formule choisie
        # sont affichés cochés et grisés (non modifiables), les autres sont les
        # suppléments cochables. Le JS met l'affichage à jour au changement de formule.
        active = ServiceFeature.objects.filter(is_active=True)
        extra_qs, excluded_qs = active, active
        if self.instance.pk:
            extra_qs = extra_qs | self.instance.extra_features.all()
            excluded_qs = excluded_qs | self.instance.excluded_features.all()
        self.fields["extra_features"].queryset = extra_qs.distinct()
        self.fields["excluded_features"].queryset = excluded_qs.distinct()
        widget = self.fields["extra_features"].widget
        widget = getattr(widget, "widget", widget)  # l'admin l'enveloppe (bouton « + »)
        widget.included = self._formula_ids(contract_type)

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
            if client is None or not client.is_esn:
                self.add_error("end_clients", _("Choisissez d'abord une organisation de type « Client ESN »."))
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
class ContractAdmin(admin.ModelAdmin):
    form = ContractForm
    change_form_template = "admin/contracts/contract/change_form.html"
    list_display = ("reference", "title", "client", "contract_type", "status", "start_date", "end_date")
    list_filter = ("status", "contract_type", "contract_type__sla__coverage", "client")
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
            "description": _(
                "Les critères de la formule choisie sont marqués « Inclus ». Activez les suppléments "
                "propres à ce client (ex. Support N3 expert sur une formule BRONZE), sans modifier la formule."
            ),
        }),
        (_("Dérogations (exceptionnel)"), {
            "classes": ("collapse",),
            "fields": ("excluded_features",),
            "description": _("Retirer pour ce contrat un critère normalement inclus dans la formule."),
        }),
    )
    inlines = [SolutionInline, ContractAccessInline]

    class Media:
        css = {"all": ("css/admin_features.css",)}
        js = ("js/feature_checklist.js", "js/contract_admin.js")

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path("<path:object_id>/import-solutions/",
                 self.admin_site.admin_view(self.import_solutions_view), name="contracts_contract_import_solutions"),
        ]
        return custom + urls

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
        "version": "version", "nom": "name", "name": "name",
        "n° de série": "serial_number", "n de série": "serial_number", "numero de serie": "serial_number",
        "serial": "serial_number", "serial_number": "serial_number",
        "localisation": "location", "lieu": "location", "location": "location",
        "début de licence": "license_start", "debut de licence": "license_start", "license_start": "license_start",
        "fin de licence": "license_end", "license_end": "license_end",
        "notes": "notes", "note": "notes", "commentaire": "notes",
        "actif": "is_active", "active": "is_active",
    }

    def _import_solutions(self, uploaded, contract):
        import datetime
        from django.core.exceptions import ValidationError
        from openpyxl import load_workbook

        try:
            wb = load_workbook(uploaded, read_only=True, data_only=True)
        except Exception:
            return {"ok": False, "errors": [_("Fichier Excel illisible (.xlsx attendu).")]}
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        try:
            header = [str(h).strip().lower() if h is not None else "" for h in next(rows)]
        except StopIteration:
            return {"ok": False, "errors": [_("Fichier vide.")]}
        cols = {}
        for i, h in enumerate(header):
            key = self.HEADER_ALIASES.get(h.replace("  ", " "))
            if key and key not in cols:
                cols[key] = i
        if "name" not in cols or "category" not in cols:
            return {"ok": False, "errors": [_("Colonnes requises manquantes : « nom » et « catégorie ».")]}

        created = updated = 0
        errors = []
        for lineno, row in enumerate(rows, start=2):
            if not row or all(v is None or str(v).strip() == "" for v in row):
                continue
            get = lambda k: (row[cols[k]] if k in cols and cols[k] < len(row) else None)  # noqa: E731
            name = str(get("name") or "").strip()
            category = self.CATEGORY_ALIASES.get(str(get("category") or "").strip().lower())
            if not name:
                errors.append(_("Ligne %(n)d : nom manquant.") % {"n": lineno})
                continue
            if not category:
                errors.append(_("Ligne %(n)d : catégorie « %(c)s » inconnue (software, hardware, vm, cloud, other).")
                              % {"n": lineno, "c": get("category")})
                continue
            name = name[:200]
            sol = Solution.objects.filter(contract=contract, name=name).first()
            was_created = sol is None
            if sol is None:
                sol = Solution(contract=contract, name=name)
            sol.category = category
            row_failed = False
            for field, key in (("vendor", "vendor"), ("model", "model"), ("version", "version"),
                               ("serial_number", "serial_number"), ("location", "location"),
                               ("license_start", "license_start"), ("license_end", "license_end"),
                               ("notes", "notes")):
                value = get(key)
                if isinstance(value, datetime.datetime):
                    value = value.date()
                elif isinstance(value, str):
                    value = value.strip() or None
                if field in ("license_start", "license_end") and isinstance(value, str):
                    try:
                        value = datetime.datetime.strptime(value, "%d/%m/%Y").date()
                    except ValueError:
                        try:
                            value = datetime.date.fromisoformat(value)
                        except ValueError:
                            errors.append(_("Ligne %(n)d : date invalide « %(d)s ».") % {"n": lineno, "d": value})
                            row_failed = True
                            break
                if value is None:
                    setattr(sol, field, None if field in ("license_start", "license_end") else "")
                else:
                    setattr(sol, field, value)
            if row_failed:
                continue
            active = get("is_active")
            if active is not None:
                sol.is_active = str(active).strip().lower() not in ("non", "no", "false", "0", "n")
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
        return {"ok": True, "created": created, "updated": updated, "errors": errors}


@admin.register(Solution)
class SolutionAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "contract", "vendor", "model", "version", "license_end", "is_active")
    list_filter = ("category", "is_active", "contract__client")
    search_fields = ("name", "vendor", "model", "serial_number", "contract__reference")
    autocomplete_fields = ("contract",)


@admin.register(ContractAccess)
class ContractAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "contract", "created_at")
    search_fields = ("user__email", "contract__reference")
    autocomplete_fields = ("user", "contract")
