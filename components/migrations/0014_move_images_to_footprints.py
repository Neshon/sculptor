"""Перенос картинок компонентов к их посадочным местам.

Раньше картинка заводилась на каждый компонент (``oy_component_image``),
теперь — на посадочное место (``oy_footprint_image``). Здесь старые записи
сворачиваются в новые по Allegro PCB Footprint своих компонентов.

Файлы не копируются и не переносятся: новая запись ссылается на тот же
путь, что и старая. Файловые операции в миграции — лишний риск, а
раскладка по папкам выровняется сама при следующей загрузке модели
(``render_step_images --replace``).

Что при переносе теряется, и почему это не страшно:

* если у нескольких компонентов общий footprint, остаётся самая свежая
  картинка — у них и так был один и тот же рендер;
* картинки компонентов без посадочного места не переносятся: хранить их
  теперь негде. Это замены и неразведённые позиции — заменам картинку
  даёт основной компонент по OY ID, а неразведённым она пока не нужна.
  Их файлы остаются на диске, на них просто никто не ссылается.

Таблицы компонентов ведёт не Django, и какой-то из них может не быть в
этой базе. Каждое обращение к ней — в своей точке сохранения: иначе
первый же неудачный запрос оборвал бы всю миграцию.
"""

from django.db import DatabaseError, migrations, transaction

# Заглушки, которыми в базе закрывают незаполненные поля. Импортировать
# components.matching сюда не стоит: миграция должна работать и тогда,
# когда код приложения уйдёт вперёд
PLACEHOLDERS = {"", "-", "--", "---", "?", "n/a", "na", "none", "нет"}


def forward(apps, schema_editor):
    ComponentImage = apps.get_model("components", "ComponentImage")
    FootprintImage = apps.get_model("components", "FootprintImage")

    by_table = {}
    for model in apps.get_app_config("components").get_models():
        names = {field.name for field in model._meta.get_fields()}
        if "allegro_pcb_footprint" in names:
            by_table[model._meta.db_table] = model

    moved = set()
    # свежие первыми: при общем footprint остаётся последняя загрузка
    for old in ComponentImage.objects.order_by("-created", "-id"):
        model = by_table.get(old.component_table)
        if model is None or not old.image:
            continue
        try:
            with transaction.atomic():
                footprint = (model.objects.filter(pk=old.component_id)
                             .values_list("allegro_pcb_footprint", flat=True)
                             .first())
        except DatabaseError:
            continue

        footprint = (footprint or "").strip()
        key = footprint.lower()
        if key in PLACEHOLDERS or key in moved:
            continue

        new = FootprintImage.objects.create(
            footprint=footprint[:128], key=key[:128],
            image=old.image.name, source_name=old.source_name,
            author=old.author)
        # auto_now_add поставил текущее время — возвращаем настоящее
        FootprintImage.objects.filter(pk=new.pk).update(created=old.created)
        moved.add(key)


class Migration(migrations.Migration):

    dependencies = [
        ("components", "0013_footprint_image"),
    ]

    operations = [
        # обратного пути нет: из картинки места не восстановить, каким
        # компонентам она была записана, — но и нужды в нём нет
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
