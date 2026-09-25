"""Подбор похожего артикула, когда точного совпадения нет.

Артикул один и тот же, а записан иначе: «2N7002KTB_R1» в задаче против
«2N7002KTB» в библиотеке — суффикс катушки, а деталь одна. Подбор нужен в
трёх местах: предположения при импорте ссылок трекера (``links``),
подсказки для строк BOM без пары (``boards``) и отчёт о записях одного
артикула, заведённых по-разному (``duplicates``). Правила у них должны
совпадать, поэтому они собраны здесь.

Подбор только предлагает. Связь ставит человек: ложная связь в составе
платы хуже её отсутствия.

Нестрогое сравнение — ``rapidfuzz``. Раньше здесь был ``difflib``, и он
был настолько медленным, что артикулы сравнивались только с теми, что
начинаются с тех же четырёх символов, и не больше четырёхсот раз на кусок
названия. Опечатка в начале номера при этом не находилась никогда, а в
большой корзине (типовые резисторы) до нужного артикула дело могло не
дойти. ``rapidfuzz`` проходит всю библиотеку за миллисекунды, и оба
ограничения сняты.
"""

import re

from rapidfuzz import fuzz, process

from .matching import usable
from .refs import component_url
from .registry import scan

# ниже этой похожести предлагать бессмысленно — будет шум
THRESHOLD = 0.75

# с такой оценкой предположение считается уверенным: дальше не ищем
CONFIDENT = 0.9

# Артикул без разделителей короче этого нестрого не сравнивается: у
# трёхзначного «куска» три четверти совпадения найдутся с чем угодно
MIN_CORE = 4

# Разделители: пробел, дефис и тире, подчёркивание, косая черта. Они же
# стоят между основой артикула и суффиксом упаковки: «MMBT3904-7-F»,
# «2N7002KTB_R1», «LM5066IPMHE/NOPB».
#
# Только они, а не «всё, что не латиница и не цифра». В отечественных
# артикулах запятая — десятичная, а кириллица — часть номинала:
# «Р1-12-0,062-5,1 кОм» и «Р1-12-0,062-51 кОм» — разные резисторы, как и
# «1,1 Ом» и «1,1 кОм». Выбрасывая запятую и кириллицу, подбор склеивал
# их в «одну запись с другими разделителями». Точка тоже значима: бывает
# десятичной («0.1»), а в номере ТУ стоит всегда одинаково.
# \u2010–\u2015 — типографские дефисы и тире: их вставляет Word
SEPARATOR = re.compile(r"[\s\-\u2010-\u2015_/]+")

SAME = "тот же артикул"
SEPARATORS = "запись отличается только разделителями"
EXTRA_SUFFIX = "в библиотеке без суффикса"
LONGER = "в библиотеке артикул длиннее"
FUZZY = "похожий артикул"


def core(text):
    """Артикул без разделителей, в верхнем регистре: «2N7002K-7» → «2N7002K7».

    Разделители в артикулах ставят кто во что горазд, а деталь одна и та же.
    Что считается разделителем — см. ``SEPARATOR``.
    """
    return SEPARATOR.sub("", text or "").upper()


def library_index():
    """Артикулы всей библиотеки: ``{нормализованный артикул: [(таблица, id)]}``.

    Два словаря — по Vendor PN и по GBT PN. Ключ приведён к нижнему
    регистру, а значение хранит исходное написание артикула и список
    записей: один и тот же артикул встречается в нескольких таблицах
    (например, в основной и в заменах), и решать, что с этим делать,
    должен вызывающий.

    ``{ключ: {"pn": как записано в базе, "targets": [(таблица, id)]}}``
    """
    by_vendor, by_gbt = {}, {}

    for category, values in scan(("id", "vendor_pn", "gbt_pn")):
        target = (category.table, values["id"])
        for field, index in (("vendor_pn", by_vendor), ("gbt_pn", by_gbt)):
            original = usable(values.get(field))
            if not original:
                continue
            entry = index.setdefault(original.lower(),
                                     {"pn": original, "targets": []})
            entry["targets"].append(target)

    return by_vendor, by_gbt


def prepare(index):
    """Готовит артикулы библиотеки к подбору.

    ``index`` — ``(по Vendor PN, по GBT PN)``, словари вида
    ``{ключ: {"pn", "targets"}}``, как их строит :func:`library_index`.
    Второго может и не быть.

    ``by_core`` — все артикулы без разделителей: по нему два самых
    надёжных правила (та же запись и лишний суффикс) находятся поиском по
    словарю, без перебора. ``cores`` и ``entries`` — плоский список для
    нестрогого сравнения, и в нём только Vendor PN. Внутренние номера GBT
    похожи друг на друга по построению: «10RC4-001502-26R» и
    «10RC4-001004-26R» отличаются на пару знаков, а это разные резисторы.
    Нестрогое сравнение предлагало бы соседние номиналы.
    """
    by_core, cores, entries = {}, [], []
    for number, source in enumerate(index):
        for key, entry in source.items():
            key_core = core(key)
            if len(key_core) < MIN_CORE:
                continue
            by_core.setdefault(key_core, []).append((key, entry))
            if number == 0:
                cores.append(key_core)
                entries.append((key, entry))
    return {"by_core": by_core, "cores": cores, "entries": entries}


def _score(candidate_core, key_core):
    """Насколько артикул из библиотеки похож на искомый — по точным правилам.

    Порядок правил — по убыванию доверия: одинаковая запись без
    разделителей надёжнее общего начала, а общее начало надёжнее просто
    похожих строк.
    """
    if candidate_core == key_core:
        return 1.0, SEPARATORS
    if candidate_core.startswith(key_core):
        # «2N7002KTB_R1» против «2N7002KTB»: в библиотеке без суффикса
        # катушки. Подписи причин не говорят «в задаче»: те же правила
        # подбирают и строки BOM
        return 0.95, EXTRA_SUFFIX
    if key_core.startswith(candidate_core):
        return 0.9, LONGER
    return 0.0, ""


def _exact_and_prefix(candidate_core, by_core):
    """Правила, которые находятся поиском по словарю, а не перебором.

    Совпадение без разделителей — один поиск. «Без суффикса» — по одному
    поиску на каждую длину начала, то есть десяток-другой, а не проход по
    всей библиотеке.
    """
    found = []
    for length in range(len(candidate_core), MIN_CORE - 1, -1):
        for key, entry in by_core.get(candidate_core[:length], ()):
            score, reason = _score(candidate_core, core(key))
            if score:
                found.append((key, entry, score, reason))
    return found


def _fuzzy(candidate_core, prepared):
    """Нестрогое сравнение со всей библиотекой.

    ``fuzz.ratio`` по смыслу та же мера, что ``SequenceMatcher.ratio`` из
    difflib, — доля общих символов в обеих строках, только в шкале 0–100.
    Считает она точнее (по наибольшей общей подпоследовательности, а
    difflib — жадными блоками), и оценки изредка расходятся на сотые, но
    прежний порог 0,75 переносится как есть. ``score_cutoff`` отсекает
    непохожее внутри самого rapidfuzz, не возвращая его в Python.
    """
    hits = process.extract(
        candidate_core, prepared["cores"], scorer=fuzz.ratio,
        processor=None, score_cutoff=THRESHOLD * 100, limit=None)
    found = []
    for _, score, position in hits:
        key, entry = prepared["entries"][position]
        found.append((key, entry, round(score / 100, 3), FUZZY))
    return found


def similar(pn, prepared, fuzzy=True):
    """Похожие на ``pn`` артикулы библиотеки: ``[(ключ, запись, оценка, причина)]``.

    Сначала точные правила; нестрогое сравнение — только если они ничего
    не дали: «2N7002KTB_R1» → «2N7002KTB» найдено точно, и перебирать
    похожее сверх этого — только добавлять шум.

    ``fuzzy=False`` оставляет только точные правила. Нестрогое сравнение
    годится там, где рядом с подсказкой человек видит, что искал, — в
    названии задачи трекера. Похожий артикул пассивного компонента почти
    всегда другая деталь: в нём и цифрами, и буквами записаны номинал,
    допуск, диэлектрик и корпус. «WR04X8251FTL» — 8,25 кОм, «WR04X8201FTL»
    — 8,2 кОм; «GRM31CR61E226KE15L» и «…ME15D» различаются допуском, а
    похожесть у таких пар 0,9 и выше.

    Порядок результата не задан: сортирует вызывающий, у него свои правила
    при равной оценке.
    """
    candidate_core = core(pn)
    if len(candidate_core) < MIN_CORE:
        return []

    hits = _exact_and_prefix(candidate_core, prepared["by_core"])
    if not hits and fuzzy:
        hits = _fuzzy(candidate_core, prepared)

    lowered = (pn or "").strip().lower()
    return [(key, entry, score, SAME if key == lowered else reason)
            for key, entry, score, reason in hits]


def hint(entry, score, reason):
    """Подсказка в том виде, в каком её показывают страницы.

    ``{"pn", "targets", "score", "reason", "url", "table", "pk"}``: артикул
    как он записан в библиотеке, все записи с ним и ссылка на первую —
    артикул один, и с его карточки видно остальные. Таблица и ключ
    отдельно — по ним кнопка рядом с подсказкой ставит связь.
    """
    targets = list(entry["targets"])
    table, pk = targets[0]
    return {"pn": entry["pn"], "targets": targets, "score": score,
            "reason": reason, "url": component_url(table, pk),
            "table": table, "pk": pk}


def base_spellings(pn):
    """Начала артикула, отделённые разделителем: возможная основа без суффикса.

    «MMBT3904-7-F» → «MMBT3904-7», «MMBT3904». Отрезается только то, что
    стоит за разделителем: «BAV99W» и «BAV99» — разные корпуса, а не одна
    деталь с суффиксом, и склеивать их нельзя. Начала короче ``MIN_CORE``
    знаков не возвращаются — это уже не артикул.
    """
    text = (pn or "").strip()
    whole = core(text)
    found = []
    for separator in reversed(list(SEPARATOR.finditer(text))):
        head = text[:separator.start()]
        head_core = core(head)
        # разделитель в самом конце («BAV99-») ничего не отрезает
        if len(head_core) >= MIN_CORE and head_core != whole:
            found.append(head)
    return found
