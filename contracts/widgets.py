"""Sélecteur de critères de service : cartes par catégorie, interrupteurs, résumé."""
from django import forms


class FeatureChecklist(forms.CheckboxSelectMultiple):
    """Critères groupés par catégorie, un interrupteur par critère.

    `included` : identifiants des critères déjà inclus dans la formule. Ils sont
    affichés avec un badge « Inclus » et leur case reste cochée et désactivée
    (non modifiable, et non envoyée par le navigateur).
    `mode` : « catalogue » (formule), « contract » (suppléments) ou
    « exclusions » (critères retirés) — adapte le résumé affiché.
    """

    template_name = "contracts/widgets/feature_checklist.html"
    option_template_name = "contracts/widgets/feature_checklist_option.html"

    def __init__(self, attrs=None, choices=(), included=(), mode="catalogue"):
        super().__init__(attrs, choices)
        self.included = set(included)
        self.mode = mode

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["mode"] = self.mode
        return context

    def optgroups(self, name, value, attrs=None):
        selected_values = {str(v) for v in value}
        groups = {}
        for index, (option_value, option_label) in enumerate(self.choices):
            if option_value in (None, ""):
                continue
            instance = getattr(option_value, "instance", None)
            pk = getattr(option_value, "value", option_value)
            included = pk in self.included
            option = self.create_option(name, option_value, option_label,
                                        included or str(pk) in selected_values, index, attrs=attrs)
            option["attrs"]["role"] = "switch"
            if included:
                option["attrs"]["disabled"] = True
            option["included"] = included
            option["label"] = instance.name if instance is not None else option_label
            option["description"] = instance.description if instance is not None else ""
            category = instance.get_category_display() if instance is not None else ""
            groups.setdefault(category, []).append(option)
        return [(category, options, i) for i, (category, options) in enumerate(groups.items())]
