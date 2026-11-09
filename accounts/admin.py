from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path
from django.utils.translation import gettext_lazy as _

from .models import STANDBY_PROFILES, AuditEvent, Organisation, Profile, User


class OrganisationForm(forms.ModelForm):
    class Meta:
        model = Organisation
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "end_clients" in self.fields:
            # Seuls des clients finaux se rattachent à une ESN.
            self.fields["end_clients"].queryset = Organisation.objects.filter(kind=Organisation.Kind.END_CLIENT)

    def clean(self):
        data = super().clean()
        if data.get("end_clients") and data.get("kind") != Organisation.Kind.CLIENT:
            self.add_error("end_clients", _("Seul un « Client ESN » peut avoir des clients finaux."))
        return data


class EndClientForm(forms.ModelForm):
    """Formulaire minimal de création d'un client final depuis la fiche d'une ESN."""

    class Meta:
        model = Organisation
        fields = ["name", "activity_sector", "email_domains"]


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    form = OrganisationForm
    change_form_template = "admin/accounts/organisation/change_form.html"
    list_display = ("name", "kind", "sector", "nb_end_clients", "is_active", "email_domains")
    list_filter = ("kind", "activity_sector", "is_active")
    search_fields = ("name", "email_domains")
    filter_horizontal = ("end_clients",)

    class Media:
        css = {"all": ("css/admin_features.css",)}

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_nb_end_clients=Count("end_clients"))

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        # Bouton « + » du champ « clients finaux » (création d'une ESN) :
        # la fiche ouverte en popup est préréglée en client final.
        if request.GET.get("_popup") and request.GET.get("_to_field") is not None and "kind" not in initial:
            initial["kind"] = Organisation.Kind.END_CLIENT
        return initial

    @admin.display(description=_("secteur d'activité"), ordering="activity_sector")
    def sector(self, obj):
        return obj.get_activity_sector_display() or "—"

    @admin.display(description=_("clients finaux"), ordering="_nb_end_clients")
    def nb_end_clients(self, obj):
        return obj._nb_end_clients

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
        (_("Identité"), {"fields": ("first_name", "last_name", "phone", "language")}),
        (_("Rattachement et droits"), {"fields": ("organisation", "profile", "all_contracts", "is_active")}),
        (_("Dates"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "organisation", "profile", "password1", "password2")}),
    )
    filter_horizontal = ()

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        field = form.base_fields.get("profile")
        if field:
            # Profils en réserve masqués, sauf celui que porte déjà le compte modifié.
            keep = {obj.profile} if obj else set()
            field.choices = [c for c in field.choices if c[0] not in STANDBY_PROFILES or c[0] in keep]
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
