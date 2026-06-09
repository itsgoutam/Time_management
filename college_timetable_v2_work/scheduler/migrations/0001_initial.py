from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """
    Single clean initial migration — replaces all previous conflicting migrations.
    Creates every table in its final state in one shot, so fresh installs
    never hit "table already exists" errors.
    """

    initial = True
    dependencies = []

    operations = [
        # ── Department ────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='Department',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
            ],
        ),

        # ── Professor ─────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='Professor',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('email', models.EmailField(blank=True, max_length=254)),
            ],
        ),

        # ── Course ────────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='Course',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('name', models.CharField(
                    max_length=10,
                    choices=[
                        ('BTECH', 'B.TECH'),
                        ('BE', 'BE'),
                        ('MTECH', 'M.TECH'),
                        ('CUSTOM', 'Custom'),
                    ],
                )),
                ('custom_name', models.CharField(blank=True, default='', max_length=100)),
                ('department', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='courses',
                    to='scheduler.department',
                )),
            ],
        ),

        # ── Room ──────────────────────────────────────────────────────────────
        # Created ONCE here — not in any later migration.
        # Includes the 'department' FK added in the old 0006 migration.
        migrations.CreateModel(
            name='Room',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('room_type', models.CharField(
                    max_length=10,
                    choices=[('CLASSROOM', 'Classroom'), ('LAB', 'Lab')],
                    default='CLASSROOM',
                )),
                ('capacity', models.IntegerField(default=60)),
                ('department', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='rooms',
                    to='scheduler.department',
                    help_text=(
                        'Assign this room/lab to a department (optional). '
                        'Assigned rooms are prioritised for that department '
                        'during timetable generation.'
                    ),
                )),
            ],
        ),

        # ── Section ───────────────────────────────────────────────────────────
        # Final state: course + year + section_name + group
        # No room/lab FKs (those were added then removed in old migrations).
        migrations.CreateModel(
            name='Section',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('year', models.CharField(
                    max_length=5,
                    choices=[
                        ('1ST', '1st Year'),
                        ('2ND', '2nd Year'),
                        ('3RD', '3rd Year'),
                        ('4TH', '4th Year'),
                    ],
                )),
                ('section_name', models.CharField(
                    max_length=2,
                    choices=[
                        ('A', 'Section A'),
                        ('B', 'Section B'),
                        ('C', 'Section C'),
                        ('D', 'Section D'),
                        ('E', 'Section E'),
                    ],
                    default='A',
                )),
                ('group', models.CharField(
                    max_length=10,
                    choices=[('G1', 'Group 1'), ('G2', 'Group 2')],
                )),
                ('course', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='sections',
                    to='scheduler.course',
                )),
            ],
            options={
                'unique_together': {('course', 'year', 'section_name', 'group')},
            },
        ),

        # ── Subject ───────────────────────────────────────────────────────────
        # Includes TUTORIAL type.
        migrations.CreateModel(
            name='Subject',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('subject_type', models.CharField(
                    max_length=10,
                    choices=[
                        ('THEORY', 'Theoretical'),
                        ('LAB', 'Lab'),
                        ('TUTORIAL', 'Tutorial'),
                    ],
                )),
                ('duration', models.IntegerField(default=1)),
                ('lectures_per_week', models.IntegerField()),
                ('professors', models.ManyToManyField(to='scheduler.professor')),
                ('section', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='subjects',
                    to='scheduler.section',
                )),
            ],
        ),

        # ── TimeSlot ──────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='TimeSlot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('day', models.CharField(max_length=10)),
                ('slot', models.IntegerField()),
                ('professor', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to='scheduler.professor',
                )),
                ('subject', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to='scheduler.subject',
                )),
                ('section', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    to='scheduler.section',
                )),
                ('room', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='timeslots',
                    to='scheduler.room',
                )),
            ],
        ),
    ]
