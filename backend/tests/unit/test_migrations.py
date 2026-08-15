"""Alembic configuration and baseline revision tests."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from falcon_api.infrastructure.persistence import Base, model_metadata


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = _REPOSITORY_ROOT / "backend"
_ALEMBIC_CONFIG = _BACKEND_ROOT / "alembic.ini"
_BASELINE_REVISION = "25efb498276a"


def create_alembic_config() -> Config:
    """Return the repository Alembic configuration."""
    return Config(str(_ALEMBIC_CONFIG))


def test_alembic_uses_backend_migration_directory() -> None:
    config = create_alembic_config()
    script_location = Path(config.get_main_option("script_location"))

    assert script_location.resolve() == (_BACKEND_ROOT / "migrations").resolve()
    assert config.get_main_option("sqlalchemy.url") == ""


def test_migrations_share_application_metadata() -> None:
    assert model_metadata() is Base.metadata
    assert len(model_metadata().tables) == 0


def test_baseline_is_the_single_reversible_head() -> None:
    scripts = ScriptDirectory.from_config(create_alembic_config())

    assert scripts.get_heads() == [_BASELINE_REVISION]

    baseline = scripts.get_revision(_BASELINE_REVISION)

    assert baseline is not None
    assert baseline.down_revision is None
    assert baseline.branch_labels == set()
    assert baseline.dependencies is None
    assert baseline.module.upgrade() is None
    assert baseline.module.downgrade() is None
