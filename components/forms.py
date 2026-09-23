"""Форма компонента: поля, проверки, выпадающие списки, секции.

Форма строится из модели на лету: полей много и они у каждой группы свои,
поэтому руками их описывать смысла нет.

Остальные формы лежат рядом с тем, чем пользуются: фильтры списков — в
:mod:`components.filter_forms`, загрузка CSV со ссылками — в
:mod:`components.link_views`, загрузка STEP-модели — в
:mod:`components.image_views`.
"""

from functools import lru_cache

from django import forms
from django.core.validators import RegexValidator, URLValidator
from django.forms import modelform_factory

from .duplicates import find_existing
from .matching import is_placeholder, usable
from .options import table_options

# эти поля заполняются автоматически и в форме не показываются
# OY ID в форму не выводится: он назначается по нумерации и правке не
# подлежит. В карточке правки он показан в шапке, как справка.
EXCLUDED = ("id", "created", "author", "oy_id")

# Поля, которыми деталь опознают. Скопировать их значило бы завести дубль —
# а образец нужен ровно для обратного, для похожей, но другой детали.
# OY ID сюда же: у новой записи он свой, следующий по нумерации.
IDENTITY_FIELDS = ("vendor_pn", "vendor", "gbt_pn", "oy_id", "tracker_url")

# Своё у каждой детали, хоть и не опознаёт её. Datasheet — документация
# конкретного артикула: у соседнего номинала и тем более у аналога другого
# производителя это другой файл, и перенесённая ссылка вела бы не туда.
# Такую ошибку заметить труднее, чем пустое поле.
OWN_FIELDS = ("datasheet",)

# что не переносится ни «по образцу», ни в форму замены
NOT_COPIED = tuple(EXCLUDED) + IDENTITY_FIELDS + OWN_FIELDS


def sample_initial(source):
    """Значения образца для формы нового компонента.

    Переносится всё, кроме перечисленного в :data:`NOT_COPIED`: группа,
    подгруппа, корпус, номиналы, файлы САПР. Заполнять их заново для
    соседнего номинала из той же серии — самая частая ручная работа в
    справочнике.
    """
    skip = set(NOT_COPIED)
    return {field.name: getattr(source, field.name, None)
            for field in source._meta.fields if field.name not in skip}

# без этих полей запись бесполезна: по ним компонент опознают
REQUIRED_FIELDS = ("vendor_pn", "description")

# Текст одинаков для пустого поля и для заглушки: с точки зрения того, кто
# потом ищет компонент, «---» и пустота — одно и то же.
#
# Подпись поля в сообщение не входит: она стоит рядом, а в сводке ошибок
# наверху её подставляет шаблон — иначе получалось бы «Description:
# заполните «Description»».
REQUIRED_MESSAGE = "Заполните это поле: «---» и прочерки не годятся."

# незаполненные поля пишутся заглушкой, как принято в данных и в BOM
BLANK_VALUE = "---"

# служебное поле формы: галочка «завести всё равно» при найденном дубле.
# В модель не входит и в секции с параметрами не попадает
CONFIRM_FIELD = "confirm_duplicate"

# многострочные поля: длинные значения удобнее видеть целиком
TEXTAREA_FIELDS = ("description", "notice", "datasheet")

# Сколько строк показывать. Пять: в описание и примечание пишут
# предложениями, а в Datasheet попадают длинные адреса — на двух строках
# конец текста уходил под прокрутку.
TEXTAREA_ROWS = 5
DEFAULT_TEXTAREA_ROWS = 3

# в БД это varchar на 255 символов — ограничиваем ввод
SHORT_TEXT = ("description", "notice")
SHORT_TEXT_MAX_LENGTH = 255

# Поля САПР: имя детали в схеме и имя посадочного места. Их пишет и читает
# Allegro, и набор допустимых символов у них разный — у имени детали шире,
# в нём встречаются номиналы вида `CAP (0.1 uF)`. Проверка нужна не столько
# от опечаток, сколько от букв чужих алфавитов: кириллическая «с» в «C0805»
# выглядит точно как латинская, но САПР такое имя не найдёт, а поиск по
# библиотеке заведёт на её месте дубль.
#
# В HTML-атрибут pattern якоря не ставятся: он и так проверяет строку
# целиком. Дефис в наборе стоит последним — иначе он задавал бы диапазон.
ALLEGRO_RULES = {
    "allegro_schematic_part": (
        r"[A-Za-z0-9_|.+() -]+",
        "Допустимы латинские буквы, цифры, пробел и знаки "
        "«-», «_», «|», «.», «+», «(», «)».",
    ),
    "allegro_pcb_footprint": (
        r"[A-Za-z0-9_|-]+",
        "Допустимы только латинские буквы, цифры и знаки «-», «_», «|».",
    ),
}
# Артикулы: та же беда, что у полей Allegro, и в более опасном месте.
# Кириллическая «С» в «C0805» на вид не отличается от латинской, поиск по
# библиотеке такую запись не найдёт — и на её месте заведут вторую, причём
# проверка дублей промолчит: строки-то разные.
#
# Набор нарочно широкий — любой печатный ASCII. Задача не в том, чтобы
# навязать формат артикула (его задаёт производитель, и там встречается
# всякое), а в том, чтобы не пропустить буквы чужого алфавита.
ARTICLE_FIELDS = ("oy_pn", "oy_id", "gbt_pn")
ARTICLE_RULE = (
    r"[\x20-\x7E]+",
    "Допустимы латинские буквы, цифры и знаки препинания.",
)

FIELD_RULES = {
    **ALLEGRO_RULES,
    **{name: ARTICLE_RULE for name in ARTICLE_FIELDS},
}


def optional(validator):
    """Обёртка: проверка пропускает пустые значения и заглушки.

    Незаполненное поле хранится как ``---``, и при правке старой записи
    оно возвращается в форму именно так. Без этой обёртки любая проверка
    формата требовала бы сначала исправить поле, которое человек не
    трогал.
    """

    def check(value):
        if usable(value):
            validator(value)

    return check


FIELD_VALIDATORS = {
    name: optional(RegexValidator(rf"^{pattern}$", message))
    for name, (pattern, message) in FIELD_RULES.items()
}

# Ссылка на задачу в трекере — адрес, и проверяется как адрес. Заглушки
# пропускаются той же обёрткой: в большинстве записей тут стоит «---»
URL_FIELDS = ("tracker_url",)
URL_VALIDATOR = optional(URLValidator(
    message="Нужен адрес целиком, вместе с https://"))

# --- порядок и группировка полей в форме -----------------------------------

# основной блок: единый для всех групп компонентов, порядок задан вручную
MAIN_ORDER = (
    # OY ID в форме сайта нет (EXCLUDED) — строка работает для админки,
    # где он правится (см. build_form_class)
    "vendor_pn", "vendor", "tracker_url", "oy_pn", "oy_id", "gbt_pn",
    "group", "subgroup",
    "country", "smt_tht", "description", "notice", "datasheet", "package",
    "packaging", "pb_no_pb", "status",
    # в таблицах замен этих двух полей нет — они просто не выведутся
    "allegro_schematic_part", "allegro_pcb_footprint",
)

# электрика: номиналы, режимы и модели поведения
ELECTRICAL = (
    "value", "value_f_si", "value_h_si", "value_ohm_si", "value_a",
    "tolerance", "frequency_tolerance",
    "voltage_v", "rated_voltage", "input_voltage_v", "output_voltage_v",
    "forward_voltage_v", "output_current_a", "rated_current_a",
    "power_dissipation_w", "impedance_ohm", "dc_resistance_ohm", "esr",
    "dielectric_type", "polarity", "operating_mode", "interface", "lines_qty",
    "spice", "ibis", "s_parameters",
)

# физика: размеры, конструкция и условия эксплуатации
PHYSICAL = (
    "dimensions_mm", "height_mm", "material", "color",
    "connector_type", "number_of_pins", "number_of_rows", "pitch",
    "resistor_quantity",
    "temperature_min_c", "temperature_max_c",
)

FORM_SECTIONS = (
    ("Основные сведения", MAIN_ORDER),
    ("Электрические параметры", ELECTRICAL),
    ("Физические параметры", PHYSICAL),
)
OTHER_SECTION = "Прочие параметры"


class ComponentForm(forms.ModelForm):
    """Базовая форма: подмешивает css-классы и убирает лишний шум."""

    # таблица компонентов: подставляется в build_form_class,
    # по ней справочник решает, какие поля показывать списком
    option_table = ""
    # поля, убранные из формы для этой группы (registry.HIDDEN_FIELDS)
    hidden_fields = ()

    confirm_duplicate = forms.BooleanField(
        required=False,
        label="Всё равно завести",
        # без css-класса: браузерный чекбокс здесь уместен, а класса
        # .check в стилях нет — не ссылаемся на несуществующий
        widget=forms.CheckboxInput(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # найденные при проверке совпадения — шаблон показывает их рядом
        # с галочкой подтверждения
        self.duplicates = []
        # таблицы, которые опросить не удалось: без этого «ничего не
        # нашлось» и «проверка не сработала» выглядят одинаково
        self.duplicate_check_failed = []
        # совпадения, которые человек подтвердил галочкой: форма их
        # пропускает, а история о них узнаёт из этого списка
        self.confirmed_duplicates = []
        # Обязательные поля помечаются звёздочкой (templates/oy/field.html
        # рисует её по field.required), а не выясняются после нажатия
        # «Создать компонент». Заглушку «---» это не ловит — её отсекает
        # clean(), — но пустое поле теперь видно до отправки.
        for name in REQUIRED_FIELDS:
            if name in self.fields:
                self.fields[name].required = True
                self.fields[name].error_messages["required"] = REQUIRED_MESSAGE

        options = table_options(self.option_table)
        for name, bound in self.fields.items():
            # служебная галочка — не параметр компонента: ни списком из
            # справочника, ни классом .field её оформлять не нужно
            if name == CONFIRM_FIELD:
                continue
            # поля из справочника показываются выпадающим списком
            if name in options:
                bound.widget = self._option_widget(
                    name, bound, bound.widget, options[name],
                    self.get_initial_for_field(bound, name))

            widget = bound.widget

            # Datasheet в модели — обычный CharField; показываем его
            # многострочным, как Description и Notice. Атрибуты исходного
            # виджета переносим, иначе потеряется maxlength поля
            if name in TEXTAREA_FIELDS and not isinstance(widget, forms.Textarea):
                widget = forms.Textarea(attrs=dict(widget.attrs))
                bound.widget = widget

            if isinstance(widget, forms.Textarea):
                # именно присваивание, а не setdefault: Textarea приходит с
                # заполненными cols=40 и rows=10 — это её собственные
                # значения по умолчанию, и настройка ниже до сих пор ничего
                # не меняла, все поля выходили десятистрочными.
                # cols не нужен вовсе: ширину задаёт вёрстка
                widget.attrs.pop("cols", None)
                widget.attrs["rows"] = (TEXTAREA_ROWS if name in TEXTAREA_FIELDS
                                        else DEFAULT_TEXTAREA_ROWS)
                if name in SHORT_TEXT:
                    widget.attrs.setdefault("maxlength", SHORT_TEXT_MAX_LENGTH)

            # Класс виджету здесь не назначается: его ставит crispy по типу
            # виджета (CRISPY_CLASS_CONVERTERS). Раньше эти две строки
            # отвечали за то, выглядит ли поле как поле, — и работали только
            # для форм, которые проходили через этот цикл.

            if name in FIELD_RULES:
                # Проверяет сервер: форма отправляется с novalidate, да и
                # в базу пишем не только мы. Атрибут pattern добавлен ради
                # подсветки прямо при вводе — см. `.field[pattern]:invalid`
                # в стилях; сохранить он не мешает.
                pattern, message = FIELD_RULES[name]
                bound.validators.append(FIELD_VALIDATORS[name])
                widget.attrs["pattern"] = pattern
                widget.attrs["title"] = message

            if name in URL_FIELDS:
                bound.validators.append(URL_VALIDATOR)
                widget.attrs["title"] = "Адрес задачи в трекере целиком"

    def _option_widget(self, name, field, widget, values, initial=None):
        """Выпадающий список строго из значений справочника.

        Если в записи стоит значение, которого в справочнике нет, оно в
        список не попадает — но о нём предупреждает подпись под полем,
        иначе оно затёрлось бы при сохранении незаметно.

        Значение ищется и в ``initial``: при заведении по образцу и при
        добавлении замены запись ещё пустая, а перенесённые параметры лежат
        именно там.
        """
        current = (getattr(self.instance, name, "") or "").strip()
        if not current:
            current = str(initial or "").strip()
        if current and current not in values:
            field.help_text = (f"В записи было «{current}» — этого значения "
                               f"нет в справочнике. Сохранение заменит его "
                               f"на выбранное.")
        return forms.Select(choices=[(v, v) for v in values],
                            attrs=dict(widget.attrs))

    def clean(self):
        cleaned = super().clean()

        # обязательные поля заглушкой закрывать нельзя: по ним компонент
        # опознают в библиотеке и в BOM, «---» там бесполезен
        for name in REQUIRED_FIELDS:
            if name not in self.fields:
                continue
            # пустое поле уже отсеяла проверка required — второе такое же
            # сообщение под полем только мешает
            if name in self._errors:
                continue
            value = (cleaned.get(name) or "").strip()
            if not value or is_placeholder(value):
                self.add_error(name, REQUIRED_MESSAGE)
                cleaned.pop(name, None)

        # остальные незаполненные поля получают «---»: так принято в базе и
        # в BOM, а сопоставление аналогов такие значения уже игнорирует
        for name, value in list(cleaned.items()):
            if name in REQUIRED_FIELDS or name == CONFIRM_FIELD:
                continue
            if value is None or (isinstance(value, str) and not value.strip()):
                cleaned[name] = BLANK_VALUE

        self._check_duplicates(cleaned)
        return cleaned

    def save(self, commit=True):
        # Скрытое поле в форму не попадает, и у новой записи осталось бы
        # NULL, а незаполненное в базе принято писать «---» — сторонний софт
        # и сопоставление аналогов ждут именно его
        obj = super().save(commit=False)
        for name in self.hidden_fields:
            if not (getattr(obj, name, None) or "").strip():
                setattr(obj, name, BLANK_VALUE)
        if commit:
            obj.save()
        return obj

    def _check_duplicates(self, cleaned):
        """Ищет в библиотеке компонент с тем же Vendor PN или GBT PN.

        Не блокирует наглухо: совпадение — почти всегда ошибка ввода, но не
        всегда, поэтому запись можно завести, отметив галочку. Это тот же
        подход, что и при удалении используемого компонента.

        При правке существующей записи она сама из поиска исключается,
        иначе нашла бы себя.
        """
        found, self.duplicate_check_failed = find_existing(
            cleaned,
            exclude_table=self.option_table,
            exclude_pk=self.instance.pk if self.instance.pk else None)

        if cleaned.get(CONFIRM_FIELD):
            # человек подтвердил, что заводит похожую запись сознательно.
            # Поиск всё равно выполняется: подтверждение — не повод забыть,
            # с чем именно совпало. Без этого в истории осталось бы «завели
            # дубль», но не было бы видно, чему он дубль.
            self.confirmed_duplicates = found
            return

        self.duplicates = found
        if not self.duplicates:
            return

        titles = ", ".join(
            f"{match['obj'].display_title()} ({match['category'].table})"
            for match in self.duplicates)
        reasons = sorted({match["reason"] for match in self.duplicates
                          if match["reason"]})
        self.add_error(None, forms.ValidationError(
            f"Такой компонент уже есть в библиотеке — совпадает "
            f"{' и '.join(reasons) or 'артикул'}: {titles}. "
            f"Проверьте, не заводится ли дубль. Если это всё-таки разные "
            f"детали, отметьте «Всё равно завести» и сохраните ещё раз."))


@lru_cache(maxsize=None)
def build_form_class(model, table="", hidden=(), editable=()):
    """Класс формы для группы компонентов.

    Собирается один раз на пару «модель + таблица» и дальше переиспользуется:
    полей в форме под сотню, и строить класс заново на каждое открытие
    страницы незачем. Значения выпадающих списков в классе не зашиты — их
    читает ``__init__``, поэтому правка справочника видна сразу.

    ``editable`` возвращает в форму поля из :data:`EXCLUDED`. Нужно это
    админке: OY ID на сайте назначается сам, а в админке его приходится
    вписывать руками — например, замене, которую там не из чего взять.
    """
    skip = (set(EXCLUDED) - set(editable)) | set(hidden)
    fields = [f.name for f in model._meta.fields if f.name not in skip]
    base = type("BoundComponentForm", (ComponentForm,),
                {"option_table": table, "hidden_fields": tuple(hidden)})
    return modelform_factory(model, form=base, fields=fields)


def field_sections(names):
    """``[(заголовок, [имена полей])]`` — раскладка полей по секциям.

    Одна на сайт и админку: раньше секции знала только форма сайта, и в
    админке те же сорок полей шли одной колонкой в порядке модели.
    """
    names = list(names)
    present = set(names)
    used = set()
    sections = []
    for title, order in FORM_SECTIONS:
        picked = [n for n in order if n in present and n not in used]
        used.update(picked)
        if picked:
            sections.append((title, picked))
    # страховка: новое поле в модели не потеряется, а выйдет отдельной секцией
    rest = [n for n in names if n not in used]
    if rest:
        sections.append((OTHER_SECTION, rest))
    return sections


def group_fields(form):
    """Раскладывает поля формы на секции для шаблона."""
    # галочка подтверждения дубля показывается отдельно, рядом с
    # предупреждением, а не среди параметров компонента
    names = [n for n in form.fields if n != CONFIRM_FIELD]
    return [(title, [form[n] for n in picked])
            for title, picked in field_sections(names)]
