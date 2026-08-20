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
_DOMAIN_SCHEMA_REVISION = "771fa3a74464"
_HARDENING_REVISION = "a1b1833784e5"
_AUTH_PERSISTENCE_REVISION = "7fff19ce50be"
_IMPORT_PERSISTENCE_REVISION = "c5a9e0b2d641"


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
    assert len(model_metadata().tables) == 18


def test_import_persistence_revision_is_the_single_head() -> None:
    scripts = ScriptDirectory.from_config(create_alembic_config())

    assert scripts.get_heads() == [_IMPORT_PERSISTENCE_REVISION]

    import_revision = scripts.get_revision(_IMPORT_PERSISTENCE_REVISION)

    assert import_revision is not None
    assert import_revision.down_revision == _AUTH_PERSISTENCE_REVISION
    assert import_revision.branch_labels == set()
    assert import_revision.dependencies is None
    assert callable(import_revision.module.upgrade)
    assert callable(import_revision.module.downgrade)


def test_authentication_persistence_precedes_import_persistence() -> None:
    scripts = ScriptDirectory.from_config(create_alembic_config())

    authentication_revision = scripts.get_revision(
        _AUTH_PERSISTENCE_REVISION
    )

    assert authentication_revision is not None
    assert authentication_revision.down_revision == _HARDENING_REVISION
    assert authentication_revision.branch_labels == set()
    assert authentication_revision.dependencies is None
    assert callable(authentication_revision.module.upgrade)
    assert callable(authentication_revision.module.downgrade)


def test_hardening_revision_follows_the_domain_schema() -> None:
    scripts = ScriptDirectory.from_config(create_alembic_config())
    hardening_revision = scripts.get_revision(_HARDENING_REVISION)

    assert hardening_revision is not None
    assert hardening_revision.down_revision == _DOMAIN_SCHEMA_REVISION
    assert hardening_revision.branch_labels == set()
    assert hardening_revision.dependencies is None


def test_domain_schema_follows_the_empty_baseline() -> None:
    scripts = ScriptDirectory.from_config(create_alembic_config())
    domain_revision = scripts.get_revision(_DOMAIN_SCHEMA_REVISION)

    assert domain_revision is not None
    assert domain_revision.down_revision == _BASELINE_REVISION


def test_baseline_remains_the_migration_root() -> None:
    scripts = ScriptDirectory.from_config(create_alembic_config())
    baseline = scripts.get_revision(_BASELINE_REVISION)

    assert baseline is not None
    assert baseline.down_revision is None
    assert baseline.module.upgrade() is None
    assert baseline.module.downgrade() is None
