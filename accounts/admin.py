import json

from django import forms
from django.contrib import admin
from django.contrib.admin.options import IS_POPUP_VAR, TO_FIELD_VAR
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from core.assets import versioned

from . import permissions
from .models import AuditEvent, Organisation, Profile, User, file_data_uri


class WrappedFilteredSelectMultiple(FilteredSelectMultiple):
    """Sélecteur à deux colonnes enveloppé comme ceux de l'admin : le JS de Django
    insère le sélecteur au début du conteneur ; sans enveloppe, il passerait avant le libellé."""

    def render(self, name, value, attrs=None, renderer=None):
        return format_html('<div class="related-widget-wrapper">{}</div>',
                           super().render(name, value, attrs, renderer))


class LogoInput(forms.ClearableFileInput):
    """Champ logo avec aperçu : le logo enregistré, puis celui choisi avant enregistrement (JS)."""

    def render(self, name, value, attrs=None, renderer=None):
        attrs = {**(attrs or {}), "accept": ".png,.jpg,.jpeg,.svg,.webp,.gif", "data-logo-input": "1"}
        src = file_data_uri(value) if value and hasattr(value, "open") else ""
        preview = format_html(
            '<div class="logo-preview"{}><img src="{}" alt=""></div>', "" if src else format_html(" hidden"), src)
        return format_html("{}{}", preview, super().render(name, value, attrs, renderer))


class OrganisationForm(forms.ModelForm):
    """Fiche organisation : les champs proposés dépendent du type.

    Client ESN → ses clients finaux ; client final → ses ESN ; Aptitude → ni l'un
    ni l'autre (ni secteur). Le JS masque les champs hors sujet ; côté serveur,
    un rattachement qui ne correspond pas au type est ignoré.
    """

    partner_esns = forms.ModelMultipleChoiceField(
        label=_("ESN rattachées"), required=False,
        queryset=Organisation.objects.filter(kind=Organisation.Kind.CLIENT),
        widget=WrappedFilteredSelectMultiple(_("ESN"), is_stacked=False),
    )

    class Meta:
        model = Organisation
        # Le code (HUD, BLAG…) est calculé automatiquement depuis le nom : pas de saisie.
        exclude = ["code"]
        widgets = {"logo": LogoInput, "brand_color": forms.TextInput(attrs={"type": "color"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "end_clients" in self.fields:
            # Seuls des clients finaux se rattachent à une ESN.
            self.fields["end_clients"].queryset = Organisation.objects.filter(kind=Organisation.Kind.END_CLIENT)
        if "partner_esns" in self.fields and self.instance.pk:
            self.fields["partner_esns"].initial = list(self.instance.partner_esns.values_list("pk", flat=True))
        # Formulaire épuré : pas de textes d'aide sous les champs (y compris le
        # « Maintenez appuyé Ctrl… » que l'admin ajoute aux listes multiples).
        for field in self.fields.values():
            field.help_text = ""
        if "brand_color" in self.fields:
            self.fields["brand_color"].help_text = _("Couleur des titres, bandeaux et graphiques des rapports : "
                                                     "choisissez-la d'après le logo pour garder l'identité de l'ESN.")
        if "logo" in self.fields:
            self.fields["logo"].label = _("Logo de l'ESN")
            self.fields["logo"].help_text = _("PNG, JPG ou SVG, fond transparent de préférence. "
                                              "Affiché en tête des rapports envoyés à ses clients finaux.")

    def clean(self):
        data = super().clean()
        kind = data.get("kind")
        # Les champs masqués pour ce type ne sont pas pris en compte.
        if kind != Organisation.Kind.CLIENT and "end_clients" in data:
            data["end_clients"] = Organisation.objects.none()
        if kind != Organisation.Kind.END_CLIENT and "partner_esns" in data:
            data["partner_esns"] = Organisation.objects.none()
        # Le secteur d'activité ne concerne que le client final.
        if kind != Organisation.Kind.END_CLIENT:
            data["activity_sector"] = ""
        # Couleur vide (champ masqué ou effacé) : la couleur neutre par défaut.
        if not data.get("brand_color"):
            data["brand_color"] = Organisation._meta.get_field("brand_color").default
        # Le logo ne concerne que l'ESN (il figure sur les rapports de ses clients finaux).
        if kind != Organisation.Kind.CLIENT and "logo" in data:
            data["logo"] = False if self.instance.logo else None
        return data

    def save_partner_esns(self, organisation):
        """À appeler après l'enregistrement : rattache le client final à ses ESN."""
        if "partner_esns" in self.cleaned_data:
            organisation.partner_esns.set(self.cleaned_data["partner_esns"])


class EndClientForm(forms.ModelForm):
    """Formulaire minimal de création d'un client final depuis la fiche d'une ESN."""

    class Meta:
        model = Organisation
        fields = ["name", "activity_sector", "email_domains"]


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    form = OrganisationForm
    change_form_template = "admin/accounts/organisation/change_form.html"
    list_display = ("logo_thumb", "name", "code", "kind", "sector", "nb_end_clients", "is_active", "email_domains")
    list_display_links = ("logo_thumb", "name")
    list_filter = ("kind", "activity_sector", "is_active")
    search_fields = ("name", "email_domains")
    filter_horizontal = ("end_clients",)
    fields = ("name", "kind", "activity_sector", "logo", "brand_color", "end_clients", "partner_esns", "is_active", "email_domains")

    class Media:
        css = {"all": (versioned("css/admin_features.css"),)}
        js = (versioned("js/organisation_admin.js"), versioned("js/organisation_tree.js"))

    # Vue par ESN : sans recherche ni filtre de type / secteur, les clients finaux rattachés
    # à une ESN ne sont pas listés au premier niveau ; ils se déplient sous leur ESN.
    TREE_BREAKING_PARAMS = ("q", "kind__exact", "activity_sector__exact")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _nb_end_clients=Count("end_clients", distinct=True),
            _nb_esns=Count("partner_esns", distinct=True),
        )

    @classmethod
    def _tree_view(cls, request):
        return not any(request.GET.get(p) for p in cls.TREE_BREAKING_PARAMS)

    def changelist_view(self, request, extra_context=None):
        request._org_tree = self._tree_view(request)
        return super().changelist_view(request, extra_context)

    def get_changelist_instance(self, request):
        cl = super().get_changelist_instance(request)
        if getattr(request, "_org_tree", False):
            linked = Organisation.objects.filter(kind=Organisation.Kind.END_CLIENT, partner_esns__isnull=False)
            cl.queryset = cl.queryset.exclude(pk__in=linked.values("pk"))
            cl.get_results(request)  # recompte et repagine sur la liste réduite
        return cl

    @staticmethod
    def _is_end_client_popup(request):
        """Fenêtre ouverte par le « + » du champ « Clients finaux » d'une ESN."""
        def has(var):
            return var in request.GET or var in request.POST
        return has(IS_POPUP_VAR) and has(TO_FIELD_VAR)

    def get_fields(self, request, obj=None):
        fields = list(super().get_fields(request, obj))
        if self._is_end_client_popup(request):
            # L'ESN d'origine reçoit le nouveau client : pas de rattachements ici.
            fields = [f for f in fields if f not in ("end_clients", "partner_esns", "logo", "brand_color")]
        return fields

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if self._is_end_client_popup(request):
            # Champ déclaré sur le formulaire : Django le garde même hors de `fields`.
            form.base_fields.pop("partner_esns", None)
            if "kind" in form.base_fields:
                end = Organisation.Kind.END_CLIENT
                form.base_fields["kind"].choices = [(end.value, end.label)]
                form.base_fields["kind"].initial = end
        return form

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        # Bouton « + » du champ « clients finaux » (création d'une ESN) :
        # la fiche ouverte en popup est préréglée en client final.
        if request.GET.get("_popup") and request.GET.get("_to_field") is not None and "kind" not in initial:
            initial["kind"] = Organisation.Kind.END_CLIENT
        return initial

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if hasattr(form, "save_partner_esns"):
            form.save_partner_esns(form.instance)

    @admin.display(description=_("logo"))
    def logo_thumb(self, obj):
        src = obj.logo_data_uri() if obj.is_esn else ""
        return format_html('<img src="{}" alt="" class="org-logo-thumb">', src) if src else ""

    @admin.display(description=_("secteur d'activité"), ordering="activity_sector")
    def sector(self, obj):
        return obj.get_activity_sector_display() or "—"

    @admin.display(description=_("clients finaux"), ordering="_nb_end_clients")
    def nb_end_clients(self, obj):
        if obj.kind == Organisation.Kind.END_CLIENT:
            return "—" if obj._nb_esns else format_html('<span class="org-no-esn">{}</span>', _("sans ESN"))
        if not obj._nb_end_clients:
            return obj._nb_end_clients
        children = [{
            "name": c.name, "code": c.code, "kind": c.get_kind_display(), "sector": c.get_activity_sector_display(),
            "active": c.is_active, "domains": c.email_domains,
            "url": reverse("admin:accounts_organisation_change", args=[c.pk]),
        } for c in obj.end_clients.order_by("name")]
        return format_html(
            '<button type="button" class="org-toggle" aria-expanded="false" data-children="{}" '
            'title="{}">▸ {}</button>',
            json.dumps(children), _("Afficher les clients finaux"), obj._nb_end_clients)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path("<path:object_id>/clients-finaux/nouveau/",
                 self.admin_site.admin_view(self.add_end_client_view), name="accounts_organisation_add_end_client"),
        ]
        return custom + urls

    def add_end_client_view(self, request, object_id):
        """Crée un client final et le rattache directement à cette ESN."""
        esn = get_object_or_404(self.get_queryset(request), pk=object_id)
        if not self.has_change_permission(request, esn):
            raise PermissionDenied
        if not esn.is_esn:
            self.message_user(request, _("Seule une ESN peut avoir des clients finaux."), level="error")
            return redirect("admin:accounts_organisation_changelist")

        if request.method == "POST":
            form = EndClientForm(request.POST)
            if form.is_valid():
                end = form.save(commit=False)
                end.kind = Organisation.Kind.END_CLIENT
                end.save()
                esn.end_clients.add(end)
                self.log_addition(request, end, _('"%(name)s" rattaché à %(esn)s')
                                  % {"name": end.name, "esn": esn.name})
                self.message_user(request, _("Client final « %(name)s » créé et rattaché à %(esn)s.")
                                  % {"name": end.name, "esn": esn.name})
                return redirect("admin:accounts_organisation_change", esn.pk)
        else:
            form = EndClientForm()
        return render(request, "admin/accounts/organisation/add_end_client.html", {
            "form": form, "esn": esn, "opts": self.model._meta, "title": _("Nouveau client final"),
        })


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("organisation__name", "email")
    list_display = ("email", "get_full_name", "organisation", "profile", "is_active", "last_login")
    list_filter = ("profile", "is_active", "organisation__kind", "organisation")
    search_fields = ("email", "first_name", "last_name", "organisation__name")
    readonly_fields = ("last_login", "date_joined")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Identité"), {"fields": ("first_name", "last_name", "job_title", "phone", "language")}),
        (_("Rattachement et droits"), {"fields": ("organisation", "profile", "manager", "all_contracts", "is_active")}),
        (_("Dates"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "organisation", "profile", "password1", "password2")}),
    )
    filter_horizontal = ()

    # Même périmètre que la gestion des comptes dans l'application (accounts.permissions) :
    # un Manager ne voit, ne crée et ne modifie que des comptes clients, avec des profils clients.
    # Sans cela, il pourrait se donner le profil Super Admin ou changer le mot de passe d'un
    # compte Aptitude depuis l'administration. Le Super Admin garde l'accès complet.

    def get_queryset(self, request):
        return super().get_queryset(request).filter(pk__in=permissions.manageable_users(request.user).values("pk"))

    def _in_scope(self, request, obj):
        return obj is None or permissions.manageable_users(request.user).filter(pk=obj.pk).exists()

    def has_change_permission(self, request, obj=None):
        return self._in_scope(request, obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self._in_scope(request, obj) and super().has_delete_permission(request, obj)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        allowed = {p.value for p in permissions.assignable_profiles(request.user)}
        field = form.base_fields.get("profile")
        if field:
            # Profils attribuables par l'acteur (profils en réserve exclus), plus celui que porte
            # déjà le compte modifié.
            keep = {obj.profile} if obj else set()
            field.choices = [c for c in field.choices if c[0] in allowed or c[0] in keep or c[0] == ""]
        org = form.base_fields.get("organisation")
        if org:
            org.queryset = permissions.manageable_organisations(request.user)
        manager = form.base_fields.get("manager")
        if manager and request.user.profile != Profile.APTITUDE_ADMIN:
            manager.disabled = True  # rattachement hiérarchique de l'équipe interne : Super Admin seul
        return form


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor", "target_user", "organisation", "ip_address")
    list_filter = ("action", "organisation")
    search_fields = ("actor__email", "target_user__email", "ip_address")
    date_hierarchy = "created_at"

    # Journal en lecture seule : on ne modifie ni ne supprime l'audit.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# Les droits viennent du profil de chaque utilisateur (User.has_perm) : les groupes et
# permissions « à la carte » de Django ne sont jamais lus. La page « Groupes » est retirée
# pour ne pas laisser croire qu'un groupe donne ou retire des droits.
if admin.site.is_registered(Group):
    admin.site.unregister(Group)
