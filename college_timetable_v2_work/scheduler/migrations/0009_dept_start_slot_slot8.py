from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Migration 0009:
    1. Adds `dept_start_slot` field to DepartmentSettings (default = 1 = 9:00 AM).
    2. Extends SLOT_CHOICES to include slot 8 (3:40–4:30 PM).
    """

    dependencies = [
        ('scheduler', '0008_professor_section_restrictions'),
    ]

    SLOT_CHOICES_NEW = [
        (1, '9:00–9:50'),
        (2, '9:50–10:40'),
        (3, '10:40–11:30'),
        (4, '11:30–12:20'),
        (5, '12:20–1:10'),
        (6, '2:00–2:50'),
        (7, '2:50–3:40'),
        (8, '3:40–4:30'),
    ]

    operations = [
        # Add dept_start_slot to DepartmentSettings
        migrations.AddField(
            model_name='departmentsettings',
            name='dept_start_slot',
            field=models.IntegerField(
                default=1,
                choices=SLOT_CHOICES_NEW,
                help_text='First slot of the day for this department (default: 1 = 9:00 AM)',
            ),
        ),
        # Update choices on existing slot fields to include slot 8
        migrations.AlterField(
            model_name='departmentsettings',
            name='lunch_start_slot',
            field=models.IntegerField(default=5, choices=SLOT_CHOICES_NEW),
        ),
        migrations.AlterField(
            model_name='departmentsettings',
            name='lunch_end_slot',
            field=models.IntegerField(default=5, choices=SLOT_CHOICES_NEW),
        ),
        migrations.AlterField(
            model_name='professoroccupiedtime',
            name='start_slot',
            field=models.IntegerField(choices=SLOT_CHOICES_NEW),
        ),
        migrations.AlterField(
            model_name='professoroccupiedtime',
            name='end_slot',
            field=models.IntegerField(choices=SLOT_CHOICES_NEW),
        ),
        migrations.AlterField(
            model_name='roomoccupiedtime',
            name='start_slot',
            field=models.IntegerField(choices=SLOT_CHOICES_NEW),
        ),
        migrations.AlterField(
            model_name='roomoccupiedtime',
            name='end_slot',
            field=models.IntegerField(choices=SLOT_CHOICES_NEW),
        ),
        migrations.AlterField(
            model_name='timeslot',
            name='slot',
            field=models.IntegerField(choices=SLOT_CHOICES_NEW),
        ),
    ]
