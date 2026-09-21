"""Картинки посадочных мест: таблица ``oy_footprint_image``.

Картинка из STEP-модели описывает посадочное место, а не компонент, и
теперь хранится у него: одна запись и один файл на footprint. Компоненты
находят её по своему Allegro PCB Footprint в момент показа.

Ключ — посадочное место без регистра и внешних пробелов, уникальный:
«SODFL100X250X050» и «sodfl100x250x050 » — одно место.
"""

import components.step
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("components", "0012_component_image"),
    ]

    operations = [
        migrations.CreateModel(
            name="FootprintImage",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("footprint", models.CharField(
                    max_length=128, verbose_name="Посадочное место")),
                ("key", models.CharField(
                    max_length=128, unique=True,
                    verbose_name="Ключ сопоставления")),
                ("image", models.ImageField(
                    upload_to=components.step.upload_path,
                    verbose_name="Изображение")),
                ("source_name", models.CharField(
                    blank=True, default="", max_length=255,
                    help_text="Имя STEP-файла; сам файл не хранится",
                    verbose_name="Из какого файла")),
                ("author", models.CharField(blank=True, default="",
                                            max_length=150,
                                            verbose_name="Кто загрузил")),
                ("created", models.DateTimeField(auto_now_add=True,
                                                 verbose_name="Когда")),
            ],
            options={
                "db_table": "oy_footprint_image",
                "ordering": ("footprint",),
                "verbose_name": "Картинка посадочного места",
                "verbose_name_plural": "Картинки посадочных мест",
            },
        ),
    ]
