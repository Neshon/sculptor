"""Таблицы Django с префиксом ``oy_`` — под префиксом приложения ``components_``.

Пять таблиц: журнал изменений, картинки посадочных мест, выпадающие списки
(столбцы и значения), заявки на рендер. Только переименование
(``ALTER TABLE … RENAME``, в одной транзакции): данные, ключи и связи
остаются, identity-последовательности ключей принадлежат таблице и
переезжают вместе с ней. Имена индексов и ограничений (``oy_…_pkey`` и
т. п.) остаются прежними — на работу это не влияет.

Откат — ``migrate components 0018``: переименует обратно.
Подробности и порядок на сервере — docs/schema-history.md.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('components', '0018_option_field_names'),
    ]

    operations = [
        migrations.AlterModelTable(
            name='componentchange',
            table='components_component_change',
        ),
        migrations.AlterModelTable(
            name='footprintimage',
            table='components_footprint_image',
        ),
        migrations.AlterModelTable(
            name='optionfield',
            table='components_option_field',
        ),
        migrations.AlterModelTable(
            name='optionvalue',
            table='components_option_value',
        ),
        migrations.AlterModelTable(
            name='steprenderjob',
            table='components_step_render_job',
        ),
    ]
