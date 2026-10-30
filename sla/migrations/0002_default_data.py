"""SLA par défaut (grille validée) et jours fériés 2026-2027."""
import datetime

from django.db import migrations

H = 60
GRID = {1: (1 * H, 8 * H), 2: (1 * H, 12 * H), 3: (4 * H, 24 * H), 4: (8 * H, 48 * H)}


def forwards(apps, schema_editor):
    from sla.holidays import holidays_for

    SLA = apps.get_model("sla", "SLA")
    SLATarget = apps.get_model("sla", "SLATarget")
    Holiday = apps.get_model("sla", "Holiday")
    for name, coverage in (("SLA 24x7", "24x7"), ("SLA 8x5", "8x5")):
        sla, _ = SLA.objects.get_or_create(
            name=name,
            defaults={"coverage": coverage, "day_start": datetime.time(8), "day_end": datetime.time(17),
                      "working_days": "0,1,2,3,4"},
        )
        for prio, (resp, reso) in GRID.items():
            SLATarget.objects.get_or_create(sla=sla, priority=prio,
                                            defaults={"response_minutes": resp, "resolution_minutes": reso})
    for year in (2026, 2027):
        for date, name, kind in holidays_for(year):
            Holiday.objects.get_or_create(date=date, defaults={"name": name, "kind": kind})


class Migration(migrations.Migration):
    dependencies = [("sla", "0001_initial")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
