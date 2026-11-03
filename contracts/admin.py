from django import forms
from django.contrib import admin

from .models import Contract, ContractAccess, ContractType, Solution


@admin.register(ContractType)
class ContractTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "sla", "is_active")
    list_filter = ("sla__coverage", "is_active")


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


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ("reference", "title", "client", "contract_type", "status", "start_date", "end_date")
    list_filter = ("status", "contract_type", "contract_type__sla__coverage", "client")
    search_fields = ("reference", "title", "client__name")
    list_select_related = ("client", "contract_type")
    exclude = ("allowance_hours",)  # forfait d'heures : non utilisé, masqué
    inlines = [SolutionInline, ContractAccessInline]


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
