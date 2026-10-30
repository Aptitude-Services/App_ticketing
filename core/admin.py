from django.contrib import admin

from .models import OutgoingMail


@admin.register(OutgoingMail)
class OutgoingMailAdmin(admin.ModelAdmin):
    """Journal en lecture seule ; la configuration se fait dans Configuration > Messagerie."""

    list_display = ("created_at", "status", "provider", "recipients", "subject")
    list_filter = ("status", "provider")
    search_fields = ("recipients", "subject")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
