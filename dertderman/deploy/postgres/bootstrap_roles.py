from pathlib import Path
import os

import psycopg
from psycopg import sql


def required(name):
    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(
            f"{name} is required."
        )

    return value


def read_secret(name):
    path = Path(
        required(name)
    )

    value = path.read_text(
        encoding="utf-8",
    ).strip()

    if not value:
        raise RuntimeError(
            f"{name} is empty."
        )

    return value


database = required(
    "POSTGRES_DB"
)

admin_user = required(
    "POSTGRES_ADMIN_USER"
)

migrator_user = required(
    "POSTGRES_MIGRATOR_USER"
)

app_user = required(
    "POSTGRES_APP_USER"
)

admin_password = read_secret(
    "POSTGRES_ADMIN_PASSWORD_FILE"
)

migrator_password = read_secret(
    "POSTGRES_MIGRATOR_PASSWORD_FILE"
)

app_password = read_secret(
    "POSTGRES_APP_PASSWORD_FILE"
)


connection = psycopg.connect(
    host=required(
        "POSTGRES_HOST"
    ),
    port=int(
        os.getenv(
            "POSTGRES_PORT",
            "5432",
        )
    ),
    dbname=database,
    user=admin_user,
    password=admin_password,
    autocommit=True,
)


with connection:
    with connection.cursor() as cursor:

        def role_exists(role):
            cursor.execute(
                """
                SELECT 1
                FROM pg_roles
                WHERE rolname = %s
                """,
                (role,),
            )

            return (
                cursor.fetchone()
                is not None
            )

        if not role_exists(
            migrator_user
        ):
            cursor.execute(
                sql.SQL(
                    """
                    CREATE ROLE {}
                    LOGIN
                    PASSWORD {}
                    NOSUPERUSER
                    NOCREATEDB
                    NOCREATEROLE
                    NOREPLICATION
                    """
                ).format(
                    sql.Identifier(
                        migrator_user
                    ),
                    sql.Literal(
                        migrator_password
                    ),
                )
            )

        cursor.execute(
            sql.SQL(
                """
                ALTER ROLE {}
                WITH
                LOGIN
                PASSWORD {}
                NOSUPERUSER
                NOCREATEDB
                NOCREATEROLE
                NOREPLICATION
                """
            ).format(
                sql.Identifier(
                    migrator_user
                ),
                sql.Literal(
                    migrator_password
                ),
            )
        )

        if not role_exists(
            app_user
        ):
            cursor.execute(
                sql.SQL(
                    """
                    CREATE ROLE {}
                    LOGIN
                    PASSWORD {}
                    NOSUPERUSER
                    NOCREATEDB
                    NOCREATEROLE
                    NOREPLICATION
                    """
                ).format(
                    sql.Identifier(
                        app_user
                    ),
                    sql.Literal(
                        app_password
                    ),
                )
            )

        cursor.execute(
            sql.SQL(
                """
                ALTER ROLE {}
                WITH
                LOGIN
                PASSWORD {}
                NOSUPERUSER
                NOCREATEDB
                NOCREATEROLE
                NOREPLICATION
                """
            ).format(
                sql.Identifier(
                    app_user
                ),
                sql.Literal(
                    app_password
                ),
            )
        )

        cursor.execute(
            sql.SQL(
                "ALTER DATABASE {} OWNER TO {}"
            ).format(
                sql.Identifier(
                    database
                ),
                sql.Identifier(
                    migrator_user
                ),
            )
        )

        cursor.execute(
            sql.SQL(
                "ALTER SCHEMA public OWNER TO {}"
            ).format(
                sql.Identifier(
                    migrator_user
                )
            )
        )

        cursor.execute(
            sql.SQL(
                "GRANT CONNECT ON DATABASE {} TO {}"
            ).format(
                sql.Identifier(
                    database
                ),
                sql.Identifier(
                    app_user
                ),
            )
        )

        cursor.execute(
            sql.SQL(
                "GRANT USAGE ON SCHEMA public TO {}"
            ).format(
                sql.Identifier(
                    app_user
                )
            )
        )

        cursor.execute(
            sql.SQL(
                """
                ALTER DEFAULT PRIVILEGES
                FOR ROLE {}
                IN SCHEMA public
                GRANT
                    SELECT,
                    INSERT,
                    UPDATE,
                    DELETE
                ON TABLES
                TO {}
                """
            ).format(
                sql.Identifier(
                    migrator_user
                ),
                sql.Identifier(
                    app_user
                ),
            )
        )

        cursor.execute(
            sql.SQL(
                """
                ALTER DEFAULT PRIVILEGES
                FOR ROLE {}
                IN SCHEMA public
                GRANT
                    USAGE,
                    SELECT,
                    UPDATE
                ON SEQUENCES
                TO {}
                """
            ).format(
                sql.Identifier(
                    migrator_user
                ),
                sql.Identifier(
                    app_user
                ),
            )
        )


print(
    "PostgreSQL production roles bootstrapped."
)
