"""Real Redis admission and PostgreSQL durable delivery/retention checks."""

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import psycopg
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from falcon_api.auth.delivery import EncryptedDeliveryPayload
from falcon_api.core.config import Settings
from falcon_api.core.errors import ApplicationError
from falcon_api.core.event_loop import create_psycopg_compatible_event_loop
from falcon_api.infrastructure.distributed_limits import RedisRequestLimiter
from falcon_api.infrastructure.persistence import transaction_scope, utc_now
from falcon_api.main import create_app
from falcon_api.models.auth import AuthenticationDelivery
from falcon_api.worker import deliver_one, retention

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not os.getenv("FALCON_TEST_REDIS_URL"), reason="Explicit Redis test URL required")
def test_two_replicas_share_atomic_rate_and_concurrency_leases():
    async def run():
        first = Redis.from_url(os.environ["FALCON_TEST_REDIS_URL"])
        second = Redis.from_url(os.environ["FALCON_TEST_REDIS_URL"])
        owner = uuid4()
        namespace = "integration-" + uuid4().hex
        a = RedisRequestLimiter(first, namespace=namespace, requests_per_minute=2, max_concurrent_requests=1)
        b = RedisRequestLimiter(second, namespace=namespace, requests_per_minute=2, max_concurrent_requests=1)
        try:
            async with a.permit(owner):
                with pytest.raises(ApplicationError, match="Request limit"):
                    async with b.permit(owner):
                        pytest.fail("Concurrent replica entered")
            async with b.permit(owner):
                pass
            with pytest.raises(ApplicationError, match="Request limit"):
                async with a.permit(owner):
                    pytest.fail("Rate limit bypassed")
            async with a.permit(uuid4()):
                pass
            keys = [key async for key in first.scan_iter(match=f"falcon:{namespace}:*")]
            assert keys and all([await first.pttl(key) > 0 for key in keys])
            await first.delete(*keys)
        finally:
            await first.aclose()
            await second.aclose()
    asyncio.run(run())


@pytest.mark.skipif(os.getenv("FALCON_RUN_DATABASE_INTEGRATION") != "1", reason="Explicit PostgreSQL required")
def test_outbox_retry_commit_delivery_and_verification():
    root = Path(__file__).resolve().parents[3]
    command.upgrade(Config(str(root / "backend/alembic.ini")), "head")
    settings = Settings(_env_file=None, env="test")
    user_id = None
    try:
        with TestClient(create_app(settings), base_url="https://testserver",
                        backend_options={"loop_factory": create_psycopg_compatible_event_loop}) as client:
            registered = client.post("/api/v1/auth/register", json={
                "email": f"worker-{uuid4().hex}@example.com", "password": "Synthetic-Worker-Password-2026!",
                "timezone": "UTC", "default_currency": "INR"})
            assert registered.status_code == 201, registered.text
            user_id = registered.json()["id"]
            sender = SimpleNamespace(send=AsyncMock(side_effect=RuntimeError("synthetic failure")))

            async def cycle():
                async with transaction_scope(client.app.state.database.session_factory) as session:
                    return await deliver_one(session, sender)

            assert client.portal.call(cycle)

            async def inspect_retry():
                async with transaction_scope(client.app.state.database.session_factory) as session:
                    row = await session.scalar(select(AuthenticationDelivery).where(AuthenticationDelivery.user_id == user_id))
                    assert row.status == "failed" and row.attempt_count == 1
                    assert row.last_error_code == "delivery_retry" and row.available_at > utc_now()
                    row.available_at = utc_now()
                    return client.app.state.authentication_cryptography.deliveries.decrypt_email_verification(
                        EncryptedDeliveryPayload(row.encrypted_payload, row.encryption_key_id)).token

            token = client.portal.call(inspect_retry)
            sender.send.side_effect = None
            assert client.portal.call(cycle)
            assert not client.portal.call(cycle)

            async def inspect_success():
                async with transaction_scope(client.app.state.database.session_factory) as session:
                    row = await session.scalar(select(AuthenticationDelivery).where(AuthenticationDelivery.user_id == user_id))
                    assert row.status == "sent" and row.attempt_count == 2 and row.encrypted_payload == b""
                    await retention(session, client.app.state.assistant_history_service)

            client.portal.call(inspect_success)
            assert client.post("/api/v1/auth/email-verification/confirm", json={"token": token}).status_code == 204
    finally:
        if user_id:
            with psycopg.connect(settings.database_url.render_as_string(hide_password=False).replace("postgresql+psycopg://", "postgresql://")) as connection:
                connection.execute("DELETE FROM users WHERE id = %s", (user_id,))
