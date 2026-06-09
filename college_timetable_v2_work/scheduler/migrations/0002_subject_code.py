from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scheduler', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='subject',
            name='code',
            field=models.CharField(
                blank=True,
                default='',
                help_text='e.g. CS301, IT401 (optional but recommended)',
                max_length=20,
                verbose_name='Subject Code',
            ),
        ),
    ]
