# Библиотека компонентов — образ для сервера.
#
# Сборка в два этапа: колёса собираются отдельно, в рабочий образ попадают
# только готовые пакеты. Так в нём не остаётся компилятора и заголовков —
# образ меньше, и лишнего внутри нет.

# ---- сборка зависимостей --------------------------------------------------
FROM python:3.14-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /wheels
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


# ---- рабочий образ --------------------------------------------------------
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings

# curl нужен для HEALTHCHECK; больше в рабочем образе ничего не ставим
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# приложение работает не от root: писать ему в файловую систему нечего,
# BOM-файлы разбираются в памяти и на диск не ложатся
RUN useradd --create-home --uid 10001 app

COPY --from=build /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels requirements.txt

# Рендер STEP-моделей — по желанию. Слой тяжёлый: OpenCascade и VTK вместе
# тянут больше гигабайта, и платить этим стоит, только если рендером
# пользуются. Нужен воркеру фоновых задач; сайту — лишь при встроенном
# бэкенде задач, когда рендер идёт прямо в запросе.
#
#   WITH_STEP=true docker compose build
#
# Системные пакеты — для VTK на сервере без экрана:
#   xvfb                          виртуальный X-сервер; рендер поднимает его
#                                 сам (components/step.py, ensure_display);
#   libgl1-mesa-dri, libglx-mesa0 программный OpenGL Mesa. libgl1 — только
#                                 диспетчер, рисует Mesa, а она приходит
#                                 «рекомендуемой» зависимостью и без явного
#                                 указания отрезается --no-install-recommends:
#                                 экран есть, а рисовать нечем;
#   libx*                         то, что VTK подгружает для работы с X.
ARG WITH_STEP=false
COPY requirements-step.in .
RUN if [ "$WITH_STEP" = "true" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends \
            xvfb libgl1 libgl1-mesa-dri libglx-mesa0 \
            libxrender1 libxext6 libxt6 libxcursor1 \
        && rm -rf /var/lib/apt/lists/* \
        && pip install -r requirements-step.in; \
    fi \
    && rm requirements-step.in

WORKDIR /app
COPY --chown=app:app . .

# Статика собирается на сборке, а не при старте: она не зависит ни от базы,
# ни от настроек окружения, и собранная в образе даёт одинаковый результат
# на всех репликах. Ключ и DEBUG здесь одноразовые, в образ они не попадают:
# collectstatic требует их только чтобы настройки прочитались.
RUN DJANGO_DEBUG=False \
    DJANGO_SECRET_KEY=collectstatic-only \
    DJANGO_ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput --clear \
    && chown -R app:app /app/staticfiles

# Каталоги, куда монтируются тома, заводим заранее и отдаём app. Пустой
# именованный том при первом подключении берёт владельца у каталога в
# образе; если каталога нет, том достаётся root — и приложение, которое
# работает от app, не может записать ни картинку, ни модель в очередь.
RUN mkdir -p /srv/media /srv/step_queue \
    && chown app:app /srv/media /srv/step_queue

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz/ || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "--config", "docker/gunicorn.conf.py", "config.wsgi:application"]
