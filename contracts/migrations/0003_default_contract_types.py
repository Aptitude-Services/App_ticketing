from django.db import migrations


def forwards(apps, schema_editor):
    SLA = apps.get_model("sla", "SLA")
    ContractType = apps.get_model("contracts", "ContractType")
    Contract = apps.get_model("contracts", "Contract")
    t24, _ = ContractType.objects.get_or_create(name="Standard 24x7", defaults={"sla": SLA.objects.get(name="SLA 24x7")})
    t85, _ = ContractType.objects.get_or_create(name="Standard 8x5", defaults={"sla": SLA.objects.get(name="SLA 8x5")})
    # Contrats créés avant ce jalon : rattachés au type 8x5 par défaut.
    Contract.objects.filter(contract_type__isnull=True).update(contract_type=t85)


class Migration(migrations.Migration):
    dependencies = [("contracts", "0002_remove_contract_coverage_contracttype_and_more"), ("sla", "0002_default_data")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
