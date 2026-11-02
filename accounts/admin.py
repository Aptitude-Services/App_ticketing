from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import AuditEvent, Organisation, User


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "client_type", "is_active", "email_domains")
    list_filter = ("kind", "client_type", "is_active")
    fields = ("name", "kind", "client_type", "email_domains", "is_active")
    search_fields = ("name", "email_domains")


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
