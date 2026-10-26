"""Provider/worker failures never escape as secrets or partial records."""

import asyncio
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from cryptography.fernet import Fernet
import pytest

from falcon_api.assistant.model import AssistantModelRequest, AssistantModelUnavailableError, AssistantModelBudgetError
from falcon_api.assistant.openai_transport import OpenAIResponsesTransport, NoRedirect, configured_assistant_model
from falcon_api.auth.delivery import AuthenticationDeliveryCipher
from falcon_api.core.config import Settings
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.distributed_limits import RedisRequestLimiter
from falcon_api.infrastructure.persistence import utc_now
from falcon_api.worker import SMTPDelivery, process_delivery, MAX_ATTEMPTS


def request():
    return AssistantModelRequest("a" * 64, "approved-model", {"evidence": []},
                                 {"type": "object"}, Decimal(0), 1500, 1_000_000)


def response():
    return {"status": "completed", "output": [{"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": '{"claims": []}'}]}],
            "usage": {"input_tokens": 10, "output_tokens": 20}}


def transport(payload=None, *, failure=None):
    opener = Mock()
    if failure:
        opener.open.side_effect = failure
    else:
        opener.open.return_value = BytesIO(json.dumps(payload or response()).encode())
    return OpenAIResponsesTransport(api_key="secret-provider-key", input_price=Decimal("0.5"),
                                   output_price=Decimal("2"), opener=opener), opener


def test_openai_closed_request_and_measured_cost():
    model, opener = transport()
    result = asyncio.run(model.complete(request()))
    assert result.usage.cost_micro_units == 45
    outbound = opener.open.call_args.args[0]
    body = json.loads(outbound.data)
    assert body["store"] is False and body["stream"] is False
    assert "tools" not in body and "previous_response_id" not in body
    assert body["text"]["format"]["strict"] is True
    assert outbound.full_url == "https://api.openai.com/v1/responses"
    assert NoRedirect().redirect_request(None, None, 302, None, None, "https://evil.test") is None


@pytest.mark.parametrize("change", [
    {"status": "incomplete"}, {"output": []}, {"output": [{"type": "function_call"}]},
    {"output": [{"type": "message", "role": "assistant", "content": [{"type": "refusal"}]}]},
    {"usage": {"input_tokens": True, "output_tokens": 20}},
    {"usage": {"input_tokens": -1, "output_tokens": 20}},
])
def test_rejects_incomplete_refused_or_invalid_provider_output(change):
    payload = response() | change
    model, _ = transport(payload)
    with pytest.raises(AssistantModelUnavailableError, match="provider is unavailable"):
        asyncio.run(model.complete(request()))


def test_provider_exception_redacted_and_never_retried():
    model, opener = transport(failure=RuntimeError("secret-provider-key private prompt"))
    with pytest.raises(AssistantModelUnavailableError) as error:
        asyncio.run(model.complete(request()))
    assert "secret" not in str(error.value)
    assert opener.open.call_count == 1
    model._input_price = Decimal(1000)
    with pytest.raises(AssistantModelBudgetError):
        asyncio.run(model.complete(request()))
    assert opener.open.call_count == 1


def test_provider_configuration_requires_key_model_and_prices():
    with pytest.raises(ValueError, match="approved model"):
        Settings(_env_file=None, assistant_provider="openai")
    settings = Settings(_env_file=None, assistant_provider="openai", openai_api_key="synthetic",
                        openai_model="approved-model", openai_input_usd_per_million=1,
                        openai_output_usd_per_million=2)
    assert configured_assistant_model(settings) is not None
    assert configured_assistant_model(Settings(_env_file=None)) is not None
    for origin in ("http://example.com", "https://example.com/evil", "https://name:pass@example.com"):
        with pytest.raises(ValueError):
            Settings(_env_file=None, smtp_host="smtp.example.com", smtp_sender="falcon@example.com", public_origin=origin)
    with pytest.raises(ValueError):
        Settings(_env_file=None, redis_url="http://example.com")


@pytest.mark.parametrize("code,status", [(1, 429), (2, 429), (None, 503)])
def test_redis_failures_do_not_enter_operation(code, status):
    async def run():
        client = SimpleNamespace(eval=AsyncMock(return_value=code), zrem=AsyncMock())
        if code is None:
            client.eval.side_effect = RuntimeError("secret redis password")
        limiter = RedisRequestLimiter(client, namespace="test", requests_per_minute=2, max_concurrent_requests=1)
        with pytest.raises(ApplicationError) as error:
            async with limiter.permit(uuid4()):
                pytest.fail("Unadmitted request entered")
        assert error.value.status_code == status and "secret" not in str(error.value)
        client.zrem.assert_not_awaited()
    asyncio.run(run())


def test_redis_owner_hashed_and_lease_released_on_error():
    async def run():
        client = SimpleNamespace(eval=AsyncMock(return_value=0), zrem=AsyncMock())
        limiter = RedisRequestLimiter(client, namespace="test", requests_per_minute=2, max_concurrent_requests=1)
        owner = uuid4()
        with pytest.raises(ValueError):
            async with limiter.permit(owner):
                raise ValueError("application error")
        assert str(owner) not in client.eval.call_args.args[2]
        client.zrem.assert_awaited_once()
        client.zrem.side_effect = ConnectionError()
        async with limiter.permit(owner):
            pass
    asyncio.run(run())


def delivery_objects():
    now = utc_now()
    return now, SimpleNamespace(id=uuid4(), encrypted_payload=b"private", attempt_count=0,
                               status="pending", processed_at=None, last_error_code=None), SimpleNamespace(
        expires_at=now + timedelta(minutes=5), consumed_at=None, invalidated_at=None,
        purpose="email_verification")


def test_delivery_retries_dead_letters_and_scrubs_success():
    now, row, challenge = delivery_objects()
    sender = SimpleNamespace(send=AsyncMock(side_effect=RuntimeError("secret token")))
    for attempt in range(MAX_ATTEMPTS):
        asyncio.run(process_delivery(row, challenge, sender, now=now))
        assert row.attempt_count == attempt + 1
        assert row.processed_at is None and row.status == "failed"
        assert row.available_at > now
        assert "secret" not in row.last_error_code
    assert row.last_error_code == "delivery_exhausted"
    row.attempt_count = 0
    sender.send.side_effect = None
    asyncio.run(process_delivery(row, challenge, sender, now=now))
    assert row.status == "sent" and row.processed_at is not None
    assert row.encrypted_payload == b""


@pytest.mark.parametrize("obsolete", ["expires_at", "consumed_at", "invalidated_at"])
def test_obsolete_challenge_never_sent(obsolete):
    now, row, challenge = delivery_objects()
    setattr(challenge, obsolete, now)
    sender = SimpleNamespace(send=AsyncMock())
    asyncio.run(process_delivery(row, challenge, sender, now=now))
    sender.send.assert_not_awaited()
    assert row.attempt_count == MAX_ATTEMPTS and row.encrypted_payload == b""


def test_smtp_previous_key_rotation_and_token_not_in_url():
    old_key = Fernet.generate_key().decode()
    settings = Settings(_env_file=None, smtp_host="smtp.example.com", smtp_sender="falcon@example.com",
                        public_origin="https://falcon.example.com", delivery_previous_keys={"old": old_key})
    cipher = AuthenticationDeliveryCipher(encryption_key=old_key, key_id="old")
    now, row, challenge = delivery_objects()
    payload = cipher.encrypt_email_verification(email="synthetic@example.com", token="synthetic-token")
    row.encrypted_payload, row.encryption_key_id = payload.ciphertext, "old"
    message = SMTPDelivery(settings).message(row, challenge)
    assert "https://falcon.example.com/verify-email\n" in message.get_content()
    assert "synthetic-token" in message.get_content()
    assert "synthetic-token" not in str(message["Message-ID"])
    challenge.purpose = "password_reset"
    row.encrypted_payload = cipher.encrypt_password_reset(email="synthetic@example.com", token="reset-token").ciphertext
    assert "reset-password" in SMTPDelivery(settings).message(row, challenge).get_content()
    challenge.purpose = "unsupported"
    with pytest.raises(ValueError):
        SMTPDelivery(settings).message(row, challenge)


@pytest.mark.parametrize("mode", ["ssl", "starttls"])
def test_smtp_uses_verified_tls_before_login(mode, monkeypatch):
    settings = Settings(_env_file=None, smtp_host="smtp.example.com", smtp_sender="falcon@example.com",
                        smtp_mode=mode, smtp_username="synthetic", smtp_password="secret")
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.send_message.return_value = {}
    factory = Mock(return_value=client)
    monkeypatch.setattr("falcon_api.worker.smtplib.SMTP_SSL" if mode == "ssl" else "falcon_api.worker.smtplib.SMTP", factory)
    sender = SMTPDelivery(settings)
    sender._send(Mock())
    client.login.assert_called_once_with("synthetic", "secret")
    if mode == "starttls":
        assert [call[0] for call in client.method_calls].index("starttls") < [call[0] for call in client.method_calls].index("login")
    else:
        assert factory.call_args.kwargs["context"].check_hostname
