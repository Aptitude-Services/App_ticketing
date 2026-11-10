from django import forms
from django.db.models import Q
from django.contrib.auth.forms import AuthenticationForm
from django.utils.translation import gettext_lazy as _

from contracts.models import Contract, ContractAccess

from . import permissions
from .models import Profile, User


class LoginForm(AuthenticationForm):
    username = forms.EmailField(label=_("Adresse email"), widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}))


class UserManageForm(forms.ModelForm):
    """Création et modification d'un utilisateur, limitées aux droits de l'acteur."""

    contracts = forms.ModelMultipleChoiceField(
        label=_("Contrats autorisés"), queryset=Contract.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text=_("Utilisé si l'accès est limité, ou pour un profil « Engineer (restricted) »."),
    )

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "phone", "language", "organisation", "profile", "manager",
                  "all_contracts", "is_active"]

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        choices = [(p.value, p.label) for p in permissions.assignable_profiles(actor)]
        if self.instance.pk and self.instance.profile not in {value for value, _label in choices}:
            # Profil en réserve déjà porté par ce compte : on le garde dans la liste pour pouvoir enregistrer.
            choices.append((self.instance.profile, self.instance.get_profile_display()))
        self.fields["profile"].choices = choices
        if not self.instance.pk:
            self.fields["profile"].initial = Profile.CLIENT_RW
        orgs = permissions.manageable_organisations(actor)
        self.fields["organisation"].queryset = orgs
        if actor.profile == Profile.CLIENT_ADMIN:
            # L'admin d'une ESN crée aussi les comptes de ses clients finaux : il choisit
            # parmi son organisation et ses clients finaux. Seul dans son périmètre, le champ est figé.
            self.fields["organisation"].initial = actor.organisation
            self.fields["organisation"].disabled = orgs.count() <= 1

        # Supérieur hiérarchique : pour l'équipe Aptitude, réglé par le Super Admin.
        if actor.profile == Profile.APTITUDE_ADMIN:
            self.fields["manager"].queryset = User.objects.filter(
                is_active=True, profile__in=[Profile.APTITUDE_ADMIN, Profile.APTITUDE_MANAGER]).exclude(
                pk=self.instance.pk)
            self.fields["manager"].label = _("Supérieur hiérarchique")
            self.fields["manager"].help_text = _("Valide les rapports d'intervention de cette personne. "
                                                 "Vide : tout Manager ou Super Admin peut les valider.")
        else:
            del self.fields["manager"]

        # Contrats proposables : ceux de l'organisation cible et visibles par l'acteur
        contract_qs = permissions.visible_contracts(actor)
        target_org = self._target_org()
        if target_org is not None and not target_org.is_aptitude:
            contract_qs = contract_qs.filter(
                Q(client=target_org) | Q(end_clients=target_org)).distinct()
        self.fields["contracts"].queryset = contract_qs
        if self.instance.pk:
            self.fields["contracts"].initial = Contract.objects.filter(accesses__user=self.instance)

    def _target_org(self):
        if self.actor.profile == Profile.CLIENT_ADMIN and self.fields["organisation"].disabled:
            return self.actor.organisation
        if self.is_bound and self.data.get(self.add_prefix("organisation")):
            return self.fields["organisation"].queryset.filter(pk=self.data.get(self.add_prefix("organisation"))).first()
        if self.instance.pk:
            return self.instance.organisation
        if self.actor.profile == Profile.CLIENT_ADMIN:
            return self.actor.organisation
        return None

    def clean_email(self):
        return self.cleaned_data["email"].lower()

    def clean(self):
        data = super().clean()
        org = data.get("organisation")
        profile = data.get("profile")
        contracts = data.get("contracts") or []

        if org is not None:
            for contract in contracts:
                if not org.is_aptitude and not org.relates_to(contract):
                    raise forms.ValidationError(_("Un contrat sélectionné n'appartient pas à cette organisation."))
            if org.is_aptitude and contracts and profile != Profile.TECH_ASSIGNED:
                self.add_error("contracts", _("Seuls les profils « Engineer (restricted) » reçoivent des affectations."))

        if profile == Profile.CLIENT_ADMIN:
            data["all_contracts"] = True
        if "manager" in data and (org is None or not org.is_aptitude):
            data["manager"] = None

        # Le dernier admin client actif ne peut être ni rétrogradé, ni désactivé.
        if self.instance.pk:
            original = User.objects.get(pk=self.instance.pk)
            demoted = profile != Profile.CLIENT_ADMIN or not data.get("is_active", True)
            if demoted and permissions.is_last_client_admin(original):
                raise forms.ValidationError(_("Impossible : c'est le dernier admin actif de cette organisation."))
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        if not user.pk:
            user.set_unusable_password()
        if commit:
            user.save()
            self._save_contracts(user)
        return user

    def _save_contracts(self, user):
        wanted = set(self.cleaned_data.get("contracts") or [])
        needs_list = user.profile == Profile.TECH_ASSIGNED or (user.is_client and not user.all_contracts)
        if not needs_list:
            wanted = set()
        # On ne touche qu'aux contrats que l'acteur voit : il ne retire jamais un accès qu'il ne gère pas.
        scope = set(self.fields["contracts"].queryset)
        current = {a.contract: a for a in ContractAccess.objects.filter(user=user).select_related("contract")}
        for contract, access in current.items():
            if contract in scope and contract not in wanted:
                access.delete()
        for contract in wanted - set(current):
            ContractAccess.objects.create(user=user, contract=contract)


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone", "language", "theme"]


class TokenForm(forms.Form):
    token = forms.CharField(
        label=_("Code à 6 chiffres"), max_length=6, min_length=6,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code", "autofocus": True}),
    )
