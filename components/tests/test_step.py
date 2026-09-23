"""Картинки посадочных мест: загрузка STEP, очередь и фоновый рендер."""

import shutil
from pathlib import Path
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .. import step
from ..image_views import StepImageForm

# Под своим именем: в matching тоже есть normalize, и когда тесты лежали
# одним файлом, импорт оттуда затирал этот — проверка «команда сравнивает
# тем же правилом, что карточка» сравнивала не ту функцию и падала.
from ..management.commands.render_step_images import models_in
from ..management.commands.render_step_images import normalize as command_normalize


class StepUploadFormTests(SimpleTestCase):
    """Проверка присланного STEP-файла — до чтения содержимого.

    Разбирать файл, чтобы потом отклонить его по размеру, незачем: рендер
    дорогой, а отказ дешёвый.
    """

    class FakeUpload:
        def __init__(self, name, size):
            self.name = name
            self.size = size

    def form(self, upload=None, drop=False):
        data = {"step-drop_image": "on"} if drop else {}
        files = {"step-step_file": upload} if upload else {}
        return StepImageForm(data, files)

    def test_empty_submission_asks_for_a_file(self):
        # на отдельной странице пустая отправка — скорее забытый файл, чем
        # «ничего не меняем»: молча вернуть в карточку значило бы дать
        # понять, что картинка загрузилась
        form = self.form()
        self.assertFalse(form.is_valid())
        self.assertIn("Выберите STEP-файл", form.non_field_errors())

    def test_delete_alone_is_enough(self):
        self.assertTrue(self.form(drop=True).is_valid())

    def test_wrong_extension_is_rejected(self):
        with self.assertRaises(ValidationError):
            step.check(self.FakeUpload("model.sldprt", 1024))

    def test_stp_is_accepted(self):
        # у STEP два расширения, и .stp встречается не реже
        step.check(self.FakeUpload("MODEL.STP", 1024))

    def test_oversized_file_is_rejected(self):
        with self.assertRaises(ValidationError):
            step.check(self.FakeUpload("model.step", step.MAX_BYTES + 1))

    def test_upload_and_delete_together_make_no_sense(self):
        form = StepImageForm({"step-drop_image": "on"},
                             {"step-step_file": self.FakeUpload("m.step", 10)})
        self.assertFalse(form.is_valid())



class StepImagePathTests(SimpleTestCase):
    """Куда ложится файл картинки посадочного места.

    Одна папка на всю библиотеку и один файл на посадочное место. Имя
    STEP-файла в путь не идёт: у трёх деталей подряд он называется
    `part.step`.
    """

    class FakeImage:
        footprint = "SODFL100X250X050"
        key = "sodfl100x250x050"

    def test_name_comes_from_the_footprint(self):
        self.assertEqual(step.upload_path(self.FakeImage(), "render.png"),
                         "footprint_images/SODFL100X250X050.png")

    def test_footprint_cannot_escape_the_directory(self):
        image = self.FakeImage()
        image.footprint = "../../etc/passwd"
        self.assertEqual(step.upload_path(image, "render.png"),
                         "footprint_images/etc-passwd.png")

    def test_different_footprints_stay_different_files(self):
        # посторонние знаки заменяются, а не выбрасываются: иначе
        # «SOT/23» и «SOT23» дали бы один файл на два разных места
        self.assertNotEqual(step.safe_stem("SOT/23"), step.safe_stem("SOT23"))



class FootprintKeyTests(SimpleTestCase):
    """Ключ, по которому компонент находит картинку своего места.

    Записи заводили разные люди и разные программы, и одно место в
    библиотеке встречается в разном написании. Картинка должна находиться
    по любому из них.
    """

    def test_case_and_spaces_do_not_matter(self):
        self.assertEqual(step.normalize_footprint("  SODFL100X250X050 "),
                         step.normalize_footprint("sodfl100x250x050"))

    def test_different_footprints_stay_different(self):
        self.assertNotEqual(step.normalize_footprint("SODFL100X250X050"),
                            step.normalize_footprint("SODFL100X250X060"))

    def test_empty_value_gives_an_empty_key(self):
        # у замен колонки нет вовсе, и в базе встречаются None и ""
        self.assertEqual(step.normalize_footprint(None), "")
        self.assertEqual(step.normalize_footprint("  "), "")



class StepRenderAvailabilityTests(SimpleTestCase):
    """Без установленных пакетов рендер отвечает понятным отказом.

    Это основной режим работы: в образ OCP не входит. Падать импортом на
    старте или пятистами строками трассировки при загрузке файла система
    не должна.
    """

    def test_missing_libraries_give_a_readable_error(self):
        try:
            import OCP  # noqa: F401
        except ImportError:
            pass
        else:
            self.skipTest("OCP установлен — проверять нечего")

        with self.assertRaises(step.StepRenderError) as caught:
            step.render_file("model.step")
        self.assertIn("не запускается", str(caught.exception))



class StepBatchMatchingTests(SimpleTestCase):
    """Пакетная загрузка: модель находит посадочное место по имени файла.

    Ничего умнее точного совпадения тут намеренно нет: картинка чужого
    посадочного места выглядит как правильная, и заметить подмену можно,
    только открыв модель.
    """

    def test_command_matches_like_the_card(self):
        # команда и карточка сравнивают одним правилом — иначе модель
        # записалась бы под ключом, по которому карточка её не найдёт
        self.assertIs(command_normalize, step.normalize_footprint)

    def make_dir(self, *names):
        import tempfile

        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        for name in names:
            (directory / name).write_text("")
        return directory

    def test_only_step_files_are_taken(self):
        found, _ = models_in(self.make_dir("a.step", "b.stp", "readme.txt",
                                           "c.sldprt"))
        self.assertEqual(set(found), {"a", "b"})

    def test_same_name_twice_is_reported_not_guessed(self):
        # SLP2510P8.step и SLP2510P8.stp: какой из них правильный, знает
        # конструктор, а не команда
        found, duplicates = models_in(self.make_dir("m.step", "m.stp"))
        self.assertEqual(set(found), {"m"})
        self.assertEqual([path.name for path in duplicates], ["m.stp"])



class StepQueueTests(SimpleTestCase):
    """Каталог, где STEP-модели ждут воркера."""

    class FakeUpload:
        def __init__(self, data=b"ISO-10303-21;"):
            self.data = data

        def seek(self, position):
            pass

        def chunks(self):
            yield self.data

    def setUp(self):
        import tempfile

        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory)

    def test_name_cannot_escape_the_queue(self):
        # имя приходит из записи в базе и не должно уводить из каталога,
        # даже если запись испорчена
        with self.settings(STEP_QUEUE_DIR=self.directory):
            self.assertEqual(step.queue_path("../../etc/passwd"),
                             self.directory / "passwd")

    def test_saved_file_gets_a_fresh_name(self):
        # две модели «part.step» подряд не должны затирать друг друга,
        # пока ждут воркера
        with self.settings(STEP_QUEUE_DIR=self.directory):
            first = step.save_to_queue(self.FakeUpload())
            second = step.save_to_queue(self.FakeUpload())
            self.assertNotEqual(first, second)
            self.assertEqual(step.queue_path(first).read_bytes(),
                             b"ISO-10303-21;")

    def test_queue_is_created_on_demand(self):
        nested = self.directory / "not" / "yet"
        with self.settings(STEP_QUEUE_DIR=nested):
            step.save_to_queue(self.FakeUpload())
        self.assertTrue(nested.is_dir())



class StepRenderJobTests(SimpleTestCase):
    """Заявка на рендер: что видит человек, пока картинка готовится."""

    def job(self, status, minutes_ago):
        import datetime as dt

        from django.utils import timezone

        from ..models import StepRenderJob

        job = StepRenderJob(status=status)
        job.created = timezone.now() - dt.timedelta(minutes=minutes_ago)
        return job

    def test_fresh_queued_job_is_not_stuck(self):
        self.assertFalse(self.job("queued", 1).looks_stuck())

    def test_long_queued_job_looks_stuck(self):
        # обычно это значит, что воркер не запущен — и карточка должна
        # сказать об этом, а не показывать «готовится» бесконечно
        self.assertTrue(self.job("queued", 30).looks_stuck())

    def test_running_job_is_never_stuck(self):
        # её уже взяли; долгий рендер — не повод говорить о воркере
        self.assertFalse(self.job("running", 30).looks_stuck())

    def test_long_running_job_looks_crashed(self):
        # OpenCascade на битом файле роняет процесс целиком, и закрыть
        # заявку становится некому — карточка должна сказать об этом
        self.assertTrue(self.job("running", 30).looks_crashed())

    def test_fresh_running_job_is_not_crashed(self):
        self.assertFalse(self.job("running", 1).looks_crashed())

    def test_active_states(self):
        for status, active in (("queued", True), ("running", True),
                               ("done", False), ("failed", False),
                               ("superseded", False)):
            with self.subTest(status=status):
                self.assertIs(self.job(status, 0).is_active, active)



class RenderTaskTests(SimpleTestCase):
    """Рендер описан задачей фреймворка, а не функцией, зовущейся из вида.

    Тогда исполнитель выбирается настройкой: в запросе или отдельным
    воркером, — а код задачи один.
    """

    def test_render_is_a_task(self):
        from django.tasks import Task

        from ..tasks import render_footprint_image

        self.assertIsInstance(render_footprint_image, Task)

    def test_task_goes_to_the_default_queue(self):
        # у бэкенда в базе очереди перечислены в настройках, и задача в
        # неизвестной очереди просто не будет принята
        from ..tasks import render_footprint_image

        self.assertEqual(render_footprint_image.queue_name, "default")
        self.assertEqual(render_footprint_image.name, "render_footprint_image")



class RenderDispatchTests(SimpleTestCase):
    """Куда уходит заявка: в очередь воркера или в отдельный процесс.

    Главное здесь — чего не происходит: рендер никогда не идёт внутри
    запроса. Встроенный бэкенд задач выполнил бы его прямо там, и сайт
    стоял бы, пока модель рисуется.
    """

    def test_default_backend_would_run_in_the_request(self):
        from ..tasks import runs_in_request

        self.assertTrue(runs_in_request())

    def test_without_a_worker_render_goes_to_a_process(self):
        from .. import tasks

        with mock.patch.object(tasks, "runs_in_request", return_value=True), \
                mock.patch.object(tasks, "_spawn_render") as spawn, \
                mock.patch.object(tasks, "render_footprint_image") as queued:
            tasks.dispatch_render(7)
        spawn.assert_called_once_with(7)
        queued.enqueue.assert_not_called()

    def test_with_a_worker_render_goes_to_the_queue(self):
        from .. import tasks

        with mock.patch.object(tasks, "runs_in_request", return_value=False), \
                mock.patch.object(tasks, "_spawn_render") as spawn, \
                mock.patch.object(tasks, "render_footprint_image") as queued:
            tasks.dispatch_render(7)
        queued.enqueue.assert_called_once_with(job_id=7)
        spawn.assert_not_called()

    def test_process_runs_the_render_command(self):
        import tempfile

        from .. import tasks

        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        with self.settings(STEP_QUEUE_DIR=directory), \
                mock.patch.object(tasks.subprocess, "Popen") as popen:
            tasks._spawn_render(42)

        command = popen.call_args.args[0]
        self.assertEqual(command[-2:], ["render_job", "42"])
        # процесс не ждут: вызов вернулся, а результат вида не зависит от
        # того, сколько рисуется модель
        popen.return_value.wait.assert_not_called()
        self.assertTrue((directory / "render.log").exists())



class RenderDisplayTests(SimpleTestCase):
    """Рендер сам даёт VTK экран, если его нет.

    Проверяется всё, кроме запуска самого Xvfb: его здесь нет, а решение,
    поднимать ли экран, — главное, в чём можно ошибиться.
    """

    def test_existing_display_is_used_as_is(self):
        with mock.patch.dict("os.environ", {"DISPLAY": ":0"}), \
                mock.patch("components.step.subprocess.Popen") as popen:
            self.assertTrue(step.ensure_display())
        popen.assert_not_called()

    def test_without_xvfb_there_is_nowhere_to_draw(self):
        # образ без слоя рендера: сказать об этом, а не падать в VTK
        import os

        if os.name == "nt":
            self.skipTest("в Windows экран есть всегда")
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch("components.step.shutil.which", return_value=None):
            self.assertFalse(step.ensure_display())

    def test_windows_needs_no_virtual_display(self):
        with mock.patch("components.step.os.name", "nt"), \
                mock.patch("components.step.subprocess.Popen") as popen:
            self.assertTrue(step.ensure_display())
        popen.assert_not_called()



class RenderJobStatusTests(SimpleTestCase):
    """Ответы опроса заявки на рендер: HTMX понимает каждый по-своему."""

    def ask(self, status):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory

        from .. import image_views as views
        from ..models import StepRenderJob

        job = StepRenderJob(pk=5, status=status, source_name="m.step",
                            message="не прочиталась")
        from django.utils import timezone
        job.created = timezone.now()
        request = RequestFactory().get("/render-jobs/5/?failures=1",
                                       HTTP_HX_REQUEST="true")
        request.user = AnonymousUser()
        request.htmx = True
        with mock.patch.object(views, "get_object_or_404", return_value=job):
            return views.render_job_status(request, 5)

    def test_ready_picture_reloads_the_page(self):
        response = self.ask("done")
        self.assertEqual(response["HX-Refresh"], "true")

    def test_superseded_job_reloads_the_page(self):
        self.assertEqual(self.ask("superseded")["HX-Refresh"], "true")

    def test_failure_stops_polling(self):
        # 286 — условленный у HTMX код «опрос больше не нужен»
        response = self.ask("failed")
        self.assertEqual(response.status_code, 286)
        self.assertIn("не прочиталась", response.content.decode())

    def test_job_in_progress_keeps_polling(self):
        self.assertEqual(self.ask("running").status_code, 200)
