"""Consume real verification challenges for synthetic integration users only."""

from uuid import UUID

from falcon_api.auth.delivery import EncryptedDeliveryPayload
from falcon_api.infrastructure.persistence import transaction_scope
from falcon_api.models.auth import AuthenticationChallenge, AuthenticationDelivery
from falcon_api.models.enums import AuthenticationChallengePurpose
from sqlalchemy import select


def verify_registered_user(client, user_id: UUID) -> None:
    """Read the test outbox on the app loop, then use the real public endpoint."""

    async def read_token():
        async with transaction_scope(
            client.app.state.database.session_factory
        ) as session:
            delivery = await session.scalar(
                select(AuthenticationDelivery)
                .join(
                    AuthenticationChallenge,
                    AuthenticationDelivery.challenge_id == AuthenticationChallenge.id,
                )
                .where(
                    AuthenticationChallenge.user_id == user_id,
                    AuthenticationChallenge.purpose
                    == AuthenticationChallengePurpose.EMAIL_VERIFICATION,
                    AuthenticationChallenge.consumed_at.is_(None),
                    AuthenticationChallenge.invalidated_at.is_(None),
                )
            )
            assert delivery is not None
            return client.app.state.authentication_cryptography.deliveries.decrypt_email_verification(
                EncryptedDeliveryPayload(
                    ciphertext=delivery.encrypted_payload,
                    key_id=delivery.encryption_key_id,
                )
            ).token

    assert client.portal is not None
    token = client.portal.call(read_token)
    response = client.post(
        "/api/v1/auth/email-verification/confirm", json={"token": token}
    )
    assert response.status_code == 204, response.text
