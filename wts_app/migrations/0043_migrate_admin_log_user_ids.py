from django.db import migrations


def _table_exists(cursor, table_name):
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = %s
        """,
        [table_name],
    )
    return cursor.fetchone()[0] > 0


def _admin_log_user_fk_name(cursor):
    cursor.execute(
        """
        SELECT CONSTRAINT_NAME
        FROM information_schema.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'django_admin_log'
          AND COLUMN_NAME = 'user_id'
          AND REFERENCED_TABLE_NAME IS NOT NULL
        """
    )
    row = cursor.fetchone()
    return row[0] if row else None


def _admin_log_user_id_is_integer(cursor):
    cursor.execute(
        """
        SELECT DATA_TYPE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'django_admin_log'
          AND COLUMN_NAME = 'user_id'
        """
    )
    row = cursor.fetchone()
    return row and row[0] in {"int", "bigint", "mediumint", "smallint", "tinyint"}


def migrate_admin_log_user_ids(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        if not _table_exists(cursor, "django_admin_log"):
            return
        if not _table_exists(cursor, "wts_app_user"):
            return
        if not _admin_log_user_id_is_integer(cursor):
            return

        fk_name = _admin_log_user_fk_name(cursor)
        if fk_name:
            cursor.execute(f"ALTER TABLE django_admin_log DROP FOREIGN KEY `{fk_name}`")

        cursor.execute(
            """
            ALTER TABLE django_admin_log
            ADD COLUMN user_uuid char(32) NULL
            """
        )

        if _table_exists(cursor, "auth_user"):
            cursor.execute(
                """
                UPDATE django_admin_log dal
                INNER JOIN auth_user au ON dal.user_id = au.id
                INNER JOIN wts_app_user wu ON wu.username = au.username
                SET dal.user_uuid = wu.id
                """
            )
        else:
            cursor.execute("DELETE FROM django_admin_log")

        cursor.execute("DELETE FROM django_admin_log WHERE user_uuid IS NULL")

        cursor.execute("ALTER TABLE django_admin_log DROP COLUMN user_id")
        cursor.execute(
            """
            ALTER TABLE django_admin_log
            CHANGE COLUMN user_uuid user_id char(32) NOT NULL
            """
        )
        cursor.execute(
            """
            ALTER TABLE django_admin_log
            ADD CONSTRAINT django_admin_log_user_id_fk_wts_app_user_id
            FOREIGN KEY (user_id) REFERENCES wts_app_user (id)
            """
        )


def clear_stale_sessions(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        if _table_exists(cursor, "django_session"):
            cursor.execute("DELETE FROM django_session")


class Migration(migrations.Migration):

    dependencies = [
        ("wts_app", "0042_migrate_auth_users"),
    ]

    operations = [
        migrations.RunPython(migrate_admin_log_user_ids, migrations.RunPython.noop),
        migrations.RunPython(clear_stale_sessions, migrations.RunPython.noop),
    ]
