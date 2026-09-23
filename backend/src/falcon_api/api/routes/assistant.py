"""Authenticated owner-scoped grounded assistant conversation routes."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    Query,
    Request,
    Response,
    status,
)

from falcon_api.api.routes.auth import CurrentPrincipalDependency, DatabaseSession
from falcon_api.assistant.history import (
    MAX_CONVERSATION_PAGE,
    MAX_HISTORY_PAGE,
    AssistantHistoryService,
    AssistantHistoryTurn,
)
from falcon_api.assistant.orchestration import GroundedAssistantOrchestrator
from falcon_api.core.errors import ApplicationError
from falcon_api.schemas.assistant import (
    AssistantAnswerResponse,
    AssistantCitationListResponse,
    AssistantCitationResponse,
    AssistantConversationDetailResponse,
    AssistantConversationListResponse,
    AssistantConversationResponse,
    AssistantMessageResponse,
    AssistantQuestionRequest,
)
from falcon_api.schemas.errors import ErrorResponse


assistant_router = APIRouter(
    prefix="/assistant/conversations",
    tags=["assistant"],
)


def assistant_history_service_from(request: Request) -> AssistantHistoryService:
    return cast(
        AssistantHistoryService,
        request.app.state.assistant_history_service,
    )


def assistant_orchestrator_from(
    request: Request,
) -> GroundedAssistantOrchestrator:
    return cast(
        GroundedAssistantOrchestrator,
        request.app.state.assistant_orchestrator,
    )


AssistantHistoryDependency = Annotated[
    AssistantHistoryService,
    Depends(assistant_history_service_from),
]
AssistantOrchestratorDependency = Annotated[
    GroundedAssistantOrchestrator,
    Depends(assistant_orchestrator_from),
]
AssistantQuestionBody = Annotated[AssistantQuestionRequest, Body()]
ConversationLimit = Annotated[
    int,
    Query(ge=1, le=MAX_CONVERSATION_PAGE),
]
HistoryLimit = Annotated[int, Query(ge=1, le=MAX_HISTORY_PAGE)]
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=16,
        max_length=128,
        pattern=r"^[A-Za-z0-9._~:+/-]+$",
    ),
]

_AUTHENTICATION_ERROR = {
    "model": ErrorResponse,
    "description": "The access token is missing, invalid, or expired.",
}
_NOT_FOUND_ERROR = {
    "model": ErrorResponse,
    "description": "The owner-scoped assistant resource was not found.",
}
_CONFLICT_ERROR = {
    "model": ErrorResponse,
    "description": "The conversation is full or the idempotency key conflicts.",
}
_VALIDATION_ERROR = {
    "model": ErrorResponse,
    "description": "The assistant request failed bounded input validation.",
}
_CAPACITY_ERROR = {
    "model": ErrorResponse,
    "description": "The process-local assistant request limit was reached.",
}
_UNAVAILABLE_ERROR = {
    "model": ErrorResponse,
    "description": "Generation timed out, is disabled, or failed verification.",
}


@assistant_router.post(
    "",
    response_model=AssistantConversationResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_assistant_conversation",
    summary="Create an encrypted owner-scoped assistant conversation",
    responses={status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR},
)
async def create_assistant_conversation(
    session: DatabaseSession,
    history: AssistantHistoryDependency,
    principal: CurrentPrincipalDependency,
) -> AssistantConversationResponse:
    conversation = await history.create(session, user_id=principal.user_id)
    return AssistantConversationResponse(
        id=conversation.id,
        created_at=conversation.created_at,
        expires_at=conversation.expires_at,
        turn_count=0,
    )


@assistant_router.get(
    "",
    response_model=AssistantConversationListResponse,
    operation_id="list_assistant_conversations",
    summary="List recent live owner-scoped assistant conversations",
    responses={status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR},
)
async def list_assistant_conversations(
    session: DatabaseSession,
    history: AssistantHistoryDependency,
    principal: CurrentPrincipalDependency,
    limit: ConversationLimit = MAX_CONVERSATION_PAGE,
) -> AssistantConversationListResponse:
    conversations = await history.list_recent(
        session,
        user_id=principal.user_id,
        limit=limit,
    )
    return AssistantConversationListResponse(
        items=tuple(
            AssistantConversationResponse.model_validate(item)
            for item in conversations
        )
    )


@assistant_router.get(
    "/{conversation_id}",
    response_model=AssistantConversationDetailResponse,
    operation_id="get_assistant_conversation",
    summary="Get bounded decrypted history for one owner conversation",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
    },
)
async def get_assistant_conversation(
    conversation_id: UUID,
    session: DatabaseSession,
    history: AssistantHistoryDependency,
    principal: CurrentPrincipalDependency,
    limit: HistoryLimit = MAX_HISTORY_PAGE,
) -> AssistantConversationDetailResponse:
    conversation = await history.get(
        session,
        user_id=principal.user_id,
        conversation_id=conversation_id,
    )
    if conversation is None:
        raise _not_found()
    turns = await history.recent_turns(
        session,
        user_id=principal.user_id,
        conversation_id=conversation_id,
        limit=limit,
    )
    return AssistantConversationDetailResponse(
        **AssistantConversationResponse.model_validate(conversation).model_dump(),
        messages=tuple(
            _message_response(
                conversation_id=conversation_id,
                turn=turn,
                replayed=False,
            )
            for turn in turns
        ),
        has_more=conversation.turn_count > len(turns),
    )


@assistant_router.post(
    "/{conversation_id}/messages",
    response_model=AssistantMessageResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_assistant_message",
    summary="Generate, verify, and atomically persist one grounded answer",
    responses={
        status.HTTP_200_OK: {
            "model": AssistantMessageResponse,
            "description": "An identical idempotent message was replayed.",
        },
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_409_CONFLICT: _CONFLICT_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
        status.HTTP_429_TOO_MANY_REQUESTS: _CAPACITY_ERROR,
        status.HTTP_503_SERVICE_UNAVAILABLE: _UNAVAILABLE_ERROR,
    },
)
async def create_assistant_message(
    conversation_id: UUID,
    payload: AssistantQuestionBody,
    response: Response,
    session: DatabaseSession,
    orchestrator: AssistantOrchestratorDependency,
    principal: CurrentPrincipalDependency,
    idempotency_key: IdempotencyKey,
) -> AssistantMessageResponse:
    result = await orchestrator.send_message(
        session,
        user_id=principal.user_id,
        conversation_id=conversation_id,
        question=payload.question,
        idempotency_key=idempotency_key,
        trusted_timezone=principal.timezone,
        default_currency=principal.default_currency,
    )
    if result.replayed:
        response.status_code = status.HTTP_200_OK
    return _message_response(
        conversation_id=conversation_id,
        turn=result.turn,
        replayed=result.replayed,
    )


@assistant_router.get(
    "/{conversation_id}/messages/{message_id}/citations",
    response_model=AssistantCitationListResponse,
    operation_id="get_assistant_message_citations",
    summary="Get verified citations for one owner-scoped assistant message",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
    },
)
async def get_assistant_message_citations(
    conversation_id: UUID,
    message_id: UUID,
    session: DatabaseSession,
    history: AssistantHistoryDependency,
    principal: CurrentPrincipalDependency,
) -> AssistantCitationListResponse:
    turn = await history.get_turn(
        session,
        user_id=principal.user_id,
        conversation_id=conversation_id,
        turn_id=message_id,
    )
    if turn is None:
        raise _not_found()
    return AssistantCitationListResponse(
        message_id=turn.id,
        items=tuple(
            AssistantCitationResponse.model_validate(item)
            for item in turn.answer.citations
        ),
    )


@assistant_router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete_assistant_conversation",
    summary="Erase one owner-scoped conversation and its audit metadata",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
    },
)
async def delete_assistant_conversation(
    conversation_id: UUID,
    session: DatabaseSession,
    history: AssistantHistoryDependency,
    principal: CurrentPrincipalDependency,
) -> Response:
    deleted = await history.delete(
        session,
        user_id=principal.user_id,
        conversation_id=conversation_id,
    )
    if not deleted:
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _message_response(
    *,
    conversation_id: UUID,
    turn: AssistantHistoryTurn,
    replayed: bool,
) -> AssistantMessageResponse:
    return AssistantMessageResponse(
        id=turn.id,
        conversation_id=conversation_id,
        ordinal=turn.ordinal,
        question=turn.question,
        answer=AssistantAnswerResponse.model_validate(turn.answer),
        created_at=turn.created_at,
        replayed=replayed,
    )


def _not_found() -> ApplicationError:
    return ApplicationError(
        code="assistant_resource_not_found",
        message="The requested assistant resource was not found.",
        status_code=404,
    )


__all__ = [
    "assistant_history_service_from",
    "assistant_orchestrator_from",
    "assistant_router",
]
