-- Переезд пользователя: auth.User -> users.User
--
-- Код теперь использует свою модель пользователя (users/models.py,
-- AUTH_USER_MODEL = "users.User"). Она повторяет стандартную поле в поле,
-- поэтому переезд — не перенос данных, а переименование: таблицы
-- стандартного пользователя становятся таблицами новой модели, и все
-- пользователи, пароли, группы и права остаются на месте.
--
-- Что делает скрипт:
--   1. переименовывает таблицы:
--        auth_user                  -> users_user
--        auth_user_groups           -> users_user_groups
--        auth_user_user_permissions -> users_user_user_permissions
--   2. переносит тип объекта (django_content_type) auth.user -> users.user:
--      на него ссылаются права на пользователей и журнал админки, и они
--      переезжают вместе с ним;
--   3. отмечает миграцию users.0001_initial выполненной — таблицы уже есть,
--      создавать их незачем.
--
-- Внешние ключи на пользователя (журнал админки, связи с группами и
-- правами) PostgreSQL хранит по внутреннему идентификатору таблицы, а не
-- по имени, — после переименования они указывают туда же.
--
-- ПОРЯДОК ВАЖЕН: скрипт выполняется ДО запуска нового кода. В Docker
-- migrate идёт при каждом старте контейнера, и новый код без скрипта
-- остановится на нём с InconsistentMigrationHistory: журнал админки уже
-- применён, а миграция пользователя, от которой он теперь зависит, — нет.
-- Данные при этом не пострадают, но сайт не запустится, пока скрипт не
-- выполнен.
--
-- Порядок действий:
--   1. остановите приложение и всё, что работает с базой:
--        docker compose stop web worker
--   2. снимите копию:
--        pg_dump -Fc -d sculptor_db -f before_users.dump
--   3. psql -d sculptor_db -f sql/move_user_to_users.sql
--   4. обновите код и запустите:
--        docker compose up -d --build
--
-- Скрипт идемпотентный: то, что уже переехало, пропускается.

BEGIN;

-- таблицы Django — в схеме sculptor (см. sql/rename_to_sculptor.sql)
SET search_path TO sculptor, oy_system, public;

DO $$
DECLARE
    pair    text[];
    pairs   text[][] := ARRAY[
        ARRAY['auth_user', 'users_user'],
        ARRAY['auth_user_groups', 'users_user_groups'],
        ARRAY['auth_user_user_permissions', 'users_user_user_permissions']
    ];
BEGIN
    FOREACH pair SLICE 1 IN ARRAY pairs LOOP
        IF to_regclass(pair[2]) IS NOT NULL THEN
            RAISE NOTICE 'таблица % уже есть — пропускаю', pair[2];
        ELSIF to_regclass(pair[1]) IS NULL THEN
            RAISE NOTICE 'таблицы % нет — пропускаю', pair[1];
        ELSE
            EXECUTE format('ALTER TABLE %I RENAME TO %I', pair[1], pair[2]);
            RAISE NOTICE 'таблица % -> %', pair[1], pair[2];
        END IF;

        -- последовательность за таблицей не следует: у неё своё имя
        IF to_regclass(pair[1] || '_id_seq') IS NOT NULL
           AND to_regclass(pair[2] || '_id_seq') IS NULL THEN
            EXECUTE format('ALTER SEQUENCE %I RENAME TO %I',
                           pair[1] || '_id_seq', pair[2] || '_id_seq');
        END IF;
    END LOOP;
END $$;

-- Тип объекта. Строку трогаем, только если users.user ещё нет: пара
-- (app_label, model) уникальна, и вторая такая же уронила бы обновление
UPDATE django_content_type AS old
SET app_label = 'users'
WHERE old.app_label = 'auth' AND old.model = 'user'
  AND NOT EXISTS (
      SELECT 1 FROM django_content_type AS new
      WHERE new.app_label = 'users' AND new.model = 'user');

-- Миграция модели — выполненной: её таблицы получены переименованием
INSERT INTO django_migrations (app, name, applied)
SELECT 'users', '0001_initial', now()
WHERE NOT EXISTS (
    SELECT 1 FROM django_migrations
    WHERE app = 'users' AND name = '0001_initial');

COMMIT;

-- Проверка:
-- SELECT count(*) FROM users_user;
-- SELECT app_label, model FROM django_content_type WHERE model = 'user';
-- SELECT app, name FROM django_migrations WHERE app = 'users';
