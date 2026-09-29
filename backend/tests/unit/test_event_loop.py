"""Async event-loop compatibility tests."""

import asyncio

from falcon_api.core.event_loop import create_psycopg_compatible_event_loop


def test_psycopg_event_loop_factory_returns_selector_loop() -> None:
    loop = create_psycopg_compatible_event_loop()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()
