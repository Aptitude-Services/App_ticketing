from django.contrib import admin

from .models import Contract, ContractAccess, ContractType, Solution


@admin.register(ContractType)
class ContractTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "sla", "is_active")
    list_filter = ("sla__coverage", "is_active")


class SolutionInline(admin.TabularInline):
    model = Solution
    extra = 0
    fields = ("category", "name", "vendor", "serial_or_version", "location", "is_active")


class ContractAccessInline(admin.TabularInline):
    model = ContractAccess
    extra = 0
    autocomplete_fields = ("user",)


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ("reference", "title", "client", "contract_type", "status", "start_date", "end_date")
    list_filter = ("status", "contract_type", "contract_type__sla__coverage", "client")
    search_fields = ("reference", "title", "client__name")
    list_select_related = ("client", "contract_type")
    inlines = [SolutionInline, ContractAccessInline]


@admin.register(Solution)
class SolutionAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "contract", "vendor", "serial_or_version", "is_active")
    list_filter = ("category", "is_active", "contract__client")
    search_fields = ("name", "serial_or_version", "contract__reference")
    autocomplete_fields = ("contract",)


@admin.register(ContractAccess)
class ContractAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "contract", "created_at")
    search_fields = ("user__email", "contract__reference")
    autocomplete_fields = ("user", "contract")
