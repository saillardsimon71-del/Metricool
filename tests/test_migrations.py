"""Migrations Alembic : une base vierge atteint le schéma courant."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect

TABLES_ATTENDUES = {
    "accounts",
    "account_groups",
    "analytics_samples",
    "app_settings",
    "event_log",
    "media_assets",
    "oauth_states",
    "post_targets",
    "post_templates",
    "posts",
    "publish_attempts",
    "series",
    "watched_folders",
}


def test_upgrade_head_cree_le_schema_complet(tmp_path: Path):
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "migration.sqlite3"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert tables >= TABLES_ATTENDUES, f"tables manquantes : {TABLES_ATTENDUES - tables}"
    assert "alembic_version" in tables


def test_downgrade_puis_reupgrade(tmp_path: Path):
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "aller-retour.sqlite3"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(config, "head")
    command.downgrade(config, "base")
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        assert "posts" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        assert "posts" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
