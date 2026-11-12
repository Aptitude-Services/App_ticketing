"""Tests des formules (ContractType), critères de service (ServiceFeature)
et personnalisation par contrat client (extra_features / dérogations).
"""
import datetime
import pytest

from accounts.models import Organisation
from contracts.models import Contract, ContractType, ServiceFeature
from sla.models import SLA

pytestmark = pytest.mark.django_db


@pytest.fixture
def base_setup():
    Organisation.objects.create(name="Aptitude Services", kind=Organisation.Kind.CLIENT, is_operator=True)
    sector = Organisation.ActivitySector.OTHER
    client_a = Organisation.objects.create(name="Client A", kind=Organisation.Kind.CLIENT, activity_sector=sector)
    client_b = Organisation.objects.create(name="Client B", kind=Organisation.Kind.CLIENT, activity_sector=sector)

    sla_8x5 = SLA.objects.get_or_create(
        name="SLA 8x5",
        defaults={"coverage": "8x5", "day_start": datetime.time(8), "day_end": datetime.time(17), "working_days": "0,1,2,3,4"},
    )[0]

    # get_or_create pour cohabiter avec la migration 0007 qui a déjà inséré ces critères
    feat_n1_n2, _ = ServiceFeature.objects.get_or_create(
        code="support_n1_n2", defaults={"name": "Support N1 / N2", "category": "support", "order": 10},
    )
    feat_n3, _ = ServiceFeature.objects.get_or_create(
        code="support_n3", defaults={"name": "Support N3 expert", "category": "support", "order": 20},
    )
    feat_vuln, _ = ServiceFeature.objects.get_or_create(
        code="gestion_vulnerabilites", defaults={"name": "Gestion des vulnérabilités", "category": "security", "order": 60},
    )

    # Formule de test : contient N1/N2 et Vulnérabilités, mais PAS Support N3
    bronze, _ = ContractType.objects.get_or_create(
        name="BRONZE TEST",
        defaults={
            "sla": sla_8x5,
            "positioning": "Assistance essentielle",
            "scope": "Support incidents",
            "billing_mode": "CFA/équipement/mois",
            "commitment_period": "Annuel",
        },
    )
    bronze.features.set([feat_n1_n2, feat_vuln])

    return {
        "client_a": client_a,
        "client_b": client_b,
        "bronze": bronze,
        "feat_n1_n2": feat_n1_n2,
        "feat_n3": feat_n3,
        "feat_vuln": feat_vuln,
    }


def test_formula_features_standard(base_setup):
    """La formule Bronze de test a N1/N2 mais pas de N3."""
    bronze = base_setup["bronze"]
    codes = set(bronze.features.values_list("code", flat=True))
    assert "support_n1_n2" in codes
    assert "gestion_vulnerabilites" in codes
    assert "support_n3" not in codes


def test_client_custom_addon_support_n3(base_setup):
    """Un client Bronze peut ajouter l'option N3 sans altérer la formule standard."""
    bronze = base_setup["bronze"]
    client_a = base_setup["client_a"]
    client_b = base_setup["client_b"]
    feat_n3 = base_setup["feat_n3"]

    # Contrat 1 : Client A souscrit Bronze standard
    c1 = Contract.objects.create(
        reference="CTR-001",
        title="Contrat Standard A",
        client=client_a,
        contract_type=bronze,
        start_date=datetime.date(2026, 11, 1),
    )
    assert not c1.has_support_n3
    assert not c1.has_feature("support_n3")

    # Contrat 2 : Client B souscrit Bronze + Option N3 expert
    c2 = Contract.objects.create(
        reference="CTR-002",
        title="Contrat Personnalisé B",
        client=client_b,
        contract_type=bronze,
        start_date=datetime.date(2026, 11, 1),
    )
    c2.extra_features.add(feat_n3)

    # Le contrat 2 a bien N3 activé
    assert c2.has_support_n3
    assert c2.has_feature("support_n3")
    assert c2.has_feature("support_n1_n2")

    # Le contrat 1 et la formule Bronze originale ne sont absolument pas affectés
    assert not c1.has_support_n3
    assert "support_n3" not in set(bronze.features.values_list("code", flat=True))

    # Vérification de l'annotation d'origine (custom vs base)
    annotated = c2.active_features_annotated()
    n3_entry = next(item for item in annotated if item["feature"].code == "support_n3")
    assert n3_entry["is_custom"] is True
    assert "Option personnalisée" in str(n3_entry["badge"])

    n1_entry = next(item for item in annotated if item["feature"].code == "support_n1_n2")
    assert n1_entry["is_custom"] is False
    assert "Inclus dans la formule" in str(n1_entry["badge"])


def test_client_excluded_feature(base_setup):
    """Possibilité d'exclure spécifiquement un critère de la formule si demandé."""
    bronze = base_setup["bronze"]
    client_a = base_setup["client_a"]
    feat_vuln = base_setup["feat_vuln"]

    c = Contract.objects.create(
        reference="CTR-EXCL",
        title="Contrat dérogatoire",
        client=client_a,
        contract_type=bronze,
        start_date=datetime.date(2026, 11, 1),
    )
    assert c.has_vulnerabilites
    c.excluded_features.add(feat_vuln)
    assert not c.has_vulnerabilites
