"""Действия с изображениями — в журнале изменений.

Новое событие «Изображение» у записи журнала: картинку посадочного места
загрузили, заменили или удалили из карточки компонента. Значения прежних
событий не меняются.

У заявки на рендер — компонент, из карточки которого её отправили: рендер
идёт в фоне, и запись в журнал ставится, когда он удался, — к этому
моменту запрос давно закончился, и знать компонент больше неоткуда.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("components", "0016_step_render_job"),
    ]

    operations = [
        migrations.AlterField(
            model_name="componentchange",
            name="action",
            field=models.CharField(
                choices=[("created", "Добавлен"), ("updated", "Изменён"),
                         ("deleted", "Удалён"),
                         ("duplicate", "Добавлен как дубль"),
                         ("image", "Изображение")],
                default="updated", max_length=16,
                verbose_name="Что произошло"),
        ),
        migrations.AddField(
            model_name="steprenderjob",
            name="component_table",
            field=models.CharField(blank=True, default="", max_length=64,
                                   verbose_name="Таблица компонента"),
        ),
        migrations.AddField(
            model_name="steprenderjob",
            name="component_id",
            field=models.IntegerField(blank=True, null=True,
                                      verbose_name="Ключ компонента"),
        ),
    ]
