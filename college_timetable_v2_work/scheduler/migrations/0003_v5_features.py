from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('scheduler', '0002_subject_code'),
    ]

    operations = [
        # ── Section: custom year support ─────────────────────────────────────
        migrations.AlterField(
            model_name='section',
            name='year',
            field=models.CharField(
                max_length=10,
                choices=[
                    ('1ST', '1st Year'), ('2ND', '2nd Year'),
                    ('3RD', '3rd Year'), ('4TH', '4th Year'),
                    ('CUSTOM', 'Custom Year'),
                ],
            ),
        ),
        migrations.AddField(
            model_name='section',
            name='custom_year',
            field=models.CharField(
                blank=True, default='', max_length=50,
                help_text='e.g. 5th Year — only used when "Custom Year" is selected.',
            ),
        ),
        # ── Section: custom section name support ─────────────────────────────
        migrations.AlterField(
            model_name='section',
            name='section_name',
            field=models.CharField(
                default='A', max_length=20,
                choices=[
                    ('A', 'Section A'), ('B', 'Section B'), ('C', 'Section C'),
                    ('D', 'Section D'), ('E', 'Section E'), ('CUSTOM', 'Custom Section'),
                ],
            ),
        ),
        migrations.AddField(
            model_name='section',
            name='custom_section_name',
            field=models.CharField(
                blank=True, default='', max_length=50,
                help_text='e.g. F, G, Alpha — only used when "Custom Section" is selected.',
            ),
        ),
        # ── Section: relax unique_together to allow custom combos ────────────
        migrations.AlterUniqueTogether(
            name='section',
            unique_together={('course', 'year', 'section_name', 'group', 'custom_year', 'custom_section_name')},
        ),
        # ── Subject: add NPTEL type + lab_room pin ───────────────────────────
        migrations.AlterField(
            model_name='subject',
            name='subject_type',
            field=models.CharField(
                max_length=10,
                choices=[
                    ('THEORY', 'Theoretical'),
                    ('LAB', 'Lab'),
                    ('TUTORIAL', 'Tutorial'),
                    ('NPTEL', 'NPTEL (after 2:00 PM only)'),
                ],
            ),
        ),
        migrations.AddField(
            model_name='subject',
            name='lab_room',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='pinned_subjects',
                to='scheduler.room',
                help_text='Pin this lab/subject to a specific room.',
            ),
        ),
        # ── New model: ProfessorOccupiedTime ─────────────────────────────────
        migrations.CreateModel(
            name='ProfessorOccupiedTime',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('day', models.CharField(
                    max_length=10,
                    choices=[
                        ('Monday', 'Monday'), ('Tuesday', 'Tuesday'),
                        ('Wednesday', 'Wednesday'), ('Thursday', 'Thursday'),
                        ('Friday', 'Friday'),
                    ],
                )),
                ('start_slot', models.IntegerField(
                    choices=[
                        (1, '9:00–9:50'), (2, '9:50–10:40'), (3, '10:40–11:30'),
                        (4, '11:30–12:20'), (5, '12:20–1:10'),
                        (6, '2:00–2:50'), (7, '2:50–3:40'),
                    ],
                    help_text='First blocked slot',
                )),
                ('end_slot', models.IntegerField(
                    choices=[
                        (1, '9:00–9:50'), (2, '9:50–10:40'), (3, '10:40–11:30'),
                        (4, '11:30–12:20'), (5, '12:20–1:10'),
                        (6, '2:00–2:50'), (7, '2:50–3:40'),
                    ],
                    help_text='Last blocked slot (inclusive)',
                )),
                ('activity_type', models.CharField(
                    default='MEETING', max_length=20,
                    choices=[
                        ('MEETING', 'Meeting'),
                        ('MENTORING', 'Student Mentoring'),
                        ('OTHER', 'Other Activity'),
                    ],
                )),
                ('description', models.CharField(blank=True, max_length=200, help_text='Optional notes')),
                ('professor', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='occupied_times',
                    to='scheduler.professor',
                )),
            ],
        ),
    ]
