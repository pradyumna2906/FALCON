"""Alembic configuration and migration-chain tests."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from falcon_api.classification.taxonomy import ClassificationSubcategoryCode
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
_PDF_IMPORT_REVISION = "d8f3a2c7b419"
_CLASSIFICATION_REVISION = "e4a7c91d2f63"
_PERSONALIZATION_REVISION = "f7b2d4e8a901"
_FORECAST_PERSISTENCE_REVISION = "a9c4e2f7b613"


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
    assert len(model_metadata().tables) == 23


def test_forecast_persistence_revision_is_the_single_head() -> None:
    scripts = ScriptDirectory.from_config(create_alembic_config())

    assert scripts.get_heads() == [_FORECAST_PERSISTENCE_REVISION]

    forecast_revision = scripts.get_revision(_FORECAST_PERSISTENCE_REVISION)

    assert forecast_revision is not None
    assert forecast_revision.down_revision == _PERSONALIZATION_REVISION
    assert callable(forecast_revision.module.upgrade)
    assert callable(forecast_revision.module.downgrade)


def test_forecast_migration_freezes_owner_scope_provenance_and_immutability() -> None:
    scripts = ScriptDirectory.from_config(create_alembic_config())
    revision = scripts.get_revision(_FORECAST_PERSISTENCE_REVISION)

    assert revision is not None
    source = Path(revision.path).read_text(encoding="utf-8")
    for statement in (
        "forecast_runs",
        "forecast_points",
        "candidate_evidence",
        "data_cutoff_at",
        "fk_forecast_points_owner_run",
        "trg_forecast_runs_immutable",
        "trg_forecast_points_immutable",
        "BEFORE UPDATE ON forecast_runs",
        "BEFORE UPDATE ON forecast_points",
    ):
        assert statement in source


def test_personalization_revision_precedes_forecast_persistence() -> None:
    scripts = ScriptDirectory.from_config(create_alembic_config())

    personalization_revision = scripts.get_revision(_PERSONALIZATION_REVISION)

    assert personalization_revision is not None
    assert personalization_revision.down_revision == _CLASSIFICATION_REVISION
    assert callable(personalization_revision.module.upgrade)
    assert callable(personalization_revision.module.downgrade)


def test_classification_revision_precedes_personalization() -> None:
    scripts = ScriptDirectory.from_config(create_alembic_config())

    classification_revision = scripts.get_revision(_CLASSIFICATION_REVISION)

    assert classification_revision is not None
    assert classification_revision.down_revision == _PDF_IMPORT_REVISION
    assert callable(classification_revision.module.upgrade)
    assert callable(classification_revision.module.downgrade)


def test_pdf_import_revision_precedes_classification() -> None:
    scripts = ScriptDirectory.from_config(create_alembic_config())

    pdf_revision = scripts.get_revision(_PDF_IMPORT_REVISION)

    assert pdf_revision is not None
    assert pdf_revision.down_revision == _IMPORT_PERSISTENCE_REVISION
    assert callable(pdf_revision.module.upgrade)
    assert callable(pdf_revision.module.downgrade)


def test_classification_migration_seeds_every_taxonomy_leaf() -> None:
    scripts = ScriptDirectory.from_config(create_alembic_config())
    revision = scripts.get_revision(_CLASSIFICATION_REVISION)

    assert revision is not None
    categories = revision.module._TAXONOMY_CATEGORIES
    codes = tuple(item[0] for item in categories)
    assert len(codes) == 48
    assert len(set(codes)) == len(codes)
    assert set(codes) == {item.value for item in ClassificationSubcategoryCode}


def test_personalization_migration_freezes_immutable_owner_scoped_feedback() -> None:
    scripts = ScriptDirectory.from_config(create_alembic_config())
    revision = scripts.get_revision(_PERSONALIZATION_REVISION)

    assert revision is not None
    source = Path(revision.path).read_text(encoding="utf-8")
    for statement in (
        "transaction_category_corrections",
        "user_merchant_memories",
        "uq_user_merchant_memories_owner_merchant",
        "fk_transaction_category_corrections_original_classification",
        "trg_transaction_category_corrections_immutable",
        "BEFORE UPDATE ON transaction_category_corrections",
    ):
        assert statement in source


def test_import_persistence_revision_precedes_pdf_import() -> None:
    scripts = ScriptDirectory.from_config(create_alembic_config())

    import_revision = scripts.get_revision(_IMPORT_PERSISTENCE_REVISION)

    assert import_revision is not None
    assert import_revision.down_revision == _AUTH_PERSISTENCE_REVISION
    assert import_revision.branch_labels == set()
    assert import_revision.dependencies is None
    assert callable(import_revision.module.upgrade)
    assert callable(import_revision.module.downgrade)


def test_pdf_import_migration_freezes_check_constraint_names() -> None:
    scripts = ScriptDirectory.from_config(create_alembic_config())
    revision = scripts.get_revision(_PDF_IMPORT_REVISION)

    assert revision is not None
    source = Path(revision.path).read_text(encoding="utf-8")
    for suffix in (
        "adapter_name_not_blank",
        "adapter_matches_source",
        "balance_reconciliation_matches_source",
    ):
        assert source.count(f'op.f("ck_import_jobs_{suffix}")') == 2


def test_import_migration_freezes_convention_qualified_check_names() -> None:
    """Prevent Alembic from applying the check-name prefix twice."""
    scripts = ScriptDirectory.from_config(create_alembic_config())
    revision = scripts.get_revision(_IMPORT_PERSISTENCE_REVISION)

    assert revision is not None
    source = Path(revision.path).read_text(encoding="utf-8")
    check_names = (
        "date_order_allowed",
        "header_row_bounded",
        "sheet_name_not_blank",
        "file_fingerprint_sha256_hex",
        "lifecycle_consistent",
        "reconciliation_consistent",
    )

    for suffix in check_names:
        expected = f'op.f("ck_import_jobs_{suffix}")'
        assert source.count(expected) == 2


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
