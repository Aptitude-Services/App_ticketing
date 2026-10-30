from django.contrib import admin

from .models import Attachment, Comment, Event, Ticket


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    fields = ("created_at", "author", "is_internal", "body")
    readonly_fields = fields
    can_delete = False


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("reference", "title", "contract", "priority", "status", "assignee", "created_at", "out_of_coverage")
    list_filter = ("status", "priority", "out_of_coverage", "contract__client")
    search_fields = ("reference", "title", "description")
    readonly_fields = ("reference", "created_at", "acknowledged_at", "resolved_at", "closed_at", "response_due",
                       "resolution_due", "response_breached", "resolution_breached", "paused_at", "paused_remaining")
    inlines = [CommentInline]

    # Les tickets se modifient par l'application (règles SLA et historique) : lecture seule ici.
    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "ticket", "kind", "actor", "is_internal")
    list_filter = ("kind",)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Attachment)
