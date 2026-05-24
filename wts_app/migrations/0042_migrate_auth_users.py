import uuid

from django.db import migrations


def _auth_user_table_exists(schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = DATABASE() AND table_name = 'auth_user'
            """
        )
        return cursor.fetchone()[0] > 0


def copy_auth_users(apps, schema_editor):
    if not _auth_user_table_exists(schema_editor):
        return

    User = apps.get_model("wts_app", "User")
    if User.objects.exists():
        return

    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, password, last_login, is_superuser, username, first_name,
                   last_name, email, is_staff, is_active, date_joined
            FROM auth_user
            """
        )
        user_rows = cursor.fetchall()

        cursor.execute("SELECT user_id, group_id FROM auth_user_groups")
        group_rows = cursor.fetchall()

        cursor.execute("SELECT user_id, permission_id FROM auth_user_user_permissions")
        permission_rows = cursor.fetchall()

    id_map = {}
    for (
        old_id,
        password,
        last_login,
        is_superuser,
        username,
        first_name,
        last_name,
        email,
        is_staff,
        is_active,
        date_joined,
    ) in user_rows:
        new_id = uuid.uuid4()
        id_map[old_id] = new_id
        User.objects.create(
            id=new_id,
            password=password,
            last_login=last_login,
            is_superuser=is_superuser,
            username=username,
            first_name=first_name,
            last_name=last_name,
            email=email,
            is_staff=is_staff,
            is_active=is_active,
            date_joined=date_joined,
        )

    UserGroups = User.groups.through
    for old_user_id, group_id in group_rows:
        new_user_id = id_map.get(old_user_id)
        if new_user_id is not None:
            UserGroups.objects.get_or_create(user_id=new_user_id, group_id=group_id)

    UserPermissions = User.user_permissions.through
    for old_user_id, permission_id in permission_rows:
        new_user_id = id_map.get(old_user_id)
        if new_user_id is not None:
            UserPermissions.objects.get_or_create(
                user_id=new_user_id, permission_id=permission_id
            )


class Migration(migrations.Migration):

    dependencies = [
        ("wts_app", "0041_user"),
    ]

    operations = [
        migrations.RunPython(copy_auth_users, migrations.RunPython.noop),
    ]
