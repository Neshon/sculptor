"""Рендер одной заявки на картинку посадочного места.

Эту команду не запускают руками: её запускает сайт отдельным процессом,
когда воркера фоновых задач нет (встроенный бэкенд задач, по умолчанию) —
см. :mod:`components.tasks`. Так рендер не держит запрос и не останавливает
сайт.

Но руками её запустить можно — например, чтобы повторить застрявшую
заявку и увидеть ошибку своими глазами:

    python manage.py render_job 42
"""

from django.core.management.base import BaseCommand

from components.tasks import run_render_job


class Command(BaseCommand):
    help = "Рендерит одну заявку на картинку посадочного места"

    def add_arguments(self, parser):
        parser.add_argument("job_id", type=int, help="Номер заявки")

    def handle(self, *args, **options):
        status = run_render_job(options["job_id"])
        self.stdout.write(f"Заявка {options['job_id']}: {status}")
