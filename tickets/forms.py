from django import forms
from django.utils.translation import gettext_lazy as _

from contracts.models import Solution
from sla.models import Priority

from . import services as S


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class CreationPrioritySelect(forms.Select):
    """P1 et P2 affichés mais grisés : on ne les atteint que par escalade, avec justification."""

    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        if str(value) in {str(p) for p in S.ESCALATION_ONLY_PRIORITIES}:
            option["attrs"]["disabled"] = True
        return option


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(d, initial) for d in data if d]
        return [single(data, initial)] if data else []


class TicketCreateForm(forms.Form):
    contract = forms.ModelChoiceField(label=_("Contrat"), queryset=None, empty_label=_("Choisir un contrat"))
    solutions = forms.ModelMultipleChoiceField(label=_("Solutions concernées"), queryset=Solution.objects.none(),
                                               required=False, widget=forms.CheckboxSelectMultiple)
    title = forms.CharField(label=_("Objet"), max_length=200,
                            widget=forms.TextInput(attrs={"placeholder": _("Ex. : le VPN de l'agence ne se connecte plus")}))
    description = forms.CharField(label=_("Description"), widget=forms.Textarea(attrs={"rows": 6}),
                                  help_text=_("Ce qui se passe, depuis quand, ce qui est impacté, ce que vous avez déjà essayé."))
    priority = forms.TypedChoiceField(label=_("Priorité"), coerce=int, initial=Priority.P4,
                                      choices=Priority.choices, widget=CreationPrioritySelect)
    requester = forms.ModelChoiceField(label=_("Pour le compte de"), queryset=None, required=False,
                                       help_text=_("Laisser vide si vous êtes le demandeur."))
    files = MultipleFileField(label=_("Pièces jointes"), required=False,
                              help_text=_("10 Mo maximum par fichier : captures, journaux, PDF, documents Office."))

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        contracts = S.writable_contracts(actor).select_related("client", "contract_type__sla")
        self.fields["contract"].queryset = contracts
        self.fields["contract"].label_from_instance = (
            (lambda c: f"{c.client} — {c.title} ({c.reference})") if actor.is_aptitude else (lambda c: f"{c.title} ({c.reference})"))
        self.fields["solutions"].queryset = Solution.objects.filter(contract__in=contracts, is_active=True)
        if actor.is_aptitude:
            from accounts.models import User
            self.fields["requester"].queryset = User.objects.filter(
                is_active=True, organisation__contracts__in=contracts).distinct().order_by("organisation__name", "last_name")
            self.fields["requester"].label_from_instance = lambda u: f"{u.display_name} ({u.organisation})"
        else:
            del self.fields["requester"]
        if contracts.count() == 1:
            self.fields["contract"].initial = contracts.first()

    def clean_priority(self):
        priority = self.cleaned_data["priority"]
        if priority in S.ESCALATION_ONLY_PRIORITIES:
            raise forms.ValidationError(_("Un ticket s'ouvre en P4 ou en P3. P2 et P1 se décident ensuite, par escalade."))
        return priority

    def clean(self):
        data = super().clean()
        contract, solutions = data.get("contract"), data.get("solutions") or []
        if contract and any(s.contract_id != contract.pk for s in solutions):
            self.add_error("solutions", _("Choisissez uniquement des solutions du contrat sélectionné."))
        requester = data.get("requester")
        if contract and requester and requester.is_client and not requester.organisation.relates_to(contract):
            self.add_error("requester", _("Ce demandeur n'appartient pas au client du contrat."))
        return data


class CommentForm(forms.Form):
    body = forms.CharField(label=_("Message"), required=False, widget=forms.Textarea(attrs={"rows": 4}))
    internal = forms.BooleanField(label=_("Note interne (invisible du client)"), required=False)
    files = MultipleFileField(label=_("Joindre des fichiers"), required=False)

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        if not actor.is_aptitude:
            del self.fields["internal"]
