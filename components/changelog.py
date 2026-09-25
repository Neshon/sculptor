"""История изменений проекта — CHANGELOG.md на сайте.

Версия в шапке открывает окно «Что нового» (base.html), без HTMX —
страницу ``/components/changelog/``. Текст один — CHANGELOG.md в корне
проекта: второй копии для сайта нет, иначе она отставала бы от файла.

Библиотеки Markdown в проекте нет, и ради одного файла она не нужна:
разбирается ровно то подмножество, которым CHANGELOG написан, —
заголовки версий (``##``) и разделов (``###``), абзацы, списки ``-`` и
``1.`` с продолжением строк отступом, ``код`` и **жирный**. Всё прочее
выводится как текст, а не теряется. Появится в файле новая разметка —
её надо добавить сюда, тест покажет где (components/tests/test_site.py).
"""

import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.utils.html import escape
from django.utils.safestring import mark_safe

VERSION_RE = re.compile(r"^##\s+(?P<number>.+?)\s*$")
SECTION_RE = re.compile(r"^###\s+(?P<title>.+?)\s*$")
BULLET_RE = re.compile(r"^-\s+(?P<text>.*)$")
NUMBERED_RE = re.compile(r"^\d+\.\s+(?P<text>.*)$")
CODE_RE = re.compile(r"`([^`]+)`")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

# Раздел для тех, кто обновляет сервер, а не для тех, кто пользуется сайтом:
# в окне он свёрнут, чтобы «Ручных шагов нет» не повторялось под каждой
# версией
UPDATE_SECTION = "Обновление"


def inline(text):
    """Строка Markdown в безопасный HTML: сначала экранирование, потом разметка.

    Порядок важен: разметка вставляется в уже экранированный текст, поэтому
    угловая скобка из CHANGELOG не станет тегом. Код обрабатывается раньше
    жирного — звёздочки внутри `кода` должны остаться звёздочками.
    """
    parts = CODE_RE.split(escape(text))
    for index, part in enumerate(parts):
        if index % 2:
            parts[index] = f"<code>{part}</code>"
        else:
            parts[index] = BOLD_RE.sub(r"<strong>\1</strong>", part)
    return mark_safe("".join(parts))


def parse(text):
    """Разбирает CHANGELOG: ``(вступление, версии)``.

    Вступление — блоки до первой версии. Версия —
    ``{"number", "sections": [{"title", "blocks"}]}``, блок —
    ``{"kind": "p" | "ul" | "ol", "items": [html]}`` (у абзаца один
    элемент). Заголовок первого уровня пропускается: это имя файла, а не
    содержание. Порядок — как в файле, новые версии сверху.
    """
    intro, versions = [], []
    blocks = intro
    block = None

    def close():
        nonlocal block
        block = None

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            close()
            continue
        if line.startswith("# "):
            close()
            continue
        if match := VERSION_RE.match(line):
            close()
            section = {"title": "", "blocks": []}
            versions.append({"number": match["number"], "sections": [section]})
            blocks = section["blocks"]
            continue
        if versions and (match := SECTION_RE.match(line)):
            close()
            section = {"title": match["title"], "blocks": []}
            versions[-1]["sections"].append(section)
            blocks = section["blocks"]
            continue

        bullet = BULLET_RE.match(line)
        numbered = NUMBERED_RE.match(line)
        if bullet or numbered:
            kind = "ul" if bullet else "ol"
            item = (bullet or numbered)["text"]
            if block is None or block["kind"] != kind:
                block = {"kind": kind, "items": []}
                blocks.append(block)
            block["items"].append(item)
        elif line.startswith(" ") and block is not None and block["kind"] != "p":
            # продолжение пункта списка — строка с отступом
            block["items"][-1] += " " + stripped
        elif block is not None and block["kind"] == "p":
            block["items"][-1] += " " + stripped
        else:
            block = {"kind": "p", "items": [stripped]}
            blocks.append(block)

    for group in [intro, *(s["blocks"] for v in versions for s in v["sections"])]:
        for item in group:
            item["items"] = [inline(text) for text in item["items"]]
    # пустой раздел без заголовка остаётся, только если у версии что-то
    # написано до первого «###»
    for version in versions:
        version["sections"] = [s for s in version["sections"]
                               if s["title"] or s["blocks"]]
        for section in version["sections"]:
            section["collapsed"] = section["title"] == UPDATE_SECTION
    return intro, versions


def changelog_path():
    return Path(settings.BASE_DIR) / "CHANGELOG.md"


def load():
    """``(вступление, версии)`` из CHANGELOG.md; файла нет — пусто.

    Разбор кэшируется до изменения файла: окно открывают из любой страницы,
    а файл меняется только с обновлением сайта.
    """
    path = changelog_path()
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return [], []
    return _load(str(path), stamp)


@lru_cache(maxsize=2)
def _load(path, stamp):
    return parse(Path(path).read_text(encoding="utf-8"))
