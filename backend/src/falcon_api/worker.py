"""Durable authentication delivery and bounded retention scheduler.

Run with python -m falcon_api.worker. Delivery is at least once: a crash after
SMTP acceptance and before commit may resend the same stable Message-ID.
"""

import asyncio
from datetime import timedelta
from email.message import EmailMessage
import logging
from pathlib import Path
import signal
import smtplib
import ssl

from sqlalchemy import delete, select

from falcon_api.assistant.history import AssistantHistoryService
from falcon_api.auth.delivery import AuthenticationDeliveryCipher, EncryptedDeliveryPayload
from falcon_api.core.config import Settings, get_settings
from falcon_api.core.event_loop import create_psycopg_compatible_event_loop
from falcon_api.core.logging import configure_logging
from falcon_api.infrastructure.database import create_database_resources
from falcon_api.infrastructure.persistence import transaction_scope, utc_now
from falcon_api.models.auth import AuthenticationChallenge, AuthenticationDelivery


logger = logging.getLogger("falcon_api.worker")
MAX_ATTEMPTS = 5


class SMTPDelivery:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.ciphers = {
            name: AuthenticationDeliveryCipher(encryption_key=key.get_secret_value(), key_id=name)
            for name, key in settings.delivery_previous_keys.items()
        }
        self.ciphers[settings.auth_delivery_encryption_key_id] = AuthenticationDeliveryCipher(
            encryption_key=settings.auth_delivery_encryption_key.get_secret_value(),
            key_id=settings.auth_delivery_encryption_key_id,
        )

    def message(self, delivery, challenge) -> EmailMessage:
        cipher = self.ciphers[delivery.encryption_key_id]
        payload = EncryptedDeliveryPayload(delivery.encrypted_payload, delivery.encryption_key_id)
        if challenge.purpose == "email_verification":
            content = cipher.decrypt_email_verification(payload)
            title, route = "Verify your FALCON email", "verify-email"
        elif challenge.purpose == "password_reset":
            content = cipher.decrypt_password_reset(payload)
            title, route = "Reset your FALCON password", "reset-password"
        else:
            raise ValueError("Unsupported delivery purpose")
        message = EmailMessage()
        message["From"] = self.settings.smtp_sender
        message["To"] = content.email
        message["Subject"] = title
        message["Message-ID"] = f"<{delivery.id}@falcon.invalid>"
        # A pasted token avoids putting credentials into URL logs or referrers.
        message.set_content(f"{title}\n\nOpen {self.settings.public_origin.rstrip('/')}/{route}\n"
                            f"and paste this token:\n\n{content.token}\n\n"
                            "If you did not request this message, ignore it. Never share this token.")
        return message

    async def send(self, delivery, challenge):
        message = self.message(delivery, challenge)
        await asyncio.to_thread(self._send, message)

    def _send(self, message):
        settings = self.settings
        context = ssl.create_default_context()
        if settings.smtp_mode == "ssl":
            client = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10, context=context)
        else:
            client = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
        with client:
            if settings.smtp_mode == "starttls":
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
            if settings.smtp_username.get_secret_value():
                client.login(settings.smtp_username.get_secret_value(), settings.smtp_password.get_secret_value())
            if client.send_message(message):
                raise RuntimeError("Recipient refused")


async def process_delivery(delivery, challenge, sender, *, now):
    if challenge.expires_at <= now or challenge.consumed_at or challenge.invalidated_at:
        delivery.status = "failed"
        delivery.attempt_count = MAX_ATTEMPTS
        delivery.last_error_code = "challenge_obsolete"
        delivery.encrypted_payload = b""
        return
    delivery.attempt_count += 1
    try:
        await sender.send(delivery, challenge)
    except Exception:
        delivery.status = "failed"
        delivery.last_error_code = "delivery_exhausted" if delivery.attempt_count >= MAX_ATTEMPTS else "delivery_retry"
        delivery.available_at = now + timedelta(seconds=min(900, 30 * 2 ** delivery.attempt_count))
        logger.warning("authentication_delivery_failed", extra={"attempt": delivery.attempt_count})
    else:
        delivery.status = "sent"
        delivery.processed_at = utc_now()
        delivery.last_error_code = None
        delivery.encrypted_payload = b""


async def deliver_one(session, sender) -> bool:
    now = utc_now()
    pair = (await session.execute(
        select(AuthenticationDelivery, AuthenticationChallenge)
        .join(AuthenticationChallenge, AuthenticationDelivery.challenge_id == AuthenticationChallenge.id)
        .where(AuthenticationDelivery.status.in_(("pending", "failed")),
               AuthenticationDelivery.attempt_count < MAX_ATTEMPTS,
               AuthenticationDelivery.available_at <= now)
        .order_by(AuthenticationDelivery.available_at, AuthenticationDelivery.id)
        .limit(1).with_for_update(skip_locked=True)
    )).first()
    if pair is None:
        return False
    await process_delivery(*pair, sender, now=now)
    return True


async def retention(session, history):
    await history.purge_expired(session, limit=100)
    # Seven days of delivery outcome metadata, then cascade payload deletion.
    expired = select(AuthenticationChallenge.id).where(
        AuthenticationChallenge.expires_at < utc_now() - timedelta(days=7)
    ).order_by(AuthenticationChallenge.expires_at).limit(100)
    await session.execute(delete(AuthenticationChallenge).where(AuthenticationChallenge.id.in_(expired)))


async def run_worker(settings=None, *, stop=None):
    settings = settings or get_settings()
    if not settings.smtp_host:
        raise ValueError("Configure SMTP before starting the delivery worker.")
    database = create_database_resources(settings)
    sender = SMTPDelivery(settings)
    history = AssistantHistoryService(encryption_keys=tuple(
        key.get_secret_value().encode("ascii") for key in settings.assistant_history_encryption_keys))
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        while not stop.is_set():
            try:
                for _ in range(20):
                    async with transaction_scope(database.session_factory) as session:
                        worked = await deliver_one(session, sender)
                    if not worked or stop.is_set():
                        break
                async with transaction_scope(database.session_factory) as session:
                    await retention(session, history)
                Path("/tmp/falcon-worker.ready").touch()
                logger.info("worker_cycle_completed")
            except Exception:
                logger.error("worker_cycle_failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                pass
    finally:
        await database.dispose()


if __name__ == "__main__":
    configure_logging()
    with asyncio.Runner(loop_factory=create_psycopg_compatible_event_loop) as runner:
        runner.run(run_worker())
