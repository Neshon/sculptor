"""Изображение компонента из STEP-модели: где лежит и как получается.

Картинка нужна, чтобы по карточке было видно, что это за деталь: корпус,
выводы, размер относительно соседей. Раньше это смотрели в CAD или на
сайте производителя.

**STEP-файл не хранится.** Он нужен ровно один раз — чтобы получить
картинку — и после рендера выбрасывается. Хранить его означало бы завести
второе место для моделей рядом с тем, где их ведут конструкторы, и
однажды разойтись с ним: модель там поправят, а здесь останется копия
двухлетней давности. Картинка так не врёт: её видно, и если она устарела,
это заметно сразу.

Рендер устроен так же, как чтение STEP в CAD: модель читается вместе с
цветами (``STEPCAFControl``), разбивается на треугольники и снимается
камерой без экрана. Цвет ищется по цепочке «экземпляр → деталь →
родитель», потому что в сборках его задают на любом из этих уровней.

Библиотеки для этого нужны тяжёлые (OCP — это OpenCascade, сотни
мегабайт), и в основной образ они не входят. Поэтому импорт сделан внутри
функции, а не наверху модуля: без них работает вся остальная система, а
загрузка STEP отвечает понятным «рендер не установлен» вместо пятисот
строк ImportError на старте. Как их поставить — в docs/components.md.
"""

import atexit
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.core.exceptions import ValidationError

# Точность триангуляции в единицах модели. Мельче — дольше и без видимой
# разницы на картинке шириной 800 точек.
LIN_DEFLECTION = 0.1
ANG_DEFLECTION = 0.3

# Если цвет не задан ни на детали, ни на сборке
DEFAULT_COLOR = (0.75, 0.75, 0.75)

SIZE = (800, 600)

# Предел на приходящий файл. Проверяется до чтения содержимого: разбирать
# стомегабайтную сборку, чтобы потом её отклонить, незачем.
MAX_BYTES = 60 * 1024 * 1024

# Расширения, которые вообще пробуем читать. Это подпись на конверте, а не
# проверка содержимого: настоящая проверка — сам чтение файла, и если
# внутри не STEP, читатель об этом скажет.
SUFFIXES = (".step", ".stp")


def normalize_footprint(value):
    """Ключ посадочного места: без регистра и внешних пробелов.

    По нему картинка находит свои компоненты. «SODFL100X250X050» и
    «sodfl100x250x050 » — одно место, а в библиотеке встречается и то, и
    другое: записи заводили разные люди и разные программы.
    """
    return (value or "").strip().lower()


def upload_path(instance, filename):
    """Путь картинки: ``footprint_images/<посадочное место>.png``.

    Одна папка на всю библиотеку и один файл на посадочное место:
    картинка принадлежит ему, а не записи компонента, и у сотни
    компонентов с одним footprint она одна и та же.

    Имя STEP-файла в путь не идёт: у трёх деталей подряд бывает
    ``part.step``. Имя даёт само посадочное место — как оно записано, без
    посторонних знаков (см. :func:`safe_stem`).

    Путь пишется в базу при сохранении, поэтому смена папки касается
    только новых картинок: уже загруженные остаются там, где лежат, и
    продолжают открываться.
    """
    stem = safe_stem(instance.footprint) or safe_stem(instance.key) or "footprint"
    return f"footprint_images/{stem}.png"


def safe_stem(value):
    """Имя файла из произвольной строки.

    Артикулы бывают со слэшами, пробелами и скобками — в имени файла им
    не место. Заменяем всё постороннее дефисом, а не выбрасываем: иначе
    «ABC/123» и «ABC123» дали бы один файл на две разные записи.
    """
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", (value or "").strip())
    return stem.strip("-.")[:120]




def check(upload):
    """Проверяет присланный файл до того, как его начнут читать."""
    if upload.size > MAX_BYTES:
        raise ValidationError(
            f"Файл больше {MAX_BYTES // 1024 // 1024} МБ. Для картинки нужна "
            f"модель детали, а не сборка целиком")

    name = (upload.name or "").lower()
    if not name.endswith(SUFFIXES):
        raise ValidationError("Нужен файл STEP (.step или .stp)")


# Классы OpenCascade, которые нужны рендеру: имя и модули, где его искать.
#
# Модулей у некоторых имён несколько, и это не перестраховка. Сборки
# cadquery-ocp переносят классы между модулями от версии к версии:
# TDF_LabelSequence в одной лежит в OCP.TDF, в другой — в OCP.TColStd, и
# жёсткий импорт ломается при обновлении пакета, хотя сам класс никуда не
# делся. Скрипт, написанный под одну сборку, на другой падает первой же
# строкой импорта — проверять стоит не «стоит ли OCP», а «где в нём то,
# что нам нужно».
OCCT_NAMES = {
    "BRep_Tool": ("BRep",),
    "BRepMesh_IncrementalMesh": ("BRepMesh",),
    "IFSelect_RetDone": ("IFSelect",),
    "Quantity_Color": ("Quantity",),
    "STEPCAFControl_Reader": ("STEPCAFControl",),
    "TCollection_ExtendedString": ("TCollection",),
    "TDF_Label": ("TDF",),
    # Обходим дерево меток итератором, а не последовательностью:
    # TDF_LabelSequence в разных сборках лежит в разных модулях, а в
    # некоторых его нет вовсе — это обёртка над шаблоном C++, и биндинги
    # её экспортируют не всегда. TDF_ChildIterator есть везде и делает то
    # же самое: метки компонентов сборки и подформ детали — это и есть
    # дочерние метки, отобранные по признаку.
    "TDF_ChildIterator": ("TDF",),
    "TDocStd_Document": ("TDocStd",),
    "TopAbs_FACE": ("TopAbs",),
    "TopAbs_REVERSED": ("TopAbs",),
    "TopExp_Explorer": ("TopExp",),
    "TopLoc_Location": ("TopLoc",),
    "TopoDS": ("TopoDS",),
    "XCAFDoc_ColorType": ("XCAFDoc",),
    "XCAFDoc_DocumentTool": ("XCAFDoc",),
}


def _pick(module, name):
    """Достаёт имя из модуля, в том числе изнутри перечисления.

    Значения вроде ``TopAbs_FACE`` в одних сборках лежат прямо в модуле, в
    других — членами класса-перечисления (``TopAbs_ShapeEnum.TopAbs_FACE``).
    Для остального кода разницы нет, поэтому разбираемся с ней здесь.
    """
    found = getattr(module, name, None)
    if found is not None:
        return found
    for attribute in vars(module).values():
        if isinstance(attribute, type):
            found = getattr(attribute, name, None)
            if found is not None:
                return found
    return None



def occt_call(owner, name):
    """Статический метод OpenCascade по имени без суффикса.

    Биндинги OCP дописывают ``_s`` к статическим методам не всегда: где-то
    ``TopoDS.Face_s``, где-то просто ``TopoDS.Face``. Зависит это от того,
    есть ли у класса одноимённый нестатический метод, то есть меняется от
    версии к версии и от класса к классу. Прибивать одно из написаний в
    коде значит ломаться на каждой второй сборке.
    """
    for candidate in (f"{name}_s", name):
        found = getattr(owner, candidate, None)
        if found is not None:
            return found
    raise StepRenderError(
        f"В этой сборке OCP у {getattr(owner, '__name__', owner)} нет "
        f"метода {name} — ни как {name}_s, ни как {name}")


def occt_classes():
    """Ищет нужные классы OpenCascade. ``{имя: объект}``.

    Поднимает :class:`StepRenderError` с указанием, чего именно не нашлось
    и что в этих модулях есть похожего: по такому сообщению правится одна
    строка в :data:`OCCT_NAMES`, а не гадается версия пакета.
    """
    import importlib

    found, missing = {}, []
    for name, modules in OCCT_NAMES.items():
        for module_name in modules:
            try:
                module = importlib.import_module(f"OCP.{module_name}")
            except ImportError:
                continue
            value = _pick(module, name)
            if value is not None:
                found[name] = value
                break
        else:
            missing.append((name, modules))

    if missing:
        raise StepRenderError(
            "Пакет OCP установлен, но в этой его сборке не нашлось: "
            + ", ".join(f"{name} (искали в {', '.join(modules)})"
                        for name, modules in missing)
            + ". Сообщите администратору")
    return found


def where_is(name):
    """В каком модуле лежит класс и что рядом с ним похожего.

    Нужна одной команде — ``check_step_render``. Возвращает
    ``(модуль или None, [похожие имена])``.
    """
    import importlib

    similar = []
    stem = name.split("_", 1)[0]
    for module_name in OCCT_NAMES.get(name, ()):
        try:
            module = importlib.import_module(f"OCP.{module_name}")
        except ImportError:
            continue
        if _pick(module, name) is not None:
            return module_name, []
        # Сначала имена, похожие на искомое по хвосту («…Sequence»,
        # «…Iterator»), потом просто соседи по модулю. Прошлый вариант
        # отбирал по началу имени и обрезал список на двадцати — до
        # интересного места он не доходил, и подсказка была бесполезной.
        tail = name.split("_", 1)[-1]
        names = [attr for attr in dir(module) if not attr.startswith("_")]
        close = [f"OCP.{module_name}.{attr}" for attr in names
                 if tail.lower() in attr.lower()]
        similar += close or [f"OCP.{module_name}.{attr}" for attr in names
                             if attr.startswith(stem)][:20]
    return None, similar[:40]


def queue_path(name):
    """Полный путь файла в очереди на рендер.

    Имя приходит из записи в базе, и выйти за пределы каталога очереди оно
    не должно, даже если запись испорчена: в пути остаётся только имя
    файла, без каталогов.
    """
    from django.conf import settings

    return Path(settings.STEP_QUEUE_DIR) / Path(name or "").name


def save_to_queue(upload):
    """Кладёт присланный STEP в каталог очереди. Возвращает имя файла.

    Имя случайное, а не исходное: две модели ``part.step``, присланные
    подряд, не должны затирать друг друга, пока ждут воркера.
    """
    import uuid

    name = f"{uuid.uuid4().hex}.step"
    path = queue_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    upload.seek(0)
    with path.open("wb") as handle:
        for chunk in upload.chunks():
            handle.write(chunk)
    return name


# Виртуальный экран, поднятый этим процессом. Один на процесс: воркер
# рисует много моделей подряд, и запускать экран на каждую незачем
_XVFB = None


def ensure_display(timeout=15):
    """Даёт VTK экран, если его нет. ``True`` — рисовать есть где.

    На сервере без экрана VTK падает при первой же попытке создать окно,
    даже невидимое: сначала ищет X-сервер по ``DISPLAY``, потом EGL и
    OSMesa, и если ничего нет — рисовать ему нечем. Здесь поднимается
    виртуальный X-сервер (Xvfb) прямо из процесса, который будет рисовать.

    Прежде экран поднимала обёртка ``xvfb-run`` вокруг команды. Этого
    мало: рисуют и воркер, и отдельный процесс, и команда проверки, и
    стоит одному из них запуститься без обёртки — рендер падает. Когда
    экран поднимает сам рендер, кто и как его запустил, неважно.

    Номер экрана выбирает Xvfb (``-displayfd``) — так два процесса,
    рисующие одновременно, не столкнутся на одном номере. В Windows и там,
    где экран уже есть, ничего не делается.
    """
    global _XVFB

    if os.name == "nt" or os.environ.get("DISPLAY"):
        return True
    binary = shutil.which("Xvfb")
    if not binary:
        return False

    import select

    read_fd, write_fd = os.pipe()
    try:
        process = subprocess.Popen(
            [binary, "-displayfd", str(write_fd), "-screen", "0",
             "1280x1024x24", "-nolisten", "tcp"],
            pass_fds=(write_fd,), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
    finally:
        os.close(write_fd)

    # Xvfb пишет номер экрана, когда готов принимать клиентов. Не дождались
    # или он умер — рисовать не на чем, и лучше сказать это сразу
    number = ""
    with os.fdopen(read_fd) as reader:
        if select.select([reader], [], [], timeout)[0]:
            number = reader.readline().strip()
    if not number:
        process.kill()
        return False

    os.environ["DISPLAY"] = f":{number}"
    _XVFB = process
    atexit.register(process.terminate)
    return True


class StepRenderError(Exception):
    """Картинку получить не удалось. Текст показывается человеку."""


def render_file(path):
    """Делает PNG из STEP-файла, лежащего на диске.

    Возвращает ``(содержимое файла, сколько треугольников, сколько цветов)``.
    Счётчики идут в сообщение после сохранения: по ним видно, что модель
    прочиталась целиком и цвета в ней были, — пустая серая картинка и
    картинка детали различаются именно этим.

    Сама функция синхронная; из интерфейса её вызывает фоновая задача
    (:mod:`components.tasks`), а в запросе или в отдельном процессе —
    решает настройка DJANGO_TASKS_BACKEND. Деталь рендерится за секунды,
    сборка на сотни тысяч треугольников — заметно дольше, отсюда и
    ограничение на размер файла выше.
    """
    try:
        import numpy as np
        import pyvista as pv
    except ImportError as exc:
        # Текст ошибки показываем как есть, и это важнее вежливой фразы.
        # «Не установлен» — лишь одна из причин, по которым импорт не
        # проходит, и далеко не самая частая. Чаще пакеты стоят, но:
        #   * приложение запущено другим интерпретатором (venv против
        #     системного python) — тогда здесь «No module named 'OCP'»;
        #   * pyvista не может подтянуть VTK, которому на сервере без
        #     экрана нужны libGL и соседи — тогда «libGL.so.1: cannot open
        #     shared object file».
        # Общая формулировка прятала и то, и другое, и починить по ней
        # было нечего. Подробности — manage.py check_step_render.
        raise StepRenderError(
            f"Рендер STEP не запускается ({exc}). Сообщите "
            f"администратору") from exc

    if not ensure_display():
        raise StepRenderError(
            "Рендер недоступен: на сервере нет экрана, а виртуальный "
            "(Xvfb) не запустился. Сообщите администратору")

    # Классы OpenCascade ищутся отдельно: их расположение зависит от сборки
    occt = occt_classes()
    BRep_Tool = occt["BRep_Tool"]
    BRepMesh_IncrementalMesh = occt["BRepMesh_IncrementalMesh"]
    IFSelect_RetDone = occt["IFSelect_RetDone"]
    Quantity_Color = occt["Quantity_Color"]
    STEPCAFControl_Reader = occt["STEPCAFControl_Reader"]
    TCollection_ExtendedString = occt["TCollection_ExtendedString"]
    TDF_Label = occt["TDF_Label"]
    TDF_ChildIterator = occt["TDF_ChildIterator"]
    TDocStd_Document = occt["TDocStd_Document"]
    TopAbs_FACE = occt["TopAbs_FACE"]
    TopAbs_REVERSED = occt["TopAbs_REVERSED"]
    TopExp_Explorer = occt["TopExp_Explorer"]
    TopLoc_Location = occt["TopLoc_Location"]
    TopoDS = occt["TopoDS"]
    XCAFDoc_ColorType = occt["XCAFDoc_ColorType"]
    XCAFDoc_DocumentTool = occt["XCAFDoc_DocumentTool"]

    color_types = (XCAFDoc_ColorType.XCAFDoc_ColorSurf,
                   XCAFDoc_ColorType.XCAFDoc_ColorGen)

    def lin_to_srgb(value):
        # OCCT хранит цвета в линейном RGB, картинке нужен sRGB — без
        # перевода деталь выглядит заметно темнее, чем в CAD
        return (12.92 * value if value <= 0.0031308
                else 1.055 * value ** (1 / 2.4) - 0.055)

    def label_color(label):
        color = Quantity_Color()
        for kind in color_types:
            if color_of(label, kind, color):
                return tuple(lin_to_srgb(v) for v in
                             (color.Red(), color.Green(), color.Blue()))
        return None

    def child_labels(label, keep):
        """Дочерние метки, отобранные признаком ``keep``.

        Замена GetSubShapes/GetComponents/GetFreeShapes: те требуют
        TDF_LabelSequence, которого в некоторых сборках OCP нет. Результат
        тот же — эти вызовы и возвращают дочерние метки нужного вида.
        """
        found = []
        walker = TDF_ChildIterator(label, False)
        while walker.More():
            child = walker.Value()
            if keep(child):
                found.append(child)
            walker.Next()
        return found

    def contains(container, face):
        """Лежит ли грань внутри тела или оболочки."""
        if container.ShapeType() == TopAbs_FACE:
            return False
        walker = TopExp_Explorer(container, TopAbs_FACE)
        while walker.More():
            if walker.Current().IsSame(face):
                return True
            walker.Next()
        return False

    points, faces, colors = [], [], []
    offset = 0

    def add_part(label, location, color):
        nonlocal offset
        shape = shape_of(label)
        BRepMesh_IncrementalMesh(shape, LIN_DEFLECTION, False,
                                 ANG_DEFLECTION, True)

        # цвета отдельных граней, если они заданы
        face_colors = []
        for sub in child_labels(label, is_sub_shape):
            found = label_color(sub)
            if found:
                face_colors.append((shape_of(sub), found))

        walker = TopExp_Explorer(shape, TopAbs_FACE)
        while walker.More():
            face = face_of(walker.Current())
            walker.Next()

            face_color = color
            for sub_shape, sub_color in face_colors:
                if sub_shape.IsSame(face) or contains(sub_shape, face):
                    face_color = sub_color
                    break

            face_location = TopLoc_Location()
            triangulation = triangulation_of(face, face_location)
            if triangulation is None:
                continue
            transform = location.Multiplied(face_location).Transformation()

            count = triangulation.NbNodes()
            nodes = [triangulation.Node(i).Transformed(transform)
                     for i in range(1, count + 1)]
            points.extend((p.X(), p.Y(), p.Z()) for p in nodes)

            flipped = face.Orientation() == TopAbs_REVERSED
            for i in range(1, triangulation.NbTriangles() + 1):
                triangle = triangulation.Triangle(i)
                a, b, c = (triangle.Value(k) - 1 + offset for k in (1, 2, 3))
                if flipped:
                    b, c = c, b
                faces.append((3, a, b, c))
                colors.append(face_color)
            offset += count

    def walk(label, location, parent_color):
        if is_reference(label):
            referred = TDF_Label()
            referred_shape(label, referred)
            moved = location.Multiplied(location_of(label))
            # приоритет: цвет экземпляра, затем детали, затем родителя
            color = (label_color(label) or label_color(referred)
                     or parent_color)
            walk(referred, moved, color)
        elif is_assembly(label):
            color = label_color(label) or parent_color
            for part in child_labels(label, is_component):
                walk(part, location, color)
        else:
            add_part(label, location, label_color(label) or parent_color)

    with tempfile.TemporaryDirectory() as tmp:
        step_path = Path(path)

        document = TDocStd_Document(TCollection_ExtendedString("doc"))
        reader = STEPCAFControl_Reader()
        reader.SetColorMode(True)
        reader.SetNameMode(True)
        if reader.ReadFile(str(step_path)) != IFSelect_RetDone:
            raise StepRenderError(
                "Файл не читается как STEP — проверьте, что это модель, а не "
                "архив или чертёж")
        reader.Transfer(document)

        shape_tool = occt_call(XCAFDoc_DocumentTool, "ShapeTool")(
            document.Main())
        color_tool = occt_call(XCAFDoc_DocumentTool, "ColorTool")(
            document.Main())

        # Имена методов разбираем здесь, один раз. Вложенные функции выше
        # видят эти переменные: замыкание разрешается в момент вызова, а
        # вызываются они ниже, когда присваивание уже прошло.
        shape_of = occt_call(shape_tool, "GetShape")
        is_reference = occt_call(shape_tool, "IsReference")
        referred_shape = occt_call(shape_tool, "GetReferredShape")
        location_of = occt_call(shape_tool, "GetLocation")
        is_assembly = occt_call(shape_tool, "IsAssembly")
        is_component = occt_call(shape_tool, "IsComponent")
        is_sub_shape = occt_call(shape_tool, "IsSubShape")
        is_shape = occt_call(shape_tool, "IsShape")
        is_free = occt_call(shape_tool, "IsFree")
        color_of = occt_call(color_tool, "GetColor")
        face_of = occt_call(TopoDS, "Face")
        triangulation_of = occt_call(BRep_Tool, "Triangulation")

        # Корни: дочерние метки самого инструмента форм, которые ни в что
        # не входят. Это и есть то, что отдаёт GetFreeShapes
        roots = child_labels(
            shape_tool.Label(),
            lambda label: is_shape(label) and is_free(label))
        for root in roots:
            walk(root, TopLoc_Location(), DEFAULT_COLOR)

        if not faces:
            raise StepRenderError(
                "В файле не нашлось геометрии: получилось ноль треугольников")

        mesh = pv.PolyData(np.array(points), np.array(faces).ravel())
        mesh.cell_data["rgb"] = ((np.array(colors) * 255)
                                 .clip(0, 255).astype(np.uint8))

        png_path = Path(tmp) / "model.png"
        plotter = pv.Plotter(off_screen=True, window_size=SIZE)
        plotter.set_background("white")
        plotter.add_mesh(mesh, scalars="rgb", rgb=True, smooth_shading=True)
        # параллельная проекция: деталь на картинке не «заваливается», и
        # соседние карточки сравнимы между собой
        plotter.enable_parallel_projection()
        try:
            plotter.screenshot(str(png_path))
        except Exception as exc:  # pyvista поднимает своё на каждый случай
            raise StepRenderError(
                f"Не удалось нарисовать картинку: {exc}") from exc
        finally:
            plotter.close()

        found_colors = {tuple(c) for c in mesh.cell_data["rgb"]}
        return png_path.read_bytes(), mesh.n_cells, len(found_colors)
