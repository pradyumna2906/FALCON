"""Authentication-model metadata, integrity, and performance tests."""

from falcon_api.infrastructure.persistence import Base
from falcon_api.models import (
    AuthenticationChallenge,
    AuthenticationDelivery,
    RefreshSession,
    RefreshToken,
    User,
    UserCredential,
    register_models,
)
from falcon_api.models.enums import (
    AuthenticationChallengePurpose,
    AuthenticationDeliveryStatus,
    enum_sql_values,
)
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, LargeBinary
from sqlalchemy.orm import configure_mappers


_AUTH_TABLES = {
    "authentication_challenges",
    "authentication_delivery_outbox",
    "refresh_sessions",
    "refresh_tokens",
    "user_credentials",
}


def check_names(table_name: str) -> set[str]:
    """Return the named check constraints for one table."""
    table = Base.metadata.tables[table_name]

    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name is not None
    }


def foreign_key_names(table_name: str) -> set[str]:
    """Return the named foreign keys for one table."""
    table = Base.metadata.tables[table_name]

    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name is not None
    }


def indexes(table_name: str) -> dict[str, Index]:
    """Return explicitly defined indexes keyed by name."""
    table = Base.metadata.tables[table_name]

    return {
        index.name: index
        for index in table.indexes
        if index.name is not None
    }


def postgresql_predicate(index: Index) -> str:
    """Return the PostgreSQL partial-index predicate."""
    predicate = index.dialect_options["postgresql"]["where"]

    assert predicate is not None

    return str(predicate)


def test_authentication_tables_are_registered() -> None:
    register_models()
    configure_mappers()

    assert _AUTH_TABLES <= set(Base.metadata.tables)
    assert len(Base.metadata.tables) == 17


def test_authentication_tables_use_uuid_and_utc_audit_columns() -> None:
    for table_name in _AUTH_TABLES:
        table = Base.metadata.tables[table_name]

        assert table.c.id.primary_key is True
        assert table.c.id.nullable is False
        assert table.c.id.default is not None

        assert table.c.created_at.nullable is False
        assert table.c.created_at.type.timezone is True

        assert table.c.updated_at.nullable is False
        assert table.c.updated_at.type.timezone is True


def test_user_verification_timestamp_is_optional_and_timezone_aware() -> None:
    column = User.__table__.c.email_verified_at

    assert column.nullable is True
    assert column.type.timezone is True
    assert (
        "ck_users_email_verification_not_before_creation"
        in check_names("users")
    )


def test_password_credential_contract_is_explicit() -> None:
    table = UserCredential.__table__

    assert table.c.user_id.nullable is False
    assert table.c.user_id.unique is True
    assert table.c.password_hash.nullable is False
    assert table.c.password_hash.type.length == 512
    assert table.c.password_changed_at.nullable is False
    assert table.c.password_changed_at.type.timezone is True

    assert "password" not in table.c
    assert "plaintext_password" not in table.c

    assert (
        "ck_user_credentials_password_hash_length"
        in check_names("user_credentials")
    )
    assert (
        "ck_user_credentials_password_hash_argon2id"
        in check_names("user_credentials")
    )
    assert (
        "ck_user_credentials_password_changed_not_before_creation"
        in check_names("user_credentials")
    )


def test_only_hashed_refresh_and_challenge_tokens_are_persisted() -> None:
    refresh_columns = set(RefreshToken.__table__.c.keys())
    challenge_columns = set(AuthenticationChallenge.__table__.c.keys())

    assert "token" not in refresh_columns
    assert "raw_token" not in refresh_columns
    assert "token_hash" in refresh_columns

    assert "token" not in challenge_columns
    assert "raw_token" not in challenge_columns
    assert "token_hash" in challenge_columns

    assert RefreshToken.__table__.c.token_hash.type.length == 64
    assert RefreshToken.__table__.c.token_hash.unique is True

    assert AuthenticationChallenge.__table__.c.token_hash.type.length == 64
    assert AuthenticationChallenge.__table__.c.token_hash.unique is True


def test_authentication_foreign_keys_have_explicit_cascade_ownership() -> None:
    assert (
        "fk_user_credentials_user_id_users"
        in foreign_key_names("user_credentials")
    )
    assert (
        "fk_refresh_sessions_user_id_users"
        in foreign_key_names("refresh_sessions")
    )
    assert (
        "fk_refresh_tokens_session_id_refresh_sessions"
        in foreign_key_names("refresh_tokens")
    )
    assert (
        "fk_authentication_challenges_user_id_users"
        in foreign_key_names("authentication_challenges")
    )
    assert (
        "fk_authentication_delivery_outbox_user_id_users"
        in foreign_key_names("authentication_delivery_outbox")
    )
    assert (
        "fk_auth_delivery_outbox_challenge"
        in foreign_key_names("authentication_delivery_outbox")
    )

    for table_name in _AUTH_TABLES:
        table = Base.metadata.tables[table_name]

        for constraint in table.foreign_key_constraints:
            assert constraint.ondelete == "CASCADE"


def test_refresh_lifecycle_constraints_are_present() -> None:
    session_checks = check_names("refresh_sessions")
    token_checks = check_names("refresh_tokens")

    assert "ck_refresh_sessions_expiry_after_creation" in session_checks
    assert (
        "ck_refresh_sessions_last_used_not_before_creation"
        in session_checks
    )
    assert "ck_refresh_sessions_last_used_not_after_expiry" in session_checks
    assert (
        "ck_refresh_sessions_revocation_not_before_creation"
        in session_checks
    )
    assert (
        "ck_refresh_sessions_revocation_state_consistent"
        in session_checks
    )

    assert "ck_refresh_tokens_token_hash_sha256_hex" in token_checks
    assert "ck_refresh_tokens_use_not_before_creation" in token_checks


def test_challenge_lifecycle_constraints_are_present() -> None:
    challenge_checks = check_names("authentication_challenges")

    assert (
        "ck_authentication_challenges_purpose_allowed"
        in challenge_checks
    )
    assert (
        "ck_authentication_challenges_token_hash_sha256_hex"
        in challenge_checks
    )
    assert (
        "ck_authentication_challenges_expiry_after_creation"
        in challenge_checks
    )
    assert (
        "ck_authentication_challenges_consumption_not_before_creation"
        in challenge_checks
    )
    assert (
        "ck_authentication_challenges_invalidation_not_before_creation"
        in challenge_checks
    )
    assert (
        "ck_authentication_challenges_terminal_state_exclusive"
        in challenge_checks
    )


def test_delivery_outbox_never_stores_plaintext_token_columns() -> None:
    table = AuthenticationDelivery.__table__
    columns = set(table.c.keys())

    assert "token" not in columns
    assert "raw_token" not in columns
    assert "payload" not in columns

    assert isinstance(table.c.encrypted_payload.type, LargeBinary)
    assert table.c.encrypted_payload.nullable is False
    assert table.c.encryption_key_id.nullable is False
    assert table.c.challenge_id.unique is True

    assert (
        "ck_authentication_delivery_outbox_status_allowed"
        in check_names("authentication_delivery_outbox")
    )
    assert (
        "ck_authentication_delivery_outbox_attempt_count_non_negative"
        in check_names("authentication_delivery_outbox")
    )
    assert (
        "ck_authentication_delivery_outbox_processing_state_consistent"
        in check_names("authentication_delivery_outbox")
    )
    assert (
        "ck_authentication_delivery_outbox_processed_not_before_creation"
        in check_names("authentication_delivery_outbox")
    )

def test_query_driven_authentication_indexes_are_present() -> None:
    session_indexes = indexes("refresh_sessions")
    token_indexes = indexes("refresh_tokens")
    challenge_indexes = indexes("authentication_challenges")
    delivery_indexes = indexes("authentication_delivery_outbox")

    active_sessions = session_indexes["ix_refresh_sessions_user_active"]
    assert tuple(column.name for column in active_sessions.columns) == (
        "user_id",
        "expires_at",
    )
    assert postgresql_predicate(active_sessions) == "revoked_at IS NULL"

    family = session_indexes["ix_refresh_sessions_family"]
    assert tuple(column.name for column in family.columns) == ("family_id",)

    active_token = token_indexes["uq_refresh_tokens_session_active"]
    assert active_token.unique is True
    assert postgresql_predicate(active_token) == "used_at IS NULL"

    active_challenge = challenge_indexes[
        "uq_authentication_challenges_user_purpose_active"
    ]
    assert active_challenge.unique is True
    assert (
        postgresql_predicate(active_challenge)
        == "consumed_at IS NULL AND invalidated_at IS NULL"
    )

    pending_delivery = delivery_indexes[
        "ix_authentication_delivery_outbox_pending"
    ]
    assert (
        postgresql_predicate(pending_delivery)
        == "status IN ('pending', 'failed') AND processed_at IS NULL"
    )


def test_authentication_relationship_cardinalities_are_configured() -> None:
    assert User.credential.property.uselist is False
    assert User.refresh_sessions.property.uselist is True
    assert User.authentication_challenges.property.uselist is True
    assert User.authentication_deliveries.property.uselist is True

    assert RefreshSession.tokens.property.uselist is True
    assert AuthenticationChallenge.delivery.property.uselist is False

def test_authentication_object_names_fit_postgresql_limit() -> None:
    for table_name in _AUTH_TABLES:
        table = Base.metadata.tables[table_name]

        object_names = [
            table.name,
            *[
                constraint.name
                for constraint in table.constraints
                if constraint.name is not None
            ],
            *[
                index.name
                for index in table.indexes
                if index.name is not None
            ],
        ]

        for object_name in object_names:
            assert len(object_name) <= 63, object_name

def test_authentication_enum_values_are_stable() -> None:
    challenge_values = enum_sql_values(AuthenticationChallengePurpose)
    delivery_values = enum_sql_values(AuthenticationDeliveryStatus)

    assert "'email_verification'" in challenge_values
    assert "'password_reset'" in challenge_values

    assert "'pending'" in delivery_values
    assert "'processing'" in delivery_values
    assert "'sent'" in delivery_values
    assert "'failed'" in delivery_values
