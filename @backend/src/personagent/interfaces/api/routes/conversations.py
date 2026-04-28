"""Routes for conversation management."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.domain.models.conversation import Conversation, Message, Role
from personagent.interfaces.api.routes.chat import get_db
from personagent.interfaces.config.di_container import get_container

router = APIRouter(prefix="/conversations", tags=["conversations"])
DB_SESSION_DEPENDENCY = Depends(get_db)


class ConversationListResponse(BaseModel):
    """Conversation list response."""

    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    workspace_root: str | None = None


class ConversationDetailResponse(BaseModel):
    """Detailed conversation response."""

    id: str
    title: str
    messages: list[dict]
    created_at: str
    updated_at: str


class ConversationForkMessage(BaseModel):
    """Message payload used to fork a conversation prefix."""

    role: str
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


class ConversationForkRequest(BaseModel):
    """Create a new conversation with an existing prefix."""

    title: str | None = None
    workspace_root: str | None = None
    messages: list[ConversationForkMessage] = Field(default_factory=list)


def serialize_message(message: Message) -> dict:
    """Serialize messages for the UI without polluting the payload sent to the LLM."""
    data = message.to_dict()
    data["timestamp"] = message.timestamp.isoformat()
    if message.metadata:
        data["metadata"] = message.metadata
    return data


@router.get("", response_model=list[ConversationListResponse])
async def list_conversations(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> list[ConversationListResponse]:
    """List all conversations."""
    container = get_container()
    repo = await container.get_conversation_repo(session)
    title_service = getattr(container, "get_session_title_service", lambda: None)()
    if title_service is not None:
        await title_service.maybe_repair_duplicate_titles(repo)
    list_summaries = getattr(repo, "list_summaries", None)
    if callable(list_summaries):
        return [
            ConversationListResponse(**summary)
            for summary in await list_summaries(limit=limit, offset=offset)
        ]

    conversations = await repo.list_all(limit=limit, offset=offset)

    return [_conversation_list_response(conv) for conv in conversations]


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: str,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> ConversationDetailResponse:
    """Retrieve a conversation by ID."""
    container = get_container()
    repo = await container.get_conversation_repo(session)
    conv = await repo.get_by_id(UUID(conversation_id))

    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return ConversationDetailResponse(
        id=str(conv.id),
        title=conv.title,
        messages=[serialize_message(msg) for msg in conv.messages],
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
    )


@router.post("/{conversation_id}/fork", response_model=ConversationDetailResponse)
async def fork_conversation(
    conversation_id: str,
    payload: ConversationForkRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> ConversationDetailResponse:
    """Create a new conversation from a UI-selected prefix."""
    container = get_container()
    repo = await container.get_conversation_repo(session)
    source = await repo.get_by_id(UUID(conversation_id))

    if not source:
        raise HTTPException(status_code=404, detail="Conversation not found")

    fork = Conversation(
        title=(payload.title or source.title or "New Chat").strip() or "New Chat",
        model_config_id=source.model_config_id,
        metadata=dict(source.metadata or {}),
    )
    if payload.workspace_root and payload.workspace_root.strip():
        fork.metadata["workspace_root"] = payload.workspace_root.strip()

    fork.messages = [
        Message(
            role=role,
            content=item.content,
            tool_calls=item.tool_calls,
            tool_call_id=item.tool_call_id,
            metadata=item.metadata,
        )
        for item in payload.messages
        if (role := _fork_message_role(item.role)) is not None
    ]
    await repo.create(fork)

    return ConversationDetailResponse(
        id=str(fork.id),
        title=fork.title,
        messages=[serialize_message(msg) for msg in fork.messages],
        created_at=fork.created_at.isoformat(),
        updated_at=fork.updated_at.isoformat(),
    )


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, bool]:
    """Delete a conversation by ID."""
    container = get_container()
    repo = await container.get_conversation_repo(session)
    deleted = await repo.delete(UUID(conversation_id))

    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return {"deleted": True}


@router.get("/search/{query}", response_model=list[ConversationListResponse])
async def search_conversations(
    query: str,
    limit: int = 10,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> list[ConversationListResponse]:
    """Search conversations by content."""
    container = get_container()
    repo = await container.get_conversation_repo(session)
    search_summaries = getattr(repo, "search_summaries", None)
    if callable(search_summaries):
        return [
            ConversationListResponse(**summary)
            for summary in await search_summaries(query, limit=limit)
        ]

    conversations = await repo.search(query, limit=limit)

    return [_conversation_list_response(conv) for conv in conversations]


def _conversation_list_response(conv: Conversation) -> ConversationListResponse:
    return ConversationListResponse(
        id=str(conv.id),
        title=conv.title,
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
        message_count=len(conv.messages),
        workspace_root=_workspace_root_from_metadata(conv.metadata),
    )


def _fork_message_role(raw_role: str) -> Role | None:
    role = raw_role.strip().lower()
    if role in {"assistant", "agent"}:
        return Role.ASSISTANT
    if role == "user":
        return Role.USER
    if role == "tool":
        return Role.TOOL
    if role == "system":
        return Role.SYSTEM
    return None


def _workspace_root_from_metadata(metadata: dict | None) -> str | None:
    value = (metadata or {}).get("workspace_root")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
