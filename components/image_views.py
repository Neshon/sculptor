"""Картинка посадочного места: загрузка STEP-модели и опрос рендера.

Вынесено из :mod:`components.views`: у картинки своя жизнь — она
принадлежит посадочному месту, а не компоненту, и рендерится в фоне
(:mod:`components.tasks`). Карточка компонента берёт отсюда только
:func:`footprint_of`.
"""

from functools import partial

from django import forms
from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from config.htmx import refresh_page
from users.roles import component_editor

from . import step
from .history import record_image
from .listing import category_or_404, fetch
from .lookup import footprint_usage
from .matching import usable
from .models import FootprintImage, StepRenderJob
from .step import normalize_footprint, save_to_queue
from .tasks import dispatch_render


class StepImageForm(forms.Form):
    """STEP-файл, из которого делается картинка компонента.

    Форма отдельная от формы компонента, а не лишнее поле в ней, по двум
    причинам. Поля компонента собираются из модели, а этого поля в модели
    нет и быть не может: таблицы компонентов ведём не мы. И картинка
    принадлежит не компоненту, а его посадочному месту
    (:class:`components.models.FootprintImage`) — её можно заменить или
    убрать, не трогая сам компонент.

    Живёт на своей странице (``components:image``): загрузка меняет
    картинку у всех компонентов с этим footprint, и прятать такое
    действие внутри правки одной записи было бы нечестно.

    Файл не сохраняется. Из него делают картинку и выбрасывают — почему
    так, написано в :mod:`components.step`.
    """

    prefix = "step"

    step_file = forms.FileField(
        required=False, label="STEP-файл",
        help_text="Из модели сделается картинка для карточки. "
                  "Сам файл не сохраняется")
    drop_image = forms.BooleanField(
        required=False,
        label="Удалить картинку посадочного места (у всех компонентов с ним)")

    def clean_step_file(self):
        uploaded = self.cleaned_data.get("step_file")
        if uploaded:
            # размер и расширение — до чтения содержимого
            step.check(uploaded)
        return uploaded

    def clean(self):
        cleaned = super().clean()
        uploaded, drop = cleaned.get("step_file"), cleaned.get("drop_image")
        if uploaded and drop:
            raise forms.ValidationError(
                "Выбран файл и одновременно отмечено удаление — оставьте "
                "что-то одно")
        # На отдельной странице пустая отправка — не «ничего не меняем»,
        # а скорее забытый файл. Молча вернуть человека в карточку значило
        # бы, что он решит, будто картинка загрузилась
        if not uploaded and not drop and not self.errors:
            raise forms.ValidationError("Выберите STEP-файл")
        return cleaned


def footprint_of(obj):
    """Allegro PCB Footprint записи. У таблиц замен колонки нет вовсе."""
    return getattr(obj, "allegro_pcb_footprint", "") or ""


# ---- картинка посадочного места -----------------------------------------


@component_editor
def footprint_image(request, slug, pk):
    """Добавление и замена картинки посадочного места компонента.

    Отдельная страница, а не блок в форме компонента, по двум причинам.
    Картинка принадлежит не компоненту, а его посадочному месту: загрузка
    меняет её у всех компонентов с этим footprint, и смешивать это с
    правкой одной записи значило бы прятать действие над многими внутри
    действия над одной. И STEP-файл весит мегабайты: гонять его вместе с
    сотней полей компонента на каждое сохранение незачем.

    Заходят сюда из карточки компонента; назад — туда же.
    """
    category = category_or_404(slug)
    if not hasattr(category.model, "allegro_pcb_footprint"):
        # у таблиц замен колонки нет, и картинку им записать некуда: они
        # берут её у основного компонента по OY ID
        raise Http404("У этой группы нет посадочного места")
    if category.read_only:
        raise Http404("Группа только для чтения")

    obj = fetch(category, pk)
    footprint = usable(footprint_of(obj))
    image = FootprintImage.for_footprint(footprint)
    form = StepImageForm(request.POST or None, request.FILES or None)
    back = redirect("components:detail", slug=category.slug, pk=obj.pk)

    if request.method == "POST" and form.is_valid():
        if not footprint:
            messages.warning(
                request,
                "У компонента не указан Allegro PCB Footprint, а картинка "
                "хранится у посадочного места. Сначала заполните его.")
            return back

        if form.cleaned_data.get("drop_image"):
            if image:
                removed = image.source_name
                image.delete()
                record_image(category.table, obj.pk, request.user, footprint,
                             old=removed or "изображение")
                messages.info(
                    request,
                    f"Картинка посадочного места {footprint} удалена — "
                    f"у всех компонентов с ним.")
            return back

        uploaded = form.cleaned_data["step_file"]
        try:
            queued_as = save_to_queue(uploaded)
        except OSError as exc:
            # чаще всего — права на каталог очереди: в Docker он том, и
            # писать в него должен пользователь, от которого работает сайт
            messages.error(
                request,
                f"Не удалось положить модель в очередь на рендер: {exc}")
            return render(request, "components/footprint_image.html", {
                "category": category, "object": obj, "form": form,
                "image": image, "footprint": footprint,
                "job": StepRenderJob.latest_for(footprint),
                "footprint_usage": footprint_usage(footprint),
            })

        # компонент запоминаем: запись в журнал ставится, когда рендер
        # удастся, а к тому времени этого запроса уже не будет
        job = StepRenderJob.objects.create(
            key=normalize_footprint(footprint), footprint=footprint,
            source_name=getattr(uploaded, "name", "")[:255],
            step_file=queued_as, author=request.user.get_username(),
            component_table=category.table, component_id=obj.pk)

        # Отправляем после фиксации транзакции: рендер идёт в другом
        # процессе со своим соединением, и заявку, которой в базе ещё не
        # видно, он бы просто не нашёл
        transaction.on_commit(partial(dispatch_render, job.pk))

        # Сообщение — по факту: если запустить рендер не вышло, заявка уже
        # закрыта с причиной, и «готовится» было бы неправдой
        job.refresh_from_db()
        if job.status == StepRenderJob.DONE:
            messages.success(
                request,
                f"Картинка посадочного места {footprint} готова: "
                f"{job.message}.")
            return back
        if job.status == StepRenderJob.FAILED:
            # остаёмся на странице — можно сразу выбрать другой файл
            messages.error(request, f"Изображение не сделано: {job.message}")
        else:
            messages.info(
                request,
                f"Модель принята, картинка посадочного места {footprint} "
                f"готовится. Карточка покажет её, когда рендер закончится.")
            return back

    return render(request, "components/footprint_image.html", {
        "category": category,
        "object": obj,
        "form": form,
        "image": image,
        "footprint": footprint,
        "job": StepRenderJob.latest_for(footprint),
        # сколько компонентов увидят новую картинку: загрузка заменяет её
        # всем, и об этом надо сказать до того, как нажмут
        "footprint_usage": footprint_usage(footprint),
    })


def render_job_status(request, pk):
    """Состояние заявки на рендер — для блока, который опрашивает её сам.

    Отвечает тремя способами, и HTMX понимает каждый:

    * заявка ещё в работе — тот же блок заново, с новым состоянием;
    * картинка готова (или заявку заменила новая) — просьба перезагрузить
      страницу целиком: показать надо картинку, а она в другом блоке;
    * ждать больше нечего (не удалось) — блок с итогом и код 286: по нему
      HTMX прекращает опрос.

    Смотреть состояние может любой вошедший — как и саму карточку.
    """
    job = get_object_or_404(StepRenderJob, pk=pk)
    if job.status in (StepRenderJob.DONE, StepRenderJob.SUPERSEDED):
        return refresh_page()

    response = render(request, "components/_render_job.html", {
        "job": job,
        "show_failures": request.GET.get("failures") == "1",
    })
    if not job.is_active:
        # 286 — условленный у HTMX код «опрос больше не нужен»
        response.status_code = 286
    return response
