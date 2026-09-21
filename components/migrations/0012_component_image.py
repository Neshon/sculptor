"""Изображения компонентов: таблица ``oy_component_image``.

Картинка делается из STEP-модели, сам STEP не хранится. Файл лежит на
диске (``MEDIA_ROOT``), в базе — только путь, как и у снимков плат.

Связь с компонентом — парой «таблица + ключ», внешнего ключа нет: таблицы
компонентов ведёт не Django. Пара уникальна: картинка на компонент одна.
"""

import components.step
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("components", "0011_capacitor_capacitorreplacement_clock_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ComponentImage",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("component_table", models.CharField(
                    max_length=64, verbose_name="Таблица компонента")),
                ("component_id", models.IntegerField(
                    verbose_name="Ключ компонента")),
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
                "db_table": "oy_component_image",
                "ordering": ("-created", "-id"),
                "verbose_name": "Изображение компонента",
                "verbose_name_plural": "Изображения компонентов",
            },
        ),
        migrations.AddConstraint(
            model_name="componentimage",
            constraint=models.UniqueConstraint(
                fields=("component_table", "component_id"),
                name="component_image_unique_target"),
        ),
    ]
