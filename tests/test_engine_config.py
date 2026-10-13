from app.db.engine import build_engine_config


NEON_POOLED = (
    "postgresql://app:secret@ep-cool-name-123-pooler.ap-southeast-1.aws.neon.tech/neondb"
    "?sslmode=require&channel_binding=require"
)
NEON_DIRECT = NEON_POOLED.replace("-pooler", "")


def test_neon_url_is_translated_for_asyncpg():
    config = build_engine_config(NEON_DIRECT)

    assert config.url.startswith("postgresql+asyncpg://app:secret@ep-cool-name-123.")
    # libpq-only options removed from the URL; TLS kept via connect_args.
    assert "sslmode" not in config.url
    assert "channel_binding" not in config.url
    assert config.connect_args == {"ssl": "require"}
    assert config.use_null_pool is False


def test_pooled_endpoint_gets_pgbouncer_safe_settings():
    config = build_engine_config(NEON_POOLED)

    assert config.use_null_pool is True
    assert config.connect_args["ssl"] == "require"
    assert config.connect_args["statement_cache_size"] == 0
    assert config.connect_args["prepared_statement_cache_size"] == 0

    name_func = config.connect_args["prepared_statement_name_func"]
    assert name_func() != name_func()


def test_postgres_scheme_alias_and_other_params_survive():
    config = build_engine_config("postgres://u:p@localhost:5433/trek?application_name=trekxp")

    assert config.url == "postgresql+asyncpg://u:p@localhost:5433/trek?application_name=trekxp"
    assert config.connect_args == {}


def test_disabled_ssl_is_not_forced():
    config = build_engine_config("postgresql://u:p@localhost/trek?sslmode=disable")
    assert "ssl" not in config.connect_args
