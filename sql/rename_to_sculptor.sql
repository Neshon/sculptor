-- Переименование проекта: oy_system -> sculptor
--
-- В базе у имени две роли, и меняются они разными командами:
--
--   схема   oy_system     -> sculptor       этот скрипт, изнутри базы
--   база    oy_system_db  -> sculptor_db    sql/rename_database.sql, снаружи
--
-- Порядок действий:
--   1. остановите приложение и всё, что работает с базой, и снимите копию:
--        pg_dump -Fc -d oy_system_db -f before_sculptor.dump
--   2. схема — изнутри базы, пока она называется по-старому:
--        psql -d oy_system_db -f sql/rename_to_sculptor.sql
--   3. сама база — из любой другой, переименовать ту, к которой подключены,
--      Postgres не даёт:
--        psql -d template1 -v old_name=oy_system_db -v new_name=sculptor_db \
--             -f sql/rename_database.sql
--   4. в .env:
--        POSTGRES_DB=sculptor_db
--        POSTGRES_SCHEMA=sculptor,public
--   5. python manage.py check_schema — первой строкой покажет схемы в пути
--      поиска; затем запускайте приложение
--
-- Шаги 2 и 4 — одно действие, разнесённое по двум местам. Если выполнить
-- только одно из них, Django не найдёт своих таблиц: они будут лежать в
-- схеме, которой нет в пути поиска. На этот случай migrate теперь
-- останавливается с объяснением, а не заводит рядом пустой набор таблиц
-- (components/schema_guard.py).
--
-- Переименование схемы не трогает то, что внутри: таблицы, индексы,
-- представления, права и права по умолчанию ссылаются на схему по
-- внутреннему идентификатору, а не по имени, и переезжают вместе с ней.
--
-- Исключение одно — путь поиска, заданный на уровне базы или роли
-- (ALTER DATABASE / ALTER ROLE ... SET search_path). Он хранится текстом,
-- и старое имя в нём после переименования указывает в никуда. Приложение
-- так путь не задаёт — у него свой, из POSTGRES_SCHEMA, — но сторонние
-- программы могли. Скрипт такие настройки находит и перечисляет, а не
-- правит: чьи они и что в них должно быть, решает тот, кто их заводил.
--
-- Скрипт идемпотентный: схема, уже переименованная, пропускается.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'sculptor') THEN
        RAISE NOTICE 'схема sculptor уже есть — пропускаю';
    ELSIF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'oy_system') THEN
        RAISE NOTICE 'схемы oy_system нет — пропускаю';
    ELSE
        ALTER SCHEMA oy_system RENAME TO sculptor;
        RAISE NOTICE 'схема oy_system переименована в sculptor';
    END IF;
END $$;

-- Пути поиска, заданные текстом на уровне базы или роли и всё ещё
-- называющие старую схему
DO $$
DECLARE
    row record;
    found int := 0;
BEGIN
    FOR row IN
        SELECT coalesce(r.rolname, '(все роли)') AS role,
               coalesce(d.datname, '(все базы)') AS db,
               setting
        FROM pg_db_role_setting s
        LEFT JOIN pg_roles r ON r.oid = s.setrole
        LEFT JOIN pg_database d ON d.oid = s.setdatabase,
             unnest(s.setconfig) AS setting
        WHERE setting ILIKE 'search_path=%oy_system%'
    LOOP
        RAISE WARNING 'путь поиска со старым именем: роль %, база %: %',
                      row.role, row.db, row.setting;
        found := found + 1;
    END LOOP;

    IF found = 0 THEN
        RAISE NOTICE 'путей поиска со старым именем схемы не найдено';
    END IF;
END $$;

COMMIT;

-- Проверка результата:
-- SELECT table_schema, count(*) FROM information_schema.tables
-- WHERE table_schema IN ('public', 'sculptor', 'oy_system') GROUP BY 1;
