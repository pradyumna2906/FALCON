"""Real PostgreSQL integrity tests for authentication persistence."""

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from falcon_api.core.config import AppEnvironment, Settings
from psycopg.errors import CheckViolation, UniqueViolation


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FALCON_RUN_DATABASE_INTEGRATION") != "1",
        reason="Set FALCON_RUN_DATABASE_INTEGRATION=1 to enable these tests.",
    ),
]

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_CONFIG = _REPOSITORY_ROOT / "backend" / "alembic.ini"

_VALID_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$"
    "c2FsdHNhbHRzYWx0c2FsdA$"
    "aGFzaGhhc2hoYXNoaGFzaGhhc2hoYXNoaGFzaGhhc2g"
)


def integration_settings() -> Settings:
    """Load the ignored root environment for PostgreSQL tests."""
    return Settings(
        _env_file=_REPOSITORY_ROOT / ".env",
        env=AppEnvironment.TEST,
        debug=False,
        docs_enabled=False,
        cors_allowed_origins=(),
    )


def connect_to_postgresql() -> psycopg.Connection:
    """Open a synchronous test connection to PostgreSQL."""
    settings = integration_settings()

    return psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
        connect_timeout=settings.db_connect_timeout_seconds,
    )


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    """Run authentication tests against the reviewed migration head."""
    config = Config(str(_ALEMBIC_CONFIG))
    command.upgrade(config, "head")

    try:
        yield
    finally:
        command.downgrade(config, "base")


def insert_user(connection: psycopg.Connection, *, email: str) -> UUID:
    """Insert a minimal active user."""
    user_id = uuid4()

    connection.execute(
        """
        INSERT INTO users (
            id,
            email,
            status,
            timezone,
            default_currency,
            created_at,
            updated_at
        )
        VALUES (%s, %s, 'active', 'UTC', 'INR', now(), now())
        """,
        (user_id, email),
    )

    return user_id


def insert_challenge(
    connection: psycopg.Connection,
    *,
    user_id: UUID,
    purpose: str,
    token_hash: str,
) -> UUID:
    """Insert one active authentication challenge."""
    challenge_id = uuid4()

    connection.execute(
        """
        INSERT INTO authentication_challenges (
            id,
            user_id,
            purpose,
            token_hash,
            expires_at,
            created_at,
            updated_at
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            now() + interval '30 minutes',
            now(),
            now()
        )
        """,
        (challenge_id, user_id, purpose, token_hash),
    )

    return challenge_id


def test_credentials_require_argon2id_and_one_record_per_user() -> None:
    """Reject non-Argon2id hashes and duplicate user credentials."""
    with connect_to_postgresql() as connection:
        user_id = insert_user(
            connection,
            email=f"credential-{uuid4().hex}@falcon.test",
        )
        invalid_user_id = insert_user(
            connection,
            email=f"invalid-credential-{uuid4().hex}@falcon.test",
        )

        connection.execute(
            """
            INSERT INTO user_credentials (
                id,
                user_id,
                password_hash,
                password_changed_at,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, now(), now(), now())
            """,
            (uuid4(), user_id, _VALID_PASSWORD_HASH),
        )
        connection.commit()

        with pytest.raises(UniqueViolation):
            connection.execute(
                """
                INSERT INTO user_credentials (
                    id,
                    user_id,
                    password_hash,
                    password_changed_at,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, now(), now(), now())
                """,
                (uuid4(), user_id, _VALID_PASSWORD_HASH),
            )
            connection.commit()

        connection.rollback()

        with pytest.raises(CheckViolation):
            connection.execute(
                """
                INSERT INTO user_credentials (
                    id,
                    user_id,
                    password_hash,
                    password_changed_at,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, now(), now(), now())
                """,
                (
                    uuid4(),
                    invalid_user_id,
                    "not-an-argon2id-password-hash-value",
                ),
            )
            connection.commit()

        connection.rollback()


def test_refresh_rotation_allows_only_one_unused_token_per_session() -> None:
    """Represent rotation while retaining consumed hashes for replay checks."""
    with connect_to_postgresql() as connection:
        user_id = insert_user(
            connection,
            email=f"refresh-{uuid4().hex}@falcon.test",
        )
        session_id = uuid4()

        connection.execute(
            """
            INSERT INTO refresh_sessions (
                id,
                user_id,
                family_id,
                expires_at,
                created_at,
                updated_at
            )
            VALUES (
                %s,
                %s,
                %s,
                now() + interval '7 days',
                now(),
                now()
            )
            """,
            (session_id, user_id, uuid4()),
        )
        connection.execute(
            """
            INSERT INTO refresh_tokens (
                id,
                session_id,
                token_hash,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, now(), now())
            """,
            (uuid4(), session_id, "a" * 64),
        )
        connection.commit()

        with pytest.raises(UniqueViolation):
            connection.execute(
                """
                INSERT INTO refresh_tokens (
                    id,
                    session_id,
                    token_hash,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, now(), now())
                """,
                (uuid4(), session_id, "b" * 64),
            )
            connection.commit()

        connection.rollback()

        connection.execute(
            """
            UPDATE refresh_tokens
            SET used_at = now(), updated_at = now()
            WHERE session_id = %s
            AND used_at IS NULL
            """,
            (session_id,),
        )
        connection.execute(
            """
            INSERT INTO refresh_tokens (
                id,
                session_id,
                token_hash,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, now(), now())
            """,
            (uuid4(), session_id, "b" * 64),
        )
        connection.commit()

        token_states = connection.execute(
            """
            SELECT
                count(*) FILTER (WHERE used_at IS NOT NULL),
                count(*) FILTER (WHERE used_at IS NULL)
            FROM refresh_tokens
            WHERE session_id = %s
            """,
            (session_id,),
        ).fetchone()

        assert token_states == (1, 1)


def test_challenges_enforce_replacement_and_exclusive_terminal_state() -> None:
    """Require one current challenge and one terminal outcome."""
    with connect_to_postgresql() as connection:
        user_id = insert_user(
            connection,
            email=f"challenge-{uuid4().hex}@falcon.test",
        )
        first_challenge_id = insert_challenge(
            connection,
            user_id=user_id,
            purpose="email_verification",
            token_hash="c" * 64,
        )
        connection.commit()

        with pytest.raises(UniqueViolation):
            insert_challenge(
                connection,
                user_id=user_id,
                purpose="email_verification",
                token_hash="d" * 64,
            )
            connection.commit()

        connection.rollback()

        connection.execute(
            """
            UPDATE authentication_challenges
            SET invalidated_at = now(), updated_at = now()
            WHERE id = %s
            """,
            (first_challenge_id,),
        )
        second_challenge_id = insert_challenge(
            connection,
            user_id=user_id,
            purpose="email_verification",
            token_hash="d" * 64,
        )
        connection.commit()

        with pytest.raises(CheckViolation):
            connection.execute(
                """
                UPDATE authentication_challenges
                SET
                    consumed_at = now(),
                    invalidated_at = now(),
                    updated_at = now()
                WHERE id = %s
                """,
                (second_challenge_id,),
            )
            connection.commit()

        connection.rollback()


def test_delivery_outbox_requires_encrypted_lifecycle_consistency() -> None:
    """Reject impossible delivery states and plaintext token columns."""
    with connect_to_postgresql() as connection:
        user_id = insert_user(
            connection,
            email=f"delivery-{uuid4().hex}@falcon.test",
        )
        challenge_id = insert_challenge(
            connection,
            user_id=user_id,
            purpose="password_reset",
            token_hash="e" * 64,
        )

        connection.execute(
            """
            INSERT INTO authentication_delivery_outbox (
                id,
                user_id,
                challenge_id,
                encrypted_payload,
                encryption_key_id,
                status,
                attempt_count,
                available_at,
                created_at,
                updated_at
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                'test-key-1',
                'pending',
                0,
                now(),
                now(),
                now()
            )
            """,
            (
                uuid4(),
                user_id,
                challenge_id,
                psycopg.Binary(b"encrypted-test-payload"),
            ),
        )
        connection.commit()

        invalid_challenge_id = insert_challenge(
            connection,
            user_id=user_id,
            purpose="email_verification",
            token_hash="f" * 64,
        )

        with pytest.raises(CheckViolation):
            connection.execute(
                """
                INSERT INTO authentication_delivery_outbox (
                    id,
                    user_id,
                    challenge_id,
                    encrypted_payload,
                    encryption_key_id,
                    status,
                    attempt_count,
                    available_at,
                    processed_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    'test-key-1',
                    'sent',
                    1,
                    now(),
                    NULL,
                    now(),
                    now()
                )
                """,
                (
                    uuid4(),
                    user_id,
                    invalid_challenge_id,
                    psycopg.Binary(b"encrypted-test-payload"),
                ),
            )
            connection.commit()

        connection.rollback()

        column_names = {
            row[0]
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                AND table_name = 'authentication_delivery_outbox'
                """
            )
        }

        assert "encrypted_payload" in column_names
        assert "token" not in column_names
        assert "raw_token" not in column_names
        assert "payload" not in column_names


def test_user_deletion_cascades_all_authentication_records() -> None:
    """Delete credentials, sessions, tokens, challenges, and deliveries."""
    with connect_to_postgresql() as connection:
        user_id = insert_user(
            connection,
            email=f"auth-erasure-{uuid4().hex}@falcon.test",
        )
        session_id = uuid4()
        challenge_id = insert_challenge(
            connection,
            user_id=user_id,
            purpose="email_verification",
            token_hash="1" * 64,
        )

        connection.execute(
            """
            INSERT INTO user_credentials (
                id,
                user_id,
                password_hash,
                password_changed_at,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, now(), now(), now())
            """,
            (uuid4(), user_id, _VALID_PASSWORD_HASH),
        )
        connection.execute(
            """
            INSERT INTO refresh_sessions (
                id,
                user_id,
                family_id,
                expires_at,
                created_at,
                updated_at
            )
            VALUES (
                %s,
                %s,
                %s,
                now() + interval '7 days',
                now(),
                now()
            )
            """,
            (session_id, user_id, uuid4()),
        )
        connection.execute(
            """
            INSERT INTO refresh_tokens (
                id,
                session_id,
                token_hash,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, now(), now())
            """,
            (uuid4(), session_id, "2" * 64),
        )
        connection.execute(
            """
            INSERT INTO authentication_delivery_outbox (
                id,
                user_id,
                challenge_id,
                encrypted_payload,
                encryption_key_id,
                status,
                attempt_count,
                available_at,
                created_at,
                updated_at
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                'test-key-1',
                'pending',
                0,
                now(),
                now(),
                now()
            )
            """,
            (
                uuid4(),
                user_id,
                challenge_id,
                psycopg.Binary(b"encrypted-test-payload"),
            ),
        )
        connection.commit()

        connection.execute(
            "DELETE FROM users WHERE id = %s",
            (user_id,),
        )
        connection.commit()

        remaining = connection.execute(
            """
            SELECT
                (
                    SELECT count(*)
                    FROM user_credentials
                    WHERE user_id = %s
                ),
                (
                    SELECT count(*)
                    FROM refresh_sessions
                    WHERE user_id = %s
                ),
                (
                    SELECT count(*)
                    FROM refresh_tokens
                    WHERE session_id = %s
                ),
                (
                    SELECT count(*)
                    FROM authentication_challenges
                    WHERE user_id = %s
                ),
                (
                    SELECT count(*)
                    FROM authentication_delivery_outbox
                    WHERE user_id = %s
                )
            """,
            (user_id, user_id, session_id, user_id, user_id),
        ).fetchone()

        assert remaining == (0, 0, 0, 0, 0)


def test_authentication_performance_indexes_exist() -> None:
    """Verify reviewed partial, cleanup, family, and expiry indexes."""
    expected_indexes = {
        "ix_authentication_challenges_expiry",
        "ix_authentication_delivery_outbox_pending",
        "ix_refresh_sessions_expiry",
        "ix_refresh_sessions_family",
        "ix_refresh_sessions_user_active",
        "uq_authentication_challenges_user_purpose_active",
        "uq_refresh_tokens_session_active",
    }

    with connect_to_postgresql() as connection:
        index_definitions = {
            row[0]: row[1]
            for row in connection.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = current_schema()
                AND tablename IN (
                    'authentication_challenges',
                    'authentication_delivery_outbox',
                    'refresh_sessions',
                    'refresh_tokens'
                )
                """
            )
        }

    assert expected_indexes <= set(index_definitions)

    assert "WHERE (revoked_at IS NULL)" in index_definitions[
        "ix_refresh_sessions_user_active"
    ]
    assert "WHERE (used_at IS NULL)" in index_definitions[
        "uq_refresh_tokens_session_active"
    ]
    assert (
        "consumed_at IS NULL"
        in index_definitions[
            "uq_authentication_challenges_user_purpose_active"
        ]
    )
    assert (
        "invalidated_at IS NULL"
        in index_definitions[
            "uq_authentication_challenges_user_purpose_active"
        ]
    )
    assert (
        "processed_at IS NULL"
        in index_definitions[
            "ix_authentication_delivery_outbox_pending"
        ]
    )
