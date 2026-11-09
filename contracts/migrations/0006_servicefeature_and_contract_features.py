# Generated for Aptitude Ticketing formulas and criteria

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0005_solution_remove_precision'),
    ]

    operations = [
        migrations.CreateModel(
            name='ServiceFeature',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=60, unique=True, verbose_name='code')),
                ('name', models.CharField(max_length=150, verbose_name='intitulé')),
                ('category', models.CharField(choices=[
                    ('support', "Support & Niveaux"),
                    ('supervision', "Supervision & Monitoring"),
                    ('security', "Sécurité, SOC & Incidents"),
                    ('changes', "Gestion des changements"),
                    ('governance', "Gouvernance & Conformité"),
                    ('infrastructure', "Infrastructure & Matériel"),
                ], default='support', max_length=30, verbose_name='catégorie')),
                ('description', models.TextField(blank=True, verbose_name='description')),
                ('order', models.PositiveSmallIntegerField(default=10, verbose_name='ordre')),
                ('is_active', models.BooleanField(default=True, verbose_name='actif')),
            ],
            options={
                'verbose_name': 'critère de service',
                'verbose_name_plural': 'critères de service',
                'ordering': ['category', 'order', 'name'],
            },
        ),
        migrations.AlterModelOptions(
            name='contracttype',
            options={'ordering': ['name'], 'verbose_name': 'formule / type de contrat', 'verbose_name_plural': 'formules / types de contrat'},
        ),
        migrations.AddField(
            model_name='contracttype',
            name='billing_mode',
            field=models.CharField(blank=True, help_text='Ex. Gratuit, CFA/équipement/mois, Forfait...', max_length=150, verbose_name='mode de facturation'),
        ),
        migrations.AddField(
            model_name='contracttype',
            name='commitment_period',
            field=models.CharField(blank=True, help_text='Ex. Min: 1 mois - Max: 3 mois, Annuel...', max_length=150, verbose_name='engagement contractuel'),
        ),
        migrations.AddField(
            model_name='contracttype',
            name='positioning',
            field=models.CharField(blank=True, help_text='Ex. Garantie SAV, Assistance essentielle, Assistance opérationnelle, MSSP...', max_length=150, verbose_name='positionnement'),
        ),
        migrations.AddField(
            model_name='contracttype',
            name='scope',
            field=models.CharField(blank=True, help_text='Ex. Support incidents, Support + supervision, Managed Security Services...', max_length=150, verbose_name='périmètre couvert'),
        ),
        migrations.AddField(
            model_name='contracttype',
            name='target_clients',
            field=models.CharField(blank=True, help_text='Ex. Tout client, PME – non critique, SI critiques, Banques / Telco...', max_length=150, verbose_name='type de clients'),
        ),
        migrations.AddField(
            model_name='contracttype',
            name='features',
            field=models.ManyToManyField(blank=True, related_name='contract_types', to='contracts.servicefeature', verbose_name='critères inclus dans la formule'),
        ),
        migrations.AddField(
            model_name='contract',
            name='extra_features',
            field=models.ManyToManyField(blank=True, help_text='Critères ou options activés pour ce client en plus de ceux de sa formule de base.', related_name='contracts_extra', to='contracts.servicefeature', verbose_name='options additionnelles (sur-mesure client)'),
        ),
        migrations.AddField(
            model_name='contract',
            name='excluded_features',
            field=models.ManyToManyField(blank=True, help_text='Critères de la formule retirés exceptionnellement pour ce contrat.', related_name='contracts_excluded', to='contracts.servicefeature', verbose_name='options exclues'),
        ),
    ]

