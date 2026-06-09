from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('scheduler', '0005_alter_professoroccupiedtime_id_alter_room_department_and_more'),
    ]

    operations = [
        # DepartmentSettings
        migrations.CreateModel(
            name='DepartmentSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('lunch_start_slot', models.IntegerField(choices=[(1, '9:00\u20139:50'), (2, '9:50\u201310:40'), (3, '10:40\u201311:30'), (4, '11:30\u201312:20'), (5, '12:20\u20131:10'), (6, '2:00\u20132:50'), (7, '2:50\u20133:40')], default=5)),
                ('lunch_end_slot', models.IntegerField(choices=[(1, '9:00\u20139:50'), (2, '9:50\u201310:40'), (3, '10:40\u201311:30'), (4, '11:30\u201312:20'), (5, '12:20\u20131:10'), (6, '2:00\u20132:50'), (7, '2:50\u20133:40')], default=5)),
                ('working_days', models.CharField(default='Monday,Tuesday,Wednesday,Thursday,Friday', max_length=200)),
                ('lecture_duration_minutes', models.IntegerField(default=50)),
                ('department', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='settings', to='scheduler.department')),
            ],
        ),
        # CSVImportLog
        migrations.CreateModel(
            name='CSVImportLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('imported_at', models.DateTimeField(auto_now_add=True)),
                ('status', models.CharField(choices=[('SUCCESS', 'Success'), ('PARTIAL', 'Partial Success'), ('FAILED', 'Failed')], default='SUCCESS', max_length=10)),
                ('subjects_created', models.IntegerField(default=0)),
                ('professors_created', models.IntegerField(default=0)),
                ('rooms_created', models.IntegerField(default=0)),
                ('sections_created', models.IntegerField(default=0)),
                ('errors', models.TextField(blank=True, default='')),
                ('warnings', models.TextField(blank=True, default='')),
            ],
        ),
        # Room: add allowed_subjects
        migrations.AddField(
            model_name='room',
            name='allowed_subjects',
            field=models.TextField(blank=True, default='all', help_text='"all" or comma-separated subject names this lab can host.'),
        ),
        # Section: add fixed_room
        migrations.AddField(
            model_name='section',
            name='fixed_room',
            field=models.ForeignKey(blank=True, help_text='If set, theory lectures always use this room.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='fixed_sections', to='scheduler.room'),
        ),
        # Professor: add max_workload_hours_per_week
        migrations.AddField(
            model_name='professor',
            name='max_workload_hours_per_week',
            field=models.IntegerField(default=20),
        ),
        # Professor: add specialization_subjects
        migrations.AddField(
            model_name='professor',
            name='specialization_subjects',
            field=models.TextField(blank=True, default=''),
        ),
        # Subject: add allowed_groups
        migrations.AddField(
            model_name='subject',
            name='allowed_groups',
            field=models.CharField(choices=[('G1', 'Group 1 Only'), ('G2', 'Group 2 Only'), ('BOTH', 'Both Groups')], default='BOTH', max_length=10),
        ),
        # Subject: add specialization_required
        migrations.AddField(
            model_name='subject',
            name='specialization_required',
            field=models.BooleanField(default=False),
        ),
    ]
