"""Фоновые задачи справочника компонентов.

Задача одна — нарисовать картинку посадочного места из STEP-модели.
Отправляет её :func:`dispatch_render`, и куда именно — зависит от
настройки ``DJANGO_TASKS_BACKEND``:

* бэкенд с воркером (``django_tasks_db``) — задача ставится в очередь
  фреймворка задач Django, и её берёт ``manage.py db_worker``;

* встроенный ``ImmediateBackend`` (по умолчанию) — задача запускается
  отдельным процессом ``manage.py render_job``, отвязанным от запроса.

Второй путь — не каприз. Встроенный бэкенд выполняет задачу прямо в
вызывающем потоке, то есть в запросе, а рендер держит GIL: пока модель
рисуется, на однопроцессном сервере (runserver, waitress) стоит весь
сайт, а у человека висит вкладка. Отдельный процесс снимает и то и
другое без воркера — запрос возвращается сразу, сайт отвечает. Заодно
падение OpenCascade на битом файле роняет только этот процесс, а не сайт.

Сам рендер — одна функция, :func:`run_render_job`: её вызывают и задача
фреймворка, и команда ``render_job``.

Задаче передаётся только номер заявки. Аргументы задач проходят через
JSON, а загруженный файл, запись модели или путь с объектами туда не
пролезут; к тому же воркер может запуститься минутой позже, и всё
нужное он должен найти сам — в заявке и в каталоге очереди.
"""

import os
import subprocess
import sys

from django.conf import settings
from django.db import transaction
from django.tasks import task, task_backends
from django.tasks.backends.immediate import ImmediateBackend
from django.utils import timezone

from .history import record_image
from .models import FootprintImage, StepRenderJob
from .step import StepRenderError, queue_path, render_file


@task
def render_footprint_image(job_id):
    """Задача фреймворка: то же, что :func:`run_render_job`.

    Возвращает итоговое состояние заявки — фреймворку задач нужен
    JSON-совместимый ответ, а человек смотрит на саму заявку.
    """
    return run_render_job(job_id)


def runs_in_request():
    """Выполнил бы бэкенд задачу прямо в запросе.

    Берём сам бэкенд из ``task_backends``, а не ``default_task_backend``:
    тот — посредник, и проверка типа на нём ничего бы не сказала.
    """
    return isinstance(task_backends["default"], ImmediateBackend)


def dispatch_render(job_id):
    """Отправляет заявку на рендер, не задерживая запрос.

    Зовётся после фиксации транзакции (см. вид страницы изображения):
    и воркер, и отдельный процесс — со своим соединением, и заявку,
    которой в базе ещё не видно, они бы не нашли.
    """
    if not runs_in_request():
        render_footprint_image.enqueue(job_id=job_id)
        return

    try:
        _spawn_render(job_id)
    except OSError as exc:
        # запустить процесс не вышло — заявку закрываем сразу, иначе она
        # висела бы «в очереди», которой нет
        job = StepRenderJob.objects.filter(pk=job_id).first()
        if job:
            _finish(job, StepRenderJob.FAILED,
                    f"Не удалось запустить рендер: {exc}")


def _spawn_render(job_id):
    """Запускает ``manage.py render_job`` отдельным процессом и не ждёт его.

    Процесс отвязан от запроса: у него своя группа (Windows) или своя сессия
    (Linux), так что ни закрытие вкладки, ни перезапуск работника сервера
    его не прерывают. Вывод — в журнал рядом с очередью: окна у процесса
    нет, и без журнала упавший рендер не оставил бы следов.
    """
    queue = settings.STEP_QUEUE_DIR
    queue.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(settings.BASE_DIR / "manage.py"),
               "render_job", str(job_id)]

    options = {"cwd": str(settings.BASE_DIR), "stdin": subprocess.DEVNULL,
               "close_fds": True}
    if os.name == "nt":
        # без консоли и без привязки к консоли сервера: иначе закрытие окна
        # runserver обрывало бы и рендер
        options["creationflags"] = (subprocess.DETACHED_PROCESS
                                    | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        options["start_new_session"] = True

    with (queue / "render.log").open("ab") as log:
        subprocess.Popen(command, stdout=log, stderr=log, **options)


def run_render_job(job_id):
    """Рендерит модель из заявки и записывает картинку посадочного места.

    Возвращает итоговое состояние заявки.
    """
    # Берём заявку под блокировку и сразу отмечаем, что она в работе:
    # два воркера не должны рисовать одну модель, а карточка — увидеть
    # «в очереди», когда рендер уже идёт
    with transaction.atomic():
        job = (StepRenderJob.objects.select_for_update()
               .filter(pk=job_id).first())
        if job is None or job.status != StepRenderJob.QUEUED:
            return job.status if job else "missing"

        # Пока заявка ждала, на то же место могли прислать модель новее.
        # Рисовать старую незачем, а нарисованная — затёрла бы свежую:
        # воркеров может быть несколько, и порядок исполнения не гарантирован
        newer = (StepRenderJob.objects
                 .filter(key=job.key, created__gt=job.created)
                 .exclude(pk=job.pk).exists())
        job.status = (StepRenderJob.SUPERSEDED if newer
                      else StepRenderJob.RUNNING)
        job.save(update_fields=["status"])

    path = queue_path(job.step_file)
    try:
        if job.status == StepRenderJob.SUPERSEDED:
            return _finish(job, StepRenderJob.SUPERSEDED)

        try:
            png, triangles, colors = render_file(path)
        except StepRenderError as exc:
            return _finish(job, StepRenderJob.FAILED, str(exc))
        except FileNotFoundError:
            # файл в очереди исчез: каталог почистили руками или воркер
            # смотрит не в тот каталог, что веб-процесс
            return _finish(job, StepRenderJob.FAILED,
                           "Файл модели не найден в каталоге очереди. "
                           "Проверьте, что воркер и сайт видят один и тот же "
                           "DJANGO_STEP_QUEUE_DIR.")
        except Exception as exc:  # noqa: BLE001 — заявка не должна зависнуть
            return _finish(job, StepRenderJob.FAILED,
                           f"Рендер упал: {type(exc).__name__}: {exc}")

        # чья картинка была до этой — для записи «было — стало» в журнале
        previous = FootprintImage.for_footprint(job.footprint)
        replaced = previous.source_name if previous else ""

        FootprintImage.store(job.footprint, png, source_name=job.source_name,
                             author=job.author)
        # В журнал — только удавшийся рендер: неудачная попытка картинку не
        # поменяла, и в истории компонента ей делать нечего (она видна в
        # заявке). Пакетная загрузка компонента не указывает — там и записи нет
        record_image(job.component_table, job.component_id, job.author,
                     job.footprint, old=replaced,
                     new=job.source_name or "изображение")
        return _finish(job, StepRenderJob.DONE,
                       f"{triangles} треугольников, {colors} цветов")
    finally:
        # Модель не храним ни при каком исходе: хранится картинка
        path.unlink(missing_ok=True)


def _finish(job, status, message=""):
    """Закрывает заявку: состояние, итог и время."""
    job.status = status
    job.message = message
    job.finished = timezone.now()
    job.save(update_fields=["status", "message", "finished"])
    return status
