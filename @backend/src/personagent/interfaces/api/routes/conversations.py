"""Rotas para gerenciamento de conversas."""

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
    """Resposta de listagem de conversas."""

    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class ConversationDetailResponse(BaseModel):
    """Resposta detalhada de uma conversa."""

    id: str
    title: str
    messages: list[dict]
    created_at: str
    updated_at: str


def serialize_message(message: Message) -> dict:
    """Serializa mensagens para a UI sem contaminar o payload enviado ao LLM."""
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
    """Lista todas as conversas."""
    container = get_container()
    repo = await container.get_conversation_repo(session)
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
    """Recupera uma conversa pelo ID."""
    container = get_container()
    repo = await container.get_conversation_repo(session)
    conv = await repo.get_by_id(UUID(conversation_id))

    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

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
    """Remove uma conversa pelo ID."""
    container = get_container()
    repo = await container.get_conversation_repo(session)
    deleted = await repo.delete(UUID(conversation_id))

    if not deleted:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    return {"deleted": True}


@router.get("/search/{query}", response_model=list[ConversationListResponse])
async def search_conversations(
    query: str,
    limit: int = 10,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> list[ConversationListResponse]:
    """Busca conversas por conteúdo."""
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
    )
