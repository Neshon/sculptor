"""Заведение и правка компонента — то, что от запроса не зависит.

Здесь две вещи:

* :func:`save_component` — сохранение с историей. Одно на сайт и
  админку. Раньше оно было написано дважды — в ``ComponentEditView.post``
  и в ``ComponentAdmin.save_model``, — и стоило поменять одно место и
  забыть второе, как история снова шла с дырами: правка через админку не
  записала бы подтверждённый дубль или автора;
* :class:`ComponentDraft` — какой из четырёх случаев перед нами (правка,
  новый, новый по образцу, замена), что в форме заперто, откуда OY ID и
  начальные значения. Раньше всё это жило в самом представлении вперемешку
  с перенаправлениями и сообщениями, и проверить решения можно было только
  запросом к сайту.

Представление (:class:`components.views.ComponentEditView`) оставляет себе
то, что про HTTP: права, перенаправления, сообщения, шаблон.
"""

from .defaults import defaults
from .forms import build_form_class, sample_initial
from .history import SITE, record, record_duplicate, snapshot
from .matching import usable
from .mixins import field_names
from .numbering import next_oy_id


def stored_snapshot(model, pk):
    """Снимок записи, какой она лежит в базе, — для сравнения «было — стало».

    Нужен админке: там форма к моменту сохранения уже перенесла присланные
    значения на объект, и снимать «было» с него значило бы сравнить новое с
    новым. Сайт снимает его раньше, при чтении записи (ComponentDraft).
    """
    if pk is None:
        return {}
    current = model.objects.filter(pk=pk).first()
    return snapshot(current) if current is not None else {}


def save_component(obj, table, user, before=None, confirmed=(), source=SITE):
    """Сохраняет компонент и пишет историю — одинаково с сайта и из админки.

    ``obj`` — запись уже с данными формы (``form.save(commit=False)``).
    ``before`` — снимок до правки; у новой записи пусто. ``confirmed`` —
    совпадения, которые человек подтвердил галочкой «Всё равно завести».

    Автор проставляется только при заведении: это тот, кто завёл запись, а
    не последний правивший. Сравнивается то, что в самом деле легло в
    базу, а не список полей, которые форма считает изменёнными: при
    сохранении пустые значения превращаются в «---», и форма об этом не
    знает. Подтверждённое совпадение — отдельное событие: запись завели,
    зная, что похожая уже есть.

    Ошибку базы не ловит: что сказать человеку, решает вызывающий.
    """
    if (obj._state.adding and "author" in field_names(type(obj))
            and not getattr(obj, "author", None)):
        obj.author = user.get_username()
    obj.save()
    record(obj, table, user, before or {}, source=source)
    record_duplicate(obj, table, user, confirmed, source=source)
    return obj


class ComponentDraft:
    """Форма компонента в одном из четырёх случаев — и всё, что из него следует.

    * правка — ``obj`` из базы;
    * новый — ``obj`` пустой;
    * по образцу — пустой ``obj`` и ``sample``, с которого списываются
      параметры («Добавить по образцу»);
    * замена — пустой ``obj`` в таблице замен и ``source``, основной
      компонент: OY ID и параметры берутся у него.

    Откуда взялись ``source`` и ``sample`` (строка запроса, права,
    перенаправления) — забота представления.
    """

    def __init__(self, category, obj, source=None, sample=None):
        self.category = category
        self.obj = obj
        self.source = source
        self.sample = sample
        self.created = obj.pk is None

        # Снимок «до» берётся здесь, при создании черновика, и это
        # принципиально. ModelForm переносит присланные данные на instance
        # ещё во время is_valid() — в _post_clean(). Дальше obj уже держит
        # новые значения, сравнивать его с самим собой бессмысленно, и
        # история правок оставалась пустой. Здесь запись только что
        # прочитана из базы и формы ещё не касалась.
        self.before = {} if self.created else snapshot(obj)

        self.locked = self._locked_fields()
        # OY ID в форму не выводится: править его нельзя, а место в первом
        # ряду занимает то, что действительно вводят. Значение показывается
        # в шапке и проставляется при сохранении.
        self.oy_id, self.oy_id_hint = self._oy_id()

    # ---- что заперто -------------------------------------------------------

    def _locked_fields(self):
        """``{поле: (значение, пояснение)}`` — что показываем, но не даём править.

        Пустой словарь для поля означает «оставить редактируемым»: подобрать
        значение не удалось, и заперев поле, мы бы не дали завести первую
        запись в пустой таблице.
        """
        locked = {}

        group = self._group()
        if group:
            # без пояснения: поле и так заперто и заполнено, а подпись
            # «определяется группой компонентов» повторяла название группы,
            # написанное строкой выше
            locked["group"] = (group, "")

        return locked

    def _oy_id(self):
        """Значение OY ID и пояснение, откуда оно взялось.

        У замены оно приходит от основного компонента, у существующей записи
        остаётся прежним, у нового компонента вычисляется по нумерации.
        Если вычислить нечего (в таблице ещё нет ни одного ID) или в записи
        стоит заглушка — поле остаётся редактируемым, иначе завести первый
        компонент было бы нечем.
        """
        if self.source:
            return self.source.oy_id, (f"Берётся у основного компонента "
                                       f"{self.source.display_title()}")
        if not self.created:
            return (usable(getattr(self.obj, "oy_id", "")) or None,
                    "Идентификатор записи не меняется")
        return (next_oy_id(self.category) or None,
                "Следующий свободный номер, назначается автоматически")

    def _group(self):
        """Значение Group: оно определяется таблицей, а не автором записи.

        У существующей записи остаётся своё: подменять его на общее по
        группе значило бы молча править данные, за которыми сюда не
        приходили. Незаполненное — случай другой: там заполнять нечего, и
        подставляется общее.
        """
        if "group" not in self.category.field_names:
            return None
        if not self.created:
            current = usable(getattr(self.obj, "group", ""))
            if current:
                return current
        return defaults(self.category).get("group")

    # ---- форма ---------------------------------------------------------------

    def initial(self):
        """Начальные значения формы — одинаковые для показа и для отправки.

        Для запертых полей это не удобство, а источник истины: значение
        ``disabled``-поля Django берёт именно отсюда.
        """
        # у всей группы одинаковые значения (Group) подставляются сразу
        initial = dict(defaults(self.category)) if self.created else {}

        # Замена — тот же компонент другого производителя: подгруппа,
        # корпус, номинал, температурный диапазон у неё те же. Поэтому
        # параметры списываются с основного компонента, как при заведении
        # по образцу, — заполнять их заново было бы переписыванием
        # соседней карточки вручную.
        #
        # Опознающие поля и Datasheet не переносятся (см. NOT_COPIED):
        # аналог на то и аналог, что артикул, производитель и документация
        # у него свои. Лишние ключи не мешают: в таблице замен нет полей
        # Allegro, и в форму они просто не попадут.
        for donor in (self.source, self.sample):
            if donor is not None:
                initial.update(sample_initial(donor))

        for name, (value, _) in self.locked.items():
            initial[name] = value
        return initial

    def form_class(self):
        return build_form_class(self.category.model, self.category.table,
                                self.category.hidden_fields)

    def build_form(self, data=None):
        """Собирает форму и сразу запирает поля.

        Запереть их нужно до проверки, а не перед показом. ``disabled``
        Django учитывает в ``is_valid()``: только там он подставляет
        значение из ``initial`` вместо присланного. Пока поле заперто лишь
        при отрисовке, браузер его не отправляет (disabled-поля не
        отправляются), проверка видит пустоту и записывает «---» — так
        Group и сбрасывалась при каждой правке.
        """
        form = self.form_class()(data, instance=self.obj,
                                 initial=self.initial())
        self._lock_widgets(form)
        return form

    def _lock_widgets(self, form):
        """Запирает поля; пояснение под полем — если оно там нужно.

        ``disabled`` вместо ``readonly``: readonly в браузере обходится, а
        disabled Django обрабатывает сам — присланные данные для такого поля
        игнорируются, и берётся значение из ``initial``. Поэтому подменить
        его запросом нельзя, и доопределять поле при сохранении не нужно.
        """
        for name, (_value, hint) in self.locked.items():
            field = form.fields.get(name)
            if field is None:
                continue
            field.disabled = True
            # пустое пояснение убирает подпись под полем, в том числе ту,
            # что могла остаться от справочника значений
            field.help_text = hint
            # Класс условный, а не по типу виджета: конвертеры crispy такое
            # не выражают. «field» дописывать не нужно — crispy увидит его в
            # строке и второй раз не добавит.
            field.widget.attrs["class"] = "field field--locked"

    # ---- сохранение --------------------------------------------------------

    def save(self, form, user):
        """Сохраняет проверенную форму. Ошибку базы не ловит."""
        obj = form.save(commit=False)
        # OY ID формой не передаётся — его в ней нет. У новой записи он
        # назначается по нумерации, у существующей остаётся прежним.
        # Остальные запертые поля доопределять не нужно: disabled-поля
        # Django заполняет из initial и присланные данные игнорирует.
        if self.oy_id:
            obj.oy_id = self.oy_id
        return save_component(obj, self.category.table, user, self.before,
                              form.confirmed_duplicates)
