"""Защита от миграций мимо своей схемы.

Django ищет свои таблицы по пути поиска (``POSTGRES_SCHEMA``), и если в
этом пути нет схемы, где они лежат, он их не видит. Для ``migrate`` это
не ошибка, а чистая база: он спокойно заводит полный набор таблиц в
первой существующей схеме пути — обычно в ``public``. Приложение после
этого запускается и работает, только пустое: плат, изделий, истории и
справочников в нём нет, потому что настоящие лежат рядом, в соседней
схеме. А новые записи, сделанные за это время, оказываются уже в другом
месте, и сводить две половины потом — ручная работа.

Проще всего попасть в это при переименовании схемы: схему переименовали,
а ``POSTGRES_SCHEMA`` в ``.env`` оставили прежним (или наоборот). В
Docker ``migrate`` выполняется при каждом старте контейнера сам, так что
заметить ошибку до того, как она случится, некому.

Проверка перед миграциями: если таблица ``django_migrations`` в пути
поиска не видна, но есть в какой-то другой схеме этой же базы, ``migrate``
останавливается и говорит, где она. Чистую базу — без неё нигде — это не
задевает.
"""

from django.core.management.base import CommandError
from django.db import DEFAULT_DB_ALIAS, connections


def django_home(using=DEFAULT_DB_ALIAS):
    """Где лежат таблицы Django и какие схемы видны.

    ``(схемы с django_migrations, схемы пути поиска)``. ``current_schemas``
    отбрасывает схемы, которых в базе нет, — именно это и нужно: схема,
    названная в пути, но переименованная, должна считаться невидимой.
    """
    connection = connections[using]
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_schemas(false)")
        path = list(cursor.fetchone()[0] or [])
        cursor.execute("""
            SELECT n.nspname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = 'django_migrations' AND c.relkind IN ('r', 'p')
            ORDER BY 1
        """)
        homes = [row[0] for row in cursor.fetchall()]
    return homes, path


def check_before_migrate(sender, using=DEFAULT_DB_ALIAS, **kwargs):
    """Приёмник ``pre_migrate``: останавливает миграции мимо своей схемы."""
    if connections[using].vendor != "postgresql":
        return

    homes, path = django_home(using)
    if not homes or any(home in path for home in homes):
        return

    raise CommandError(
        "Миграции остановлены: таблицы Django лежат в схеме "
        f"{', '.join(homes)}, а её нет в пути поиска "
        f"(сейчас в нём: {', '.join(path) or 'пусто'}). Продолжи migrate — "
        "он завёл бы рядом второй, пустой набор таблиц. Проверьте "
        "POSTGRES_SCHEMA в .env: после переименования схемы "
        "(sql/rename_to_sculptor.sql) там должно быть sculptor,public.")
