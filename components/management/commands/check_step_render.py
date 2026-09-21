"""Проверка окружения рендера STEP.

Нужна на один вопрос: «пакеты стоят, а приложение говорит, что их нет».
Почти всегда ответ в том, что *ставили* и *запускают* разными питонами —
или что пакет импортируется, но тянет за собой системную библиотеку,
которой на сервере нет.

Команда отвечает на это прямо: каким интерпретатором она запущена, что
удалось импортировать, а что нет и с какой именно ошибкой. Запускать её
надо ровно так же, как запускается приложение, — тем же manage.py, из того
же окружения, тем же пользователем:

    python manage.py check_step_render
"""

import sys
from pathlib import Path

from django.core.management.base import BaseCommand

# Что именно нужно рендеру. Имя пакета для pip и имя модуля для импорта
# различаются, и это регулярный источник путаницы: ставят cadquery-ocp, а
# импортируется OCP, и «pip show OCP» ничего не находит.
MODULES = (
    ("OCP", "cadquery-ocp"),
    ("pyvista", "pyvista"),
    ("numpy", "numpy"),
    ("vtkmodules", "vtk (приходит зависимостью pyvista)"),
)


class Command(BaseCommand):
    help = "Проверяет, готово ли окружение к рендеру STEP"

    def handle(self, *args, **options):
        self.stdout.write("Интерпретатор:")
        self.stdout.write(f"  {sys.executable}")
        self.stdout.write(f"  версия {sys.version.split()[0]}")
        # Виртуальное окружение: если приложение работает в одном, а pip
        # запускали в другом, видно будет здесь
        prefix = Path(sys.prefix)
        self.stdout.write(f"  окружение {prefix}"
                          + ("" if prefix == Path(sys.base_prefix)
                             else "  (venv)"))
        self.stdout.write("")

        failures = []
        for module, package in MODULES:
            try:
                imported = __import__(module)
            except Exception as exc:
                # Не только ImportError: VTK на некоторых сборках поднимает
                # OSError, а pyvista — собственные исключения
                failures.append((module, package, exc))
                self.stdout.write(self.style.ERROR(f"  {module}: {exc}"))
                continue

            version = getattr(imported, "__version__", "")
            where = getattr(imported, "__file__", "") or "встроенный"
            self.stdout.write(self.style.SUCCESS(
                f"  {module}: {version or 'есть'}"))
            self.stdout.write(f"      {where}")

        self.stdout.write("")
        if not failures:
            self._check_classes()
            return

        self.stdout.write(self.style.WARNING("Чего не хватает и что делать:"))
        for module, package, exc in failures:
            text = str(exc)
            if "No module named" in text:
                self.stdout.write(
                    f"  {module}: пакета нет в этом окружении. Поставьте его "
                    f"тем же питоном, что напечатан выше:")
                self.stdout.write(
                    f"      \"{sys.executable}\" -m pip install {package}")
            elif "libGL" in text or "libX" in text or ".so" in text:
                self.stdout.write(
                    f"  {module}: пакет есть, но ему не хватает системных "
                    f"библиотек. На Debian и Ubuntu:")
                self.stdout.write(
                    "      apt-get install -y libgl1 libxrender1 libxext6 xvfb")
            elif "DLL" in text:
                self.stdout.write(
                    f"  {module}: пакет есть, но не загружается DLL. Обычно "
                    f"это отсутствующий Visual C++ Redistributable или "
                    f"32-битный Python вместо 64-битного.")
            else:
                self.stdout.write(f"  {module}: {text}")

    def _check_classes(self):
        """Проверяет сами классы OpenCascade, а не только модули.

        Импорт ``OCP`` проходит почти всегда, а падает потом конкретное имя:
        сборки пакета переносят классы между модулями, и рендер ломается на
        строке вроде «cannot import name TDF_LabelSequence from OCP.TDF».
        Проверка одних модулей такое пропускала и говорила «всё хорошо» —
        то есть врала ровно в том случае, ради которого её запускают.
        """
        from components.step import OCCT_NAMES, where_is

        self.stdout.write("Классы OpenCascade:")
        missing = []
        for name in OCCT_NAMES:
            module, similar = where_is(name)
            if module:
                self.stdout.write(self.style.SUCCESS(
                    f"  {name}: OCP.{module}"))
            else:
                missing.append((name, similar))
                self.stdout.write(self.style.ERROR(f"  {name}: не найден"))

        self.stdout.write("")
        if not missing:
            self.stdout.write(self.style.SUCCESS(
                "Всё на месте — рендер должен работать."))
            self.stdout.write(
                "Если загрузка STEP всё равно не даёт картинку, дело уже не в "
                "пакетах: смотрите текст ошибки на странице.")
            return

        self.stdout.write(self.style.WARNING(
            "Эти классы в вашей сборке OCP лежат в другом месте."))
        for name, similar in missing:
            self.stdout.write(f"  {name} — похожее рядом:")
            for candidate in similar or ["ничего похожего не нашлось"]:
                self.stdout.write(f"      {candidate}")
        self.stdout.write("")
        self.stdout.write(
            "Добавьте нужный модуль в OCCT_NAMES в components/step.py — "
            "поиск идёт по списку, лишние варианты не мешают.")
