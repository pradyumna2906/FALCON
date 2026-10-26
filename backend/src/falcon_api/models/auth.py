"""Authentication credential, session, challenge, and delivery models."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from falcon_api.infrastructure.persistence import (
    Base,
    TimestampMixin,
    UTCDateTime,
    UUIDPrimaryKeyMixin,
    utc_now,
)
from falcon_api.models.enums import (
    AuthenticationChallengePurpose,
    AuthenticationDeliveryStatus,
    enum_sql_values,
)
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from falcon_api.models.user import User


class UserCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Store one encoded password credential for a user."""

    __tablename__ = "user_credentials"
    __table_args__ = (
        CheckConstraint(
            "length(password_hash) BETWEEN 32 AND 512",
            name="password_hash_length",
        ),
        CheckConstraint(
            "password_hash LIKE '$argon2id$%'",
            name="password_hash_argon2id",
        ),
        CheckConstraint(
            "password_changed_at >= created_at",
            name="password_changed_not_before_creation",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_user_credentials_user_id_users",
        ),
        nullable=False,
        unique=True,
    )
    password_hash: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )
    password_changed_at: Mapped[UTCDateTime] = mapped_column(
        default=utc_now,
        nullable=False,
    )

    user: Mapped[User] = relationship(
        back_populates="credential",
    )


class RefreshSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Represent one revocable browser refresh-session family."""

    __tablename__ = "refresh_sessions"
    __table_args__ = (
        CheckConstraint(
            "expires_at > created_at",
            name="expiry_after_creation",
        ),
        CheckConstraint(
            "last_used_at IS NULL OR last_used_at >= created_at",
            name="last_used_not_before_creation",
        ),
        CheckConstraint(
            "last_used_at IS NULL OR last_used_at <= expires_at",
            name="last_used_not_after_expiry",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="revocation_not_before_creation",
        ),
        CheckConstraint(
            (
                "(revoked_at IS NULL AND revocation_reason IS NULL) OR "
                "(revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)"
            ),
            name="revocation_state_consistent",
        ),
        Index(
            "ix_refresh_sessions_user_active",
            "user_id",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index(
            "ix_refresh_sessions_family",
            "family_id",
        ),
        Index(
            "ix_refresh_sessions_expiry",
            "expires_at",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_refresh_sessions_user_id_users",
        ),
        nullable=False,
    )
    family_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )
    last_used_at: Mapped[UTCDateTime | None] = mapped_column(
        nullable=True,
    )
    expires_at: Mapped[UTCDateTime] = mapped_column(
        nullable=False,
    )
    revoked_at: Mapped[UTCDateTime | None] = mapped_column(
        nullable=True,
    )
    revocation_reason: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    user: Mapped[User] = relationship(
        back_populates="refresh_sessions",
    )
    tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Store a hashed refresh token and its rotation-consumption state."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'",
            name="token_hash_sha256_hex",
        ),
        CheckConstraint(
            "used_at IS NULL OR used_at >= created_at",
            name="use_not_before_creation",
        ),
        Index(
            "uq_refresh_tokens_session_active",
            "session_id",
            unique=True,
            postgresql_where=text("used_at IS NULL"),
        ),
    )

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "refresh_sessions.id",
            ondelete="CASCADE",
            name="fk_refresh_tokens_session_id_refresh_sessions",
        ),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    used_at: Mapped[UTCDateTime | None] = mapped_column(
        nullable=True,
    )

    session: Mapped[RefreshSession] = relationship(
        back_populates="tokens",
    )


class AuthenticationChallenge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Store a hashed, expiring, single-use authentication challenge."""

    __tablename__ = "authentication_challenges"
    __table_args__ = (
        CheckConstraint(
            (
                "purpose IN "
                f"({enum_sql_values(AuthenticationChallengePurpose)})"
            ),
            name="purpose_allowed",
        ),
        CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'",
            name="token_hash_sha256_hex",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="expiry_after_creation",
        ),
        CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name="consumption_not_before_creation",
        ),
        CheckConstraint(
            "invalidated_at IS NULL OR invalidated_at >= created_at",
            name="invalidation_not_before_creation",
        ),
        CheckConstraint(
            "consumed_at IS NULL OR invalidated_at IS NULL",
            name="terminal_state_exclusive",
        ),
        Index(
            "uq_authentication_challenges_user_purpose_active",
            "user_id",
            "purpose",
            unique=True,
            postgresql_where=text(
                "consumed_at IS NULL AND invalidated_at IS NULL"
            ),
        ),
        Index(
            "ix_authentication_challenges_expiry",
            "expires_at",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_authentication_challenges_user_id_users",
        ),
        nullable=False,
    )
    purpose: Mapped[AuthenticationChallengePurpose] = mapped_column(
        String(32),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    expires_at: Mapped[UTCDateTime] = mapped_column(
        nullable=False,
    )
    consumed_at: Mapped[UTCDateTime | None] = mapped_column(
        nullable=True,
    )
    invalidated_at: Mapped[UTCDateTime | None] = mapped_column(
        nullable=True,
    )

    user: Mapped[User] = relationship(
        back_populates="authentication_challenges",
    )
    delivery: Mapped[AuthenticationDelivery | None] = relationship(
        back_populates="challenge",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class AuthenticationDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persist encrypted authentication-message delivery work."""

    __tablename__ = "authentication_delivery_outbox"
    __table_args__ = (
        CheckConstraint(
            (
                "status IN "
                f"({enum_sql_values(AuthenticationDeliveryStatus)})"
            ),
            name="status_allowed",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="attempt_count_non_negative",
        ),
        CheckConstraint(
            (
                "(status = 'sent' AND processed_at IS NOT NULL) OR "
                "(status <> 'sent' AND processed_at IS NULL)"
            ),
            name="processing_state_consistent",
        ),
        CheckConstraint(
            "processed_at IS NULL OR processed_at >= created_at",
            name="processed_not_before_creation",
        ),
        Index(
            "ix_authentication_delivery_outbox_pending",
            "available_at",
            "created_at",
            postgresql_where=text(
                "status IN ('pending', 'failed') "
                "AND processed_at IS NULL"
            ),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_authentication_delivery_outbox_user_id_users",
        ),
        nullable=False,
    )
    challenge_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "authentication_challenges.id",
            ondelete="CASCADE",
            name="fk_auth_delivery_outbox_challenge",
        ),
        nullable=False,
        unique=True,
    )
    encrypted_payload: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )
    encryption_key_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    status: Mapped[AuthenticationDeliveryStatus] = mapped_column(
        String(16),
        default=AuthenticationDeliveryStatus.PENDING,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    available_at: Mapped[UTCDateTime] = mapped_column(
        default=utc_now,
        nullable=False,
    )
    processed_at: Mapped[UTCDateTime | None] = mapped_column(
        nullable=True,
    )
    last_error_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    user: Mapped[User] = relationship(
        back_populates="authentication_deliveries",
    )
    challenge: Mapped[AuthenticationChallenge] = relationship(
        back_populates="delivery",
    )
