"""Authenticated assistant API, ownership, and OpenAPI contract tests."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.api.routes.assistant import (
    assistant_history_service_from,
    assistant_orchestrator_from,
)
from falcon_api.api.routes.auth import current_principal_service_from
from falcon_api.assistant import (
    AssistantAnswer,
    AssistantAnswerStatus,
    AssistantConversationSummary,
    AssistantHistoryService,
    AssistantHistoryTurn,
    AssistantIntent,
    AssistantMessageResult,
    AssistantRefusalReason,
    AssistantReliability,
    GroundedAssistantOrchestrator,
)
from falcon_api.auth.principal import AuthenticatedPrincipal, CurrentPrincipalService
from falcon_api.infrastructure.database import get_database_session


NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
TOKEN = "assistant-route-access-token"
IDEMPOTENCY_KEY = "message-key-00000001"


def _answer() -> AssistantAnswer:
    return AssistantAnswer(
        intent=AssistantIntent.EXPLAIN_FORECAST,
        status=AssistantAnswerStatus.UNAVAILABLE,
        answer="I do not have enough verified FALCON evidence to answer that question.",
        evidence_summary=(),
        citations=(),
        reliability=AssistantReliability.UNAVAILABLE,
        refusal_reason=AssistantRefusalReason.INSUFFICIENT_EVIDENCE,
    )


def _turn(*, ordinal: int = 1) -> AssistantHistoryTurn:
    return AssistantHistoryTurn(
        id=uuid4(),
        ordinal=ordinal,
        question="Explain my forecast",
        answer=_answer(),
        created_at=NOW,
    )


@pytest.fixture
def assistant_dependencies(client: TestClient):
    principal = AuthenticatedPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email="assistant-user@example.com",
        display_name="Assistant User",
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=NOW,
    )
    principal_service = Mock(spec=CurrentPrincipalService)
    principal_service.authenticate = AsyncMock(return_value=principal)
    history = AsyncMock(spec=AssistantHistoryService)
    orchestrator = AsyncMock(spec=GroundedAssistantOrchestrator)
    session = AsyncMock(spec=AsyncSession)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    client.app.dependency_overrides[get_database_session] = session_override
    client.app.dependency_overrides[current_principal_service_from] = lambda: (
        principal_service
    )
    client.app.dependency_overrides[assistant_history_service_from] = lambda: history
    client.app.dependency_overrides[assistant_orchestrator_from] = lambda: orchestrator
    try:
        yield history, orchestrator, session, principal
    finally:
        client.app.dependency_overrides.clear()


def test_conversation_lifecycle_is_owner_scoped_and_bounded(
    client: TestClient,
    assistant_dependencies,
) -> None:
    history, _, session, principal = assistant_dependencies
    conversation_id = uuid4()
    summary = AssistantConversationSummary(
        id=conversation_id,
        created_at=NOW,
        expires_at=NOW + timedelta(days=90),
        turn_count=1,
    )
    history.create.return_value = SimpleNamespace(
        id=conversation_id,
        created_at=summary.created_at,
        expires_at=summary.expires_at,
    )
    history.list_recent.return_value = (summary,)
    history.get.return_value = summary
    history.recent_turns.return_value = (_turn(),)
    history.delete.return_value = True
    headers = {"Authorization": f"Bearer {TOKEN}"}

    created = client.post("/api/v1/assistant/conversations", headers=headers)
    listed = client.get(
        "/api/v1/assistant/conversations?limit=5",
        headers=headers,
    )
    detail = client.get(
        f"/api/v1/assistant/conversations/{conversation_id}?limit=10",
        headers=headers,
    )
    deleted = client.delete(
        f"/api/v1/assistant/conversations/{conversation_id}",
        headers=headers,
    )

    assert created.status_code == 201 and created.json()["turn_count"] == 0
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == str(conversation_id)
    assert detail.status_code == 200
    assert detail.json()["messages"][0]["question"] == "Explain my forecast"
    assert detail.json()["has_more"] is False
    assert deleted.status_code == 204 and not deleted.content
    history.create.assert_awaited_once_with(session, user_id=principal.user_id)
    assert history.list_recent.await_args.kwargs == {
        "user_id": principal.user_id,
        "limit": 5,
    }
    assert history.recent_turns.await_args.kwargs["limit"] == 10
    assert history.delete.await_args.kwargs["user_id"] == principal.user_id


def test_message_creation_forwards_only_trusted_context_and_replays_with_200(
    client: TestClient,
    assistant_dependencies,
) -> None:
    _, orchestrator, session, principal = assistant_dependencies
    conversation_id = uuid4()
    turn = _turn()
    orchestrator.send_message.side_effect = (
        AssistantMessageResult(turn, False),
        AssistantMessageResult(turn, True),
    )
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Idempotency-Key": IDEMPOTENCY_KEY,
    }
    path = f"/api/v1/assistant/conversations/{conversation_id}/messages"

    created = client.post(
        path,
        headers=headers,
        json={"question": "Explain my forecast"},
    )
    replayed = client.post(
        path,
        headers=headers,
        json={"question": "Explain my forecast"},
    )

    assert created.status_code == 201 and created.json()["replayed"] is False
    assert replayed.status_code == 200 and replayed.json()["replayed"] is True
    first = orchestrator.send_message.await_args_list[0]
    assert first.args == (session,)
    assert first.kwargs == {
        "user_id": principal.user_id,
        "conversation_id": conversation_id,
        "question": "Explain my forecast",
        "idempotency_key": IDEMPOTENCY_KEY,
        "trusted_timezone": principal.timezone,
        "default_currency": principal.default_currency,
    }

    missing_key = client.post(
        path,
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"question": "Explain my forecast"},
    )
    injected = client.post(
        path,
        headers=headers,
        json={
            "question": "Explain my forecast",
            "user_id": str(uuid4()),
            "intent": "compare_scenarios",
        },
    )
    assert missing_key.status_code == 422
    assert injected.status_code == 422


def test_citations_and_missing_resources_use_owner_safe_404(
    client: TestClient,
    assistant_dependencies,
) -> None:
    history, _, _, principal = assistant_dependencies
    conversation_id, message_id = uuid4(), uuid4()
    turn = _turn()
    history.get_turn.return_value = turn
    headers = {"Authorization": f"Bearer {TOKEN}"}
    path = (
        f"/api/v1/assistant/conversations/{conversation_id}"
        f"/messages/{message_id}/citations"
    )

    response = client.get(path, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"message_id": str(turn.id), "items": []}
    assert history.get_turn.await_args.kwargs["user_id"] == principal.user_id
    history.get_turn.return_value = None
    missing = client.get(path, headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "assistant_resource_not_found"

    history.get.return_value = None
    detail = client.get(
        f"/api/v1/assistant/conversations/{conversation_id}",
        headers=headers,
    )
    history.delete.return_value = False
    deletion = client.delete(
        f"/api/v1/assistant/conversations/{conversation_id}",
        headers=headers,
    )
    assert detail.status_code == deletion.status_code == 404


def test_openapi_freezes_authenticated_non_streaming_assistant_contract(
    client: TestClient,
) -> None:
    document = client.get("/openapi.json").json()
    paths = document["paths"]
    root = paths["/api/v1/assistant/conversations"]
    detail = paths["/api/v1/assistant/conversations/{conversation_id}"]
    message = paths[
        "/api/v1/assistant/conversations/{conversation_id}/messages"
    ]["post"]
    citation = paths[
        "/api/v1/assistant/conversations/{conversation_id}/messages/"
        "{message_id}/citations"
    ]["get"]

    assert set(root) == {"get", "post"}
    assert set(detail) == {"get", "delete"}
    for operation in (*root.values(), *detail.values(), message, citation):
        assert operation["security"] == [{"HTTPBearer": []}]
    idempotency = next(
        item for item in message["parameters"] if item["name"] == "Idempotency-Key"
    )
    assert idempotency["required"] is True and idempotency["in"] == "header"
    request = document["components"]["schemas"]["AssistantQuestionRequest"]
    assert set(request["properties"]) == {"question"}
    serialized = str(document).casefold()
    assert "text/event-stream" not in serialized
    assert "chain_of_thought" not in serialized
