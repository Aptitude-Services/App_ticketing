from django.contrib import admin

from .models import SLA, Holiday, SLATarget


class SLATargetInline(admin.TabularInline):
    model = SLATarget
    extra = 0
    max_num = 4


@admin.register(SLA)
class SLAAdmin(admin.ModelAdmin):
    list_display = ("name", "coverage", "day_start", "day_end", "working_days")
    list_filter = ("coverage",)
    inlines = [SLATargetInline]


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name", "kind")
    list_filter = ("kind",)
    date_hierarchy = "date"
    search_fields = ("name",)
