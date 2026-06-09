from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scheduler', '0007_alter_professoroccupiedtime_description_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='professor',
            name='section_restrictions',
            field=models.TextField(blank=True, default=''),
        ),
    ]
