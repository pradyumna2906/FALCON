"""Async event-loop factories for platform-sensitive infrastructure."""

import asyncio


def create_psycopg_compatible_event_loop() -> asyncio.AbstractEventLoop:
    """Create the selector event loop required by async Psycopg on Windows."""
    return asyncio.SelectorEventLoop()
