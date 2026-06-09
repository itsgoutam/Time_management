from django.db import migrations, models


NEW_SLOT_CHOICES = [
    (1, '9:00–9:50'),
    (2, '9:50–10:40'),
    (3, '10:40–11:30'),
    (4, '11:30–12:20'),
    (5, '12:20–1:10'),
    (6, '1:10–2:00'),
    (7, '2:00–2:50'),
    (8, '2:50–3:40'),
    (9, '3:40–4:30'),
]


def shift_slots_up(apps, schema_editor):
    """
    Old slots: 6=2:00, 7=2:50, 8=3:40
    New slots: 6=1:10, 7=2:00, 8=2:50, 9=3:40
    Shift all existing slot values 6→7, 7→8, 8→9 (in reverse to avoid collisions).
    """
    TimeSlot = apps.get_model('scheduler', 'TimeSlot')
    ProfOcc = apps.get_model('scheduler', 'ProfessorOccupiedTime')
    RoomOcc = apps.get_model('scheduler', 'RoomOccupiedTime')
    DeptSettings = apps.get_model('scheduler', 'DepartmentSettings')

    # Shift in reverse order to avoid overwriting
    for old, new in [(8, 9), (7, 8), (6, 7)]:
        TimeSlot.objects.filter(slot=old).update(slot=new)
        ProfOcc.objects.filter(start_slot=old).update(start_slot=new)
        ProfOcc.objects.filter(end_slot=old).update(end_slot=new)
        RoomOcc.objects.filter(start_slot=old).update(start_slot=new)
        RoomOcc.objects.filter(end_slot=old).update(end_slot=new)
        DeptSettings.objects.filter(lunch_start_slot=old).update(lunch_start_slot=new)
        DeptSettings.objects.filter(lunch_end_slot=old).update(lunch_end_slot=new)
        DeptSettings.objects.filter(dept_start_slot=old).update(dept_start_slot=new)


def shift_slots_down(apps, schema_editor):
    """Reverse migration: shift 7→6, 8→7, 9→8."""
    TimeSlot = apps.get_model('scheduler', 'TimeSlot')
    ProfOcc = apps.get_model('scheduler', 'ProfessorOccupiedTime')
    RoomOcc = apps.get_model('scheduler', 'RoomOccupiedTime')
    DeptSettings = apps.get_model('scheduler', 'DepartmentSettings')

    for old, new in [(7, 6), (8, 7), (9, 8)]:
        TimeSlot.objects.filter(slot=old).update(slot=new)
        ProfOcc.objects.filter(start_slot=old).update(start_slot=new)
        ProfOcc.objects.filter(end_slot=old).update(end_slot=new)
        RoomOcc.objects.filter(start_slot=old).update(start_slot=new)
        RoomOcc.objects.filter(end_slot=old).update(end_slot=new)
        DeptSettings.objects.filter(lunch_start_slot=old).update(lunch_start_slot=new)
        DeptSettings.objects.filter(lunch_end_slot=old).update(lunch_end_slot=new)
        DeptSettings.objects.filter(dept_start_slot=old).update(dept_start_slot=new)


class Migration(migrations.Migration):

    dependencies = [
        ('scheduler', '0009_dept_start_slot_slot8'),
    ]

    operations = [
        # 1. Run data migration FIRST (before altering choices)
        migrations.RunPython(shift_slots_up, shift_slots_down),

        # 2. Update choices on all slot fields to include new slot 6
        migrations.AlterField(
            model_name='departmentsettings',
            name='lunch_start_slot',
            field=models.IntegerField(default=5, choices=NEW_SLOT_CHOICES),
        ),
        migrations.AlterField(
            model_name='departmentsettings',
            name='lunch_end_slot',
            field=models.IntegerField(default=5, choices=NEW_SLOT_CHOICES),
        ),
        migrations.AlterField(
            model_name='departmentsettings',
            name='dept_start_slot',
            field=models.IntegerField(default=1, choices=NEW_SLOT_CHOICES),
        ),
        migrations.AlterField(
            model_name='professoroccupiedtime',
            name='start_slot',
            field=models.IntegerField(choices=NEW_SLOT_CHOICES),
        ),
        migrations.AlterField(
            model_name='professoroccupiedtime',
            name='end_slot',
            field=models.IntegerField(choices=NEW_SLOT_CHOICES),
        ),
        migrations.AlterField(
            model_name='roomoccupiedtime',
            name='start_slot',
            field=models.IntegerField(choices=NEW_SLOT_CHOICES),
        ),
        migrations.AlterField(
            model_name='roomoccupiedtime',
            name='end_slot',
            field=models.IntegerField(choices=NEW_SLOT_CHOICES),
        ),
        migrations.AlterField(
            model_name='timeslot',
            name='slot',
            field=models.IntegerField(choices=NEW_SLOT_CHOICES),
        ),
    ]
