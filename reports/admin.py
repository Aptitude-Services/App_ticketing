from django.contrib import admin

from .models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    """Consultation des rapports ; la rédaction et la validation se font dans l'application."""

    list_display = ("reference", "kind", "status", "contract", "end_client", "author", "validator", "created_at")
    list_filter = ("kind", "status", "contract__client")
    search_fields = ("reference", "title", "contract__reference", "contract__client__name", "end_client__name")
    readonly_fields = [f.name for f in Report._meta.fields]

    def has_add_permission(self, request):
        return False
