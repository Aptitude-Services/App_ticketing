"""Création d'un contrat dans l'administration avec des accès contrats dans le même écran."""
import datetime

import pytest
from django.core.exceptions import ValidationError
from django.contrib.admin.sites import site

from accounts.models import Organisation, Profile, User
from contracts.models import Contract, ContractAccess, ContractType, Solution

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(rf):
    apt = Organisation.objects.create(name="Aptitude Services", kind=Organisation.Kind.APTITUDE)
    sector = Organisation.ActivitySector.OTHER
    client = Organisation.objects.create(name="HUDSON", kind=Organisation.Kind.CLIENT, activity_sector=sector)
    other = Organisation.objects.create(name="Autre", kind=Organisation.Kind.CLIENT, activity_sector=sector)
    admin_user = User.objects.create_superuser("admin@aptitudes.net", "x" * 12)
    users = {
        "admin": admin_user,
        "engineer": User.objects.create_user("ing@aptitudes.net", organisation=apt, profile=Profile.TECH_ASSIGNED),
        "client": User.objects.create_user("rw@hudson.ci", organisation=client, profile=Profile.CLIENT_RW),
        "stranger": User.objects.create_user("rw@autre.ci", organisation=other, profile=Profile.CLIENT_RW),
    }
    request = rf.post("/")
    request.user = admin_user
    return client, users, request


def _post(client, user):
    """Données du formulaire d'ajout de contrat, avec une ligne d'accès pour `user`."""
    return {
        "reference": "HUD-001", "title": "Réseau HUDSON", "client": client.pk,
        "contract_type": ContractType.objects.get(name="Standard 8x5").pk,
        "status": Contract.Status.ACTIVE, "start_date": datetime.date(2026, 11, 1),
        "solutions-TOTAL_FORMS": "0", "solutions-INITIAL_FORMS": "0",
        "accesses-TOTAL_FORMS": "1", "accesses-INITIAL_FORMS": "0",
        "accesses-0-user": user.pk,
    }


def _validate(request, data):
    """Reproduit la validation de l'écran d'ajout : contrat + lignes d'accès."""
    admin = site._registry[Contract]
    form = admin.get_form(request)(data)
    assert form.is_valid(), form.errors
    contract = form.save(commit=False)
    formset_class = next(f for f in admin.get_formsets_with_inlines(request) if f[1].model is ContractAccess)[0]
    formset = formset_class(data, instance=contract, prefix="accesses")
    return contract, formset


@pytest.mark.parametrize("who", ["admin", "stranger"])
def test_forbidden_access_is_a_form_error_not_a_crash(setup, who):
    client, users, request = setup
    contract, formset = _validate(request, _post(client, users[who]))
    assert not formset.is_valid()
    assert formset.errors[0] or formset.non_form_errors()


def test_extra_features_exclude_formula_criteria(setup):
    """Les critères déjà inclus dans la formule ne sont pas reproposés en options."""
    _client, _users, request = setup
    admin = site._registry[Contract]
    contract_type = ContractType.objects.get(name="STARTER")
    form = admin.get_form(request)({"contract_type": contract_type.pk})
    base_ids = set(contract_type.features.values_list("pk", flat=True))
    proposed = set(form.fields["extra_features"].queryset.values_list("pk", flat=True))
    assert base_ids and not (base_ids & proposed)


def test_end_clients_queryset_limited_to_esn(setup):
    """Le formulaire contrat ne propose que les clients finaux de l'ESN choisie."""
    client, _users, request = setup
    from accounts.models import Organisation
    end = Organisation.objects.create(name="Client final HUD", kind=Organisation.Kind.END_CLIENT,
                                       activity_sector=Organisation.ActivitySector.OTHER)
    client.end_clients.add(end)
    stray = Organisation.objects.create(name="Client final autre", kind=Organisation.Kind.END_CLIENT,
                                         activity_sector=Organisation.ActivitySector.OTHER)
    admin = site._registry[Contract]
    form_class = admin.get_form(request)
    form = form_class({"client": client.pk})
    assert set(form.fields["end_clients"].queryset.values_list("pk", flat=True)) == {end.pk}
    assert stray.pk not in form.fields["end_clients"].queryset.values_list("pk", flat=True)


def _solution(client, **kw):
    contract, _ = Contract.objects.get_or_create(reference="HUD-9", defaults={
        "title": "x", "client": client, "start_date": datetime.date(2026, 1, 1),
        "contract_type": ContractType.objects.get(name="Standard 8x5")})
    return Solution(contract=contract, name="Élément", **kw)


def test_license_dates_are_kept_for_every_category(setup):
    client, _users, _request = setup
    start, end = datetime.date(2026, 1, 1), datetime.date(2027, 1, 1)
    for category in ("software", "hardware", "vm", "cloud", "other"):
        s = _solution(client, category=category, license_start=start, license_end=end)
        s.full_clean()
        assert (s.license_start, s.license_end) == (start, end)
    with pytest.raises(ValidationError):
        _solution(client, category="hardware", license_start=end, license_end=start).full_clean()


def test_license_dates_use_the_calendar_widget(setup):
    _client, _users, request = setup
    admin = site._registry[Contract]
    inline = next(i for i in admin.get_inline_instances(request) if i.model is Solution)
    form = inline.get_formset(request)().empty_form
    for name in ("license_start", "license_end"):
        assert "vDateField" in form[name].as_widget()  # champ date de Django : icône calendrier


def test_category_options_have_hover_help(setup):
    _client, _users, request = setup
    admin = site._registry[Contract]
    inline = next(i for i in admin.get_inline_instances(request) if i.model is Solution)
    html = inline.get_formset(request)().empty_form.fields["category"].widget.render("category", "")
    assert 'value="software" title="' in html and 'value="other" title="' in html


@pytest.mark.parametrize("who", ["engineer", "client"])
def test_allowed_access_is_saved_with_the_new_contract(setup, who):
    client, users, request = setup
    contract, formset = _validate(request, _post(client, users[who]))
    assert formset.is_valid(), formset.errors
    contract.save()
    formset.instance = contract
    formset.save()
    assert ContractAccess.objects.filter(contract=contract, user=users[who]).exists()
