from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scheduler', '0010_slot6_1_10_to_2_00'),
    ]

    operations = [
        migrations.AddField(
            model_name='section',
            name='free_day',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', 'None'),
                    ('Monday', 'Monday'),
                    ('Tuesday', 'Tuesday'),
                    ('Wednesday', 'Wednesday'),
                    ('Thursday', 'Thursday'),
                    ('Friday', 'Friday'),
                ],
                default='',
                help_text='Weekly holiday for this section (e.g. Wednesday). No lectures scheduled on this day.',
                max_length=10,
            ),
        ),
    ]
