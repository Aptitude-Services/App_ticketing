# Data migration for Aptitude Ticketing formulas and features

from django.db import migrations

CRITERIA = [
    # Support & Niveaux
    ("support_n1_n2", "Support N1 / N2", "support", 10, "Support technique niveaux 1 et 2 pour la prise en charge et le traitement standard des incidents."),
    ("support_n3", "Support N3 expert", "support", 20, "Escalade et expertise avancée niveau 3 pour les incidents complexes."),

    # Supervision & Monitoring
    ("supervision_disponibilite", "Supervision disponibilité", "supervision", 10, "Monitoring continu de la disponibilité des équipements et des services."),
    ("supervision_performance", "Supervision performance", "supervision", 20, "Suivi des métriques de charge (CPU, RAM, bande passante) et performances."),

    # Sécurité, SOC & Incidents
    ("analyse_logs_soc", "Analyse logs sécurité (corrélée SOC)", "security", 10, "Collecte, normalisation et corrélation des journaux d'événements de sécurité par le SOC."),
    ("detection_incidents_basique", "Détection Incidents sécurité (Basique)", "security", 20, "Détection élémentaire des anomalies et alertes de sécurité standard."),
    ("detection_incidents_soc", "Détection Incidents sécurité (Avancée SOC)", "security", 25, "Détection avancée 24x7 avec règles de détection et corrélation SOC."),
    ("reponse_incidents_guidee", "Réponse aux incidents (Guidée)", "security", 30, "Conseils, procédures pas-à-pas et guidage des équipes pour la remédiation."),
    ("reponse_incidents_active", "Réponse aux incidents (Active)", "security", 35, "Intervention directe, confinement et remédiation active par nos ingénieurs."),
    ("revue_firewall_periodique", "Revue règles firewall (Périodique)", "security", 40, "Revue périodique des règles de filtrage et de la politique de sécurité pare-feu."),
    ("revue_firewall_trimestrielle", "Revue règles firewall (Trimestrielle)", "security", 45, "Audit trimestriel complet et optimisation des flux et règles firewall."),
    ("durcissement_recommande", "Durcissement sécurité (Recommandé)", "security", 50, "Recommandations de renforcement de configuration et durcissement des systèmes."),
    ("durcissement_proactif", "Durcissement sécurité (Proactif)", "security", 55, "Application proactive des standards de durcissement (CIS Benchmarks, ANSSI)."),
    ("gestion_vulnerabilites", "Gestion des vulnérabilités", "security", 60, "Identification continue, évaluation et suivi de la correction des failles de sécurité."),

    # Gestion des changements
    ("changements_mineurs", "Changements inclus : Mineurs", "changes", 10, "Prise en compte des demandes d'évolution ou modifications simples sans devis."),
    ("changements_standards", "Changements inclus : Standards", "changes", 20, "Changements standards catalogués inclus sans facturation supplémentaire."),
    ("changements_illimites", "Changements inclus : Illimités (hors projet)", "changes", 30, "Changements illimités inclus dans le périmètre du contrat (hors projets majeurs)."),

    # Gouvernance & Conformité
    ("reporting_trimestriel", "Reporting trimestriel", "governance", 10, "Rapport d'activité trimestriel consolidé avec indicateurs de service."),
    ("reporting_mensuel_comite", "Reporting mensuel + Comité trimestriel", "governance", 20, "Rapports mensuels détaillés et réunion trimestrielle de revue de service."),
    ("comite_pilotage", "Comité de pilotage", "governance", 30, "Comité stratégique dédié au suivi des orientations, de la sécurité et des KPI."),
    ("accompagnement_conformite_partiel", "Accompagnement conformité (Partiel)", "governance", 40, "Assistance ponctuelle sur les exigences réglementaires et de conformité."),
    ("accompagnement_conformite_audit", "Accompagnement conformité (ISO / PCI / Audit)", "governance", 45, "Support complet pour les audits de conformité, normes ISO 27001 et PCI-DSS."),

    # Infrastructure & Matériel
    ("gestion_spares", "Gestion des spares", "infrastructure", 10, "Gestion et maintien en condition opérationnelle d'un stock de pièces ou matériels de rechange."),
]

FORMULAS = [
    {
        "name": "STARTER",
        "description": "Formule Starter — Garantie SAV pour tout type de client avec support incidents en 8x5.",
        "coverage_name": "SLA 8x5",
        "positioning": "Garantie SAV",
        "target_clients": "Tout client",
        "scope": "Support incidents",
        "billing_mode": "Gratuit",
        "commitment_period": "Min : 1 mois - Max : 3 mois",
        "features": [
            "support_n1_n2",
            "support_n3",
        ],
    },
    {
        "name": "BRONZE",
        "description": "Formule Bronze — Assistance essentielle pour PME non critique avec support incidents en 8x5 et SLA J+1.",
        "coverage_name": "SLA 8x5",
        "positioning": "Assistance essentielle",
        "target_clients": "PME – non critique",
        "scope": "Support incidents",
        "billing_mode": "CFA/équipement/mois",
        "commitment_period": "Annuel",
        "features": [
            "support_n1_n2",
            "reporting_trimestriel",
            "gestion_vulnerabilites",
        ],
    },
    {
        "name": "SILVER",
        "description": "Formule Silver — Assistance opérationnelle pour PME structurées avec support incidents, supervision et changements mineurs en 8x5.",
        "coverage_name": "SLA 8x5",
        "positioning": "Assistance opérationnelle",
        "target_clients": "PME structurées",
        "scope": "Support + supervision",
        "billing_mode": "CFA/équipement/mois",
        "commitment_period": "Annuel",
        "features": [
            "support_n1_n2",
            "support_n3",
            "supervision_disponibilite",
            "changements_mineurs",
            "reporting_trimestriel",
            "gestion_vulnerabilites",
        ],
    },
    {
        "name": "GOLD",
        "description": "Formule Gold — Assistance avancée sécurité pour SI critiques avec support 24x7, supervision performance et réactivité 2h.",
        "coverage_name": "SLA 24x7",
        "positioning": "Assistance avancée sécurité",
        "target_clients": "SI critiques",
        "scope": "Support + sécurité",
        "billing_mode": "CFA/équipement/mois",
        "commitment_period": "Annuel",
        "features": [
            "support_n1_n2",
            "support_n3",
            "supervision_disponibilite",
            "supervision_performance",
            "detection_incidents_basique",
            "reponse_incidents_guidee",
            "changements_standards",
            "revue_firewall_periodique",
            "durcissement_recommande",
            "reporting_mensuel_comite",
            "accompagnement_conformite_partiel",
            "gestion_vulnerabilites",
        ],
    },
    {
        "name": "PLATINUM",
        "description": "Formule Platinum — Managed Security Services (MSSP) pour banques, opérateurs télécom et infrastructures critiques avec SOC 24x7.",
        "coverage_name": "SLA 24x7",
        "positioning": "MSSP / Critique",
        "target_clients": "Banques, Telco, Infrastructures critiques",
        "scope": "Managed Security Services",
        "billing_mode": "Forfait ou CFA/équipement/mois",
        "commitment_period": "Annuel",
        "features": [
            "support_n1_n2",
            "support_n3",
            "supervision_disponibilite",
            "supervision_performance",
            "analyse_logs_soc",
            "detection_incidents_soc",
            "reponse_incidents_active",
            "changements_illimites",
            "revue_firewall_trimestrielle",
            "durcissement_proactif",
            "reporting_mensuel_comite",
            "comite_pilotage",
            "accompagnement_conformite_audit",
            "gestion_vulnerabilites",
        ],
    },
]


def forwards(apps, schema_editor):
    ServiceFeature = apps.get_model("contracts", "ServiceFeature")
    ContractType = apps.get_model("contracts", "ContractType")
    SLA = apps.get_model("sla", "SLA")

    sla_8x5 = SLA.objects.filter(coverage="8x5").first()
    sla_24x7 = SLA.objects.filter(coverage="24x7").first()
    default_sla = sla_8x5 or sla_24x7

    # 1. Créer ou mettre à jour les critères de service
    feature_map = {}
    for code, name, category, order, description in CRITERIA:
        feat, _ = ServiceFeature.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "category": category,
                "order": order,
                "description": description,
                "is_active": True,
            },
        )
        feature_map[code] = feat

    # 2. Créer ou mettre à jour les 5 formules de base si un SLA est disponible
    if default_sla:
        for item in FORMULAS:
            sla_target = sla_24x7 if item["coverage_name"] == "SLA 24x7" else sla_8x5
            sla = sla_target or default_sla
            ct, _ = ContractType.objects.update_or_create(
                name=item["name"],
                defaults={
                    "description": item["description"],
                    "sla": sla,
                    "positioning": item["positioning"],
                    "target_clients": item["target_clients"],
                    "scope": item["scope"],
                    "billing_mode": item["billing_mode"],
                    "commitment_period": item["commitment_period"],
                    "is_active": True,
                },
            )
            feats_to_set = [feature_map[code] for code in item["features"] if code in feature_map]
            ct.features.set(feats_to_set)


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0006_servicefeature_and_contract_features'),
        ('sla', '0002_default_data'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

