"""Alembic configuration and migration-chain tests."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from falcon_api.infrastructure.persistence import Base, model_metadata
from falcon_api.models import register_models


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = _REPOSITORY_ROOT / "backend"
_ALEMBIC_CONFIG = _BACKEND_ROOT / "alembic.ini"
_BASELINE_REVISION = "25efb498276a"
_SCHEMA_REVISION = "771fa3a74464"


def create_alembic_config() -> Config:
    """Return the repository Alembic configuration."""
    return Config(str(_ALEMBIC_CONFIG))


def test_alembic_uses_backend_migration_directory() -> None:
    config = create_alembic_config()
    script_location = Path(config.get_main_option("script_location"))

    assert script_location.resolve() == (_BACKEND_ROOT / "migrations").resolve()
    assert config.get_main_option("sqlalchemy.url") == ""


def test_migrations_share_application_metadata() -> None:
    register_models()

    assert model_metadata() is Base.metadata
    assert len(model_metadata().tables) == 12


def test_schema_revision_is_the_single_head() -> None:
    scripts = ScriptDirectory.from_config(create_alembic_config())

    assert scripts.get_heads() == [_SCHEMA_REVISION]

    schema_revision = scripts.get_revision(_SCHEMA_REVISION)

    assert schema_revision is not None
    assert schema_revision.down_revision == _BASELINE_REVISION
    assert schema_revision.branch_labels == set()
    assert schema_revision.dependencies is None


def test_baseline_remains_the_migration_root() -> None:
    scripts = ScriptDirectory.from_config(create_alembic_config())
    baseline = scripts.get_revision(_BASELINE_REVISION)

    assert baseline is not None
    assert baseline.down_revision is None
    assert baseline.module.upgrade() is None
    assert baseline.module.downgrade() is None
