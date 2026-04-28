"""Routes for conversation management."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.domain.models.conversation import Conversation, Message
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


def _workspace_root_from_metadata(metadata: dict | None) -> str | None:
    value = (metadata or {}).get("workspace_root")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
