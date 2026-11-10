from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from core.assets import versioned

from .models import SLA, Holiday, SLATarget

# Valeurs stockées : 0 = lundi … 6 = dimanche (convention Python utilisée par le moteur SLA).
WEEKDAYS = [
    ("0", _("Lundi")), ("1", _("Mardi")), ("2", _("Mercredi")), ("3", _("Jeudi")),
    ("4", _("Vendredi")), ("5", _("Samedi")), ("6", _("Dimanche")),
]
SHORT_DAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
MAX_WORKING_DAYS = 5  # 8x5 : 5 jours ouvrés au plus (même limite dans static/js/sla_admin.js)


class SLAForm(forms.ModelForm):
    working_days = forms.MultipleChoiceField(
        label=_("Jours ouvrés"), choices=WEEKDAYS, required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = SLA
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial["working_days"] = [str(d) for d in sorted(self.instance.weekdays())]

    def clean_working_days(self):
        return ",".join(sorted(self.cleaned_data["working_days"]))

    def clean(self):
        data = super().clean()
        if data.get("coverage") == SLA.Coverage.H24X7:
            # En 24x7 les jours ouvrés ne servent pas : valeur par défaut, champ masqué à l'écran.
            data["working_days"] = "0,1,2,3,4"
        elif not data.get("working_days"):
            self.add_error("working_days", _("Cochez au moins un jour ouvré."))
        elif len(data["working_days"].split(",")) > MAX_WORKING_DAYS:
            self.add_error("working_days", _("En 8x5, cochez 5 jours ouvrés au plus."))
        return data


class SLATargetInline(admin.TabularInline):
    model = SLATarget
    extra = 0
    max_num = 4
    fields = ("priority", "reply_minutes", "response_minutes", "resolution_minutes")


@admin.register(SLA)
class SLAAdmin(admin.ModelAdmin):
    form = SLAForm
    list_display = ("name", "coverage", "horaires", "jours")
    list_filter = ("coverage",)
    inlines = [SLATargetInline]
    fieldsets = (
        (None, {"fields": ("name", "coverage")}),
        (_("Horaires ouvrés (8x5 uniquement)"), {
            "fields": ("day_start", "day_end", "working_days"),
            "classes": ("apt-8x5",),
        }),
    )

    class Media:
        js = (versioned("js/sla_admin.js"),)

    @admin.display(description=_("horaires"))
    def horaires(self, obj):
        return "24 h / 24" if obj.is_24x7 else f"{obj.day_start:%H:%M} – {obj.day_end:%H:%M}"

    @admin.display(description=_("jours ouvrés"))
    def jours(self, obj):
        if obj.is_24x7:
            return _("7 j / 7")
        return ", ".join(SHORT_DAYS[d] for d in sorted(obj.weekdays()))


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name", "kind")
    list_filter = ("kind",)
    date_hierarchy = "date"
    search_fields = ("name",)
