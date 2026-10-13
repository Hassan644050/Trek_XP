from alembic import command


def test_migrations_match_the_models(migrated):
    # Fails if a model changed without a matching migration (or vice versa).
    command.check(migrated)
