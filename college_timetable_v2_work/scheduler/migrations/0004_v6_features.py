from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('scheduler', '0003_v5_features'),
    ]

    operations = [
        # ── ProfessorOccupiedTime: add is_quick_block flag ────────────────────
        migrations.AddField(
            model_name='professoroccupiedtime',
            name='is_quick_block',
            field=models.BooleanField(
                default=False,
                help_text='Temporary block added during subject assignment',
            ),
        ),
        # ── New model: RoomOccupiedTime ────────────────────────────────────────
        migrations.CreateModel(
            name='RoomOccupiedTime',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name='ID')),
                ('day', models.CharField(
                    max_length=10,
                    choices=[
                        ('Monday', 'Monday'), ('Tuesday', 'Tuesday'),
                        ('Wednesday', 'Wednesday'), ('Thursday', 'Thursday'),
                        ('Friday', 'Friday'),
                    ],
                )),
                ('start_slot', models.IntegerField(
                    help_text='First blocked slot',
                    choices=[
                        (1,'9:00–9:50'),(2,'9:50–10:40'),(3,'10:40–11:30'),
                        (4,'11:30–12:20'),(5,'12:20–1:10'),(6,'2:00–2:50'),(7,'2:50–3:40'),
                    ],
                )),
                ('end_slot', models.IntegerField(
                    help_text='Last blocked slot (inclusive)',
                    choices=[
                        (1,'9:00–9:50'),(2,'9:50–10:40'),(3,'10:40–11:30'),
                        (4,'11:30–12:20'),(5,'12:20–1:10'),(6,'2:00–2:50'),(7,'2:50–3:40'),
                    ],
                )),
                ('purpose', models.CharField(
                    default='OTHER', max_length=20,
                    choices=[
                        ('WORKSHOP','Workshop / Seminar'),
                        ('MAINTENANCE','Maintenance'),
                        ('EXAM','Examination'),
                        ('EVENT','College Event'),
                        ('OTHER','Other'),
                    ],
                )),
                ('description', models.CharField(blank=True, max_length=200,
                                                  help_text='Optional notes')),
                ('room', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='occupied_times',
                    to='scheduler.room',
                )),
            ],
        ),
    ]
