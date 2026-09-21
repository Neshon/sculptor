"""Картинки посадочных мест из папки со STEP-моделями.

Модели лежат отдельной папкой и названы по посадочному месту:
``SODFL100X250X050.step``. В библиотеке оно записано в поле **Allegro PCB
Footprint**. Картинка из модели сохраняется у посадочного места
(:class:`components.models.FootprintImage`), и все компоненты с этим
footprint показывают её сами — связывать их ни с чем не нужно.

    python manage.py render_step_images
    python manage.py render_step_images --dir model --dry-run
    python manage.py render_step_images --replace

Одна модель — один рендер — одна запись, сколько бы компонентов на этом
месте ни стояло. Новые компоненты с тем же footprint получат картинку
сразу, в том числе заведённые в базу другими программами: поиск идёт в
момент показа карточки.

Сопоставление — по имени файла без расширения и значению Allegro PCB
Footprint, без учёта регистра и внешних пробелов. Ничего умнее
намеренно: совпадение «примерно» здесь хуже, чем его отсутствие —
картинка чужого посадочного места выглядит как правильная, и заметить
подмену можно, только открыв модель.

Модели без компонента тоже рендерятся: посадочное место могут завести
завтра, и картинка будет ждать его готовой. В отчёте они перечислены
отдельно — чаще это всё-таки опечатка в имени файла или в библиотеке.

По умолчанию посадочные места, у которых картинка уже есть, пропускаются:
команду запускают повторно, когда в папку добавили новые модели, и
перерисовывать готовые незачем. ``--replace`` перерисовывает всё.

В конце выводятся два списка: модели, которым не нашлось компонента, и
посадочные места библиотеки, у которых нет картинки. Второй — рабочий
результат: по нему видно, какие модели ещё нужны.
"""

from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from components.db import unavailable
from components.lookup import searchable
from components.models import FootprintImage
from components.step import (SUFFIXES, StepRenderError, normalize_footprint,
                             render_file)

DEFAULT_DIR = "model"

# Поле, по которому модель находит свои компоненты
MATCH_FIELD = "allegro_pcb_footprint"

# Сколько посадочных мест без картинки показывать в конце. Их бывают
# сотни — длинный список никто не читает, а короткий видно целиком
UNMATCHED_LIMIT = 40

# Имя оставлено для тестов и старых вызовов: сопоставление то же самое
normalize = normalize_footprint


def footprints_index():
    """Посадочные места библиотеки: ``{ключ: (как записано, сколько)}``.

    Один проход по таблицам с колонкой Allegro PCB Footprint — у замен её
    нет. Читается одна колонка: полные записи здесь не нужны, а таблиц
    двадцать семь.
    """
    counts = defaultdict(int)
    shown = {}
    for category in searchable():
        if not hasattr(category.model, MATCH_FIELD):
            continue
        with unavailable(category.table):
            values = (category.model.objects
                      .exclude(**{f"{MATCH_FIELD}__isnull": True})
                      .exclude(**{MATCH_FIELD: ""})
                      .order_by()
                      .values_list(MATCH_FIELD, flat=True))
            for value in values:
                key = normalize(value)
                if key and key != "---":
                    counts[key] += 1
                    shown.setdefault(key, value.strip())
    return {key: (shown[key], counts[key]) for key in counts}


def models_in(directory):
    """STEP-файлы папки, по одному на посадочное место.

    Если рядом лежат ``SLP2510P8.step`` и ``SLP2510P8.stp``, берётся
    первый по имени, а про второй говорится отдельно: молча выбрать один
    из двух — значит однажды удивиться, почему картинка не та.
    """
    found, duplicates = {}, []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() not in SUFFIXES:
            continue
        key = normalize(path.stem)
        if key in found:
            duplicates.append(path)
            continue
        found[key] = path
    return found, duplicates


class Command(BaseCommand):
    help = ("Делает картинки посадочных мест из STEP-моделей в папке, "
            "сопоставляя имя файла с полем Allegro PCB Footprint")

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir", default=DEFAULT_DIR,
            help=f"Папка со STEP-моделями (по умолчанию {DEFAULT_DIR})")
        parser.add_argument(
            "--replace", action="store_true",
            help="Перерисовать и те места, у которых картинка уже есть")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Только показать, что будет сделано")
        parser.add_argument(
            "--author", default="render_step_images",
            help="Кого записать автором картинок")

    def handle(self, *args, **options):
        directory = Path(options["dir"])
        if not directory.is_dir():
            raise CommandError(f"Папки {directory} нет")

        models, duplicates = models_in(directory)
        if not models:
            raise CommandError(
                f"В {directory} нет файлов STEP (ищем {', '.join(SUFFIXES)})")

        index = footprints_index()
        ready = set(FootprintImage.objects.values_list("key", flat=True))
        self.stdout.write(f"Моделей в папке: {len(models)}")
        self.stdout.write(f"Посадочных мест в библиотеке: {len(index)}, "
                          f"с картинкой: {len(ready & set(index))}")
        self.stdout.write("")

        rendered, skipped, failed = 0, 0, []
        lonely_models = []

        for key, path in models.items():
            shown, used = index.get(key, (path.stem, 0))
            if not used:
                lonely_models.append(path.name)

            if key in ready and not options["replace"]:
                skipped += 1
                continue

            where = f"{used} компонентов" if used else "компонентов пока нет"
            if options["dry_run"]:
                self.stdout.write(f"  {path.name} → {shown} ({where})")
                rendered += 1
                continue

            try:
                png, triangles, colors = render_file(path)
            except StepRenderError as exc:
                failed.append((path.name, str(exc)))
                self.stdout.write(self.style.ERROR(f"  {path.name}: {exc}"))
                continue

            FootprintImage.store(shown, png, source_name=path.name,
                                 author=options["author"])
            ready.add(key)
            rendered += 1
            self.stdout.write(self.style.SUCCESS(
                f"  {path.name} → {shown} ({where}; {triangles} "
                f"треугольников, {colors} цветов)"))

        self._report(options, index, ready, rendered, skipped, failed,
                     lonely_models, duplicates)

    def _report(self, options, index, ready, rendered, skipped, failed,
                lonely_models, duplicates):
        """Итог и два списка несопоставленного."""
        self.stdout.write("")
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING(
                f"Пробный запуск: отрисовано было бы моделей — {rendered}"))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Отрисовано моделей: {rendered}"))
        if skipped:
            self.stdout.write(
                f"Пропущено (картинка уже есть): {skipped}. "
                f"Перерисовать — с ключом --replace")

        if duplicates:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "Файлы с тем же именем, но другим расширением — не брались:"))
            for name in duplicates:
                self.stdout.write(f"  {name.name}")

        if failed:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR(
                f"Не прочитались ({len(failed)}):"))
            for name, error in failed:
                self.stdout.write(f"  {name}: {error}")

        self.stdout.write("")
        if lonely_models:
            self.stdout.write(self.style.WARNING(
                f"Моделей без компонента ({len(lonely_models)}) — такого "
                f"Allegro PCB Footprint в библиотеке нет, картинка сохранена "
                f"впрок:"))
            for name in lonely_models:
                self.stdout.write(f"  {name}")
        else:
            self.stdout.write("Все модели нашли своих компонентов.")

        # Посадочные места без картинки — уже с учётом того, что сделано
        # в этом запуске. Список урезается: он для того, чтобы понять
        # масштаб и заказать недостающее, а не для полной выгрузки
        lonely = sorted((shown, used) for key, (shown, used) in index.items()
                        if key not in ready)
        self.stdout.write("")
        if not lonely:
            self.stdout.write(
                "У всех посадочных мест библиотеки есть картинка.")
            return

        self.stdout.write(self.style.WARNING(
            f"Посадочных мест без картинки ({len(lonely)}):"))
        # сначала самые ходовые: их картинка закроет больше карточек
        for shown, used in sorted(lonely, key=lambda row: -row[1])[:UNMATCHED_LIMIT]:
            self.stdout.write(f"  {shown} — {used} компонентов")
        if len(lonely) > UNMATCHED_LIMIT:
            self.stdout.write(f"  … и ещё {len(lonely) - UNMATCHED_LIMIT}")
