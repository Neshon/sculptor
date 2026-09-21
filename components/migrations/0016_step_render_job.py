"""Заявки на рендер картинок посадочных мест: ``oy_step_render_job``.

Рендер уходит в фон через фреймворк задач Django, а состояние, которое
видит человек, — «готовится», «готово», «не удалось» — хранится здесь.
Своё, а не бэкенда задач: встроенный бэкенд результаты не хранит, а бэкенд
можно сменить настройкой.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("components", "0015_delete_component_image"),
    ]

    operations = [
        migrations.CreateModel(
            name="StepRenderJob",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("key", models.CharField(
                    db_index=True, max_length=128,
                    verbose_name="Ключ посадочного места")),
                ("footprint", models.CharField(
                    max_length=128, verbose_name="Посадочное место")),
                ("source_name", models.CharField(
                    blank=True, default="", max_length=255,
                    verbose_name="Из какого файла")),
                ("step_file", models.CharField(
                    blank=True, default="", max_length=255,
                    verbose_name="Файл в очереди")),
                ("status", models.CharField(
                    choices=[("queued", "в очереди"), ("running", "рисуется"),
                             ("done", "готово"), ("failed", "не удалось"),
                             ("superseded", "заменена новой")],
                    default="queued", max_length=16,
                    verbose_name="Состояние")),
                ("message", models.TextField(blank=True, default="",
                                             verbose_name="Итог")),
                ("author", models.CharField(blank=True, default="",
                                            max_length=150,
                                            verbose_name="Кто загрузил")),
                ("created", models.DateTimeField(auto_now_add=True,
                                                 verbose_name="Когда")),
                ("finished", models.DateTimeField(blank=True, null=True,
                                                  verbose_name="Закончено")),
            ],
            options={
                "db_table": "oy_step_render_job",
                "ordering": ("-created", "-id"),
                "verbose_name": "Рендер картинки",
                "verbose_name_plural": "Рендеры картинок",
            },
        ),
    ]
