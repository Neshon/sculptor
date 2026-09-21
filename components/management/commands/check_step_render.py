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

    def add_arguments(self, parser):
        parser.add_argument(
            "--render", action="store_true",
            help="Нарисовать пробную фигуру: проверить не только пакеты, "
                 "но и то, что VTK есть где рисовать")

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
            if options["render"]:
                self._check_render()
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

    def _check_render(self):
        """Рисует шар в файл — так же, как рисуется модель.

        Импорт пакетов проходит и там, где рисовать нечем: на сервере без
        экрана VTK загружается, а падает только при создании окна, даже
        невидимого. Эта проверка доходит ровно до того места, где падает
        настоящий рендер.

        Экран поднимается так же, как перед настоящим рендером
        (:func:`components.step.ensure_display`), — проверка идёт тем же
        путём, что и работа.
        """
        import os
        import tempfile
        from pathlib import Path

        from components.step import ensure_display

        self.stdout.write("")
        self.stdout.write("Пробный рендер:")
        before = os.environ.get("DISPLAY")
        ready = ensure_display()
        after = os.environ.get("DISPLAY")
        if before:
            self.stdout.write(f"  экран: {before}")
        elif ready and after:
            self.stdout.write(f"  экрана не было — поднят виртуальный {after}")
        else:
            self.stdout.write(self.style.ERROR(
                "  экрана нет, и виртуальный (Xvfb) не запустился — "
                "образ собран без слоя рендера?"))
            return

        try:
            import pyvista as pv

            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "probe.png"
                plotter = pv.Plotter(off_screen=True, window_size=(200, 150))
                plotter.add_mesh(pv.Sphere())
                plotter.screenshot(str(target))
                plotter.close()
                size = target.stat().st_size
        except Exception as exc:  # noqa: BLE001 — ровно это и проверяем
            self.stdout.write(self.style.ERROR(f"  не удалось: {exc}"))
            self.stdout.write(
                "  Экран есть, а нарисовать не вышло — чаще всего нет "
                "программного OpenGL (libgl1-mesa-dri, libglx-mesa0).")
            return

        self.stdout.write(self.style.SUCCESS(
            f"  получилось: картинка {size} байт. Рендер моделей работает."))
