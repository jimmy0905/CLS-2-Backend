"""Explicit production database migration entry point.

Application containers keep ``DATABASE_AUTO_MIGRATE=false``.  The regional
deploy CLI runs this module once per selected profile before replacing its app
container, so a failed migration never starts a partly-compatible release.
"""

from infrastructure.database.migrations import run_database_migrations


def main() -> None:
    if not run_database_migrations():
        raise RuntimeError(
            "DATABASE_AUTO_MIGRATE must be true for the dedicated migration job"
        )


if __name__ == "__main__":
    main()
