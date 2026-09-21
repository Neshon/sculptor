"""Картинки компонентов больше не хранятся — только посадочных мест.

Данные перенесены предыдущей миграцией (0014). Таблица
``oy_component_image`` удаляется; файлы на диске не трогаются.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("components", "0014_move_images_to_footprints"),
    ]

    operations = [
        migrations.DeleteModel(name="ComponentImage"),
    ]
