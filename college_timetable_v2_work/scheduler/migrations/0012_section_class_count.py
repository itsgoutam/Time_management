from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scheduler', '0011_section_free_day'),
    ]

    operations = [
        migrations.AddField(
            model_name='section',
            name='class_count',
            field=models.IntegerField(
                default=0,
                help_text='Number of students. Used to auto-select a room with sufficient capacity when no fixed room is set.'
            ),
        ),
    ]
