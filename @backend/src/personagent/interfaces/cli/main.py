"""CLI do PersonAgent com Typer + Rich."""

import asyncio
from uuid import UUID

import structlog
import typer
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.use_cases.chat_completion import ChatCompletionUseCase
from personagent.domain.exceptions import PersonAgentError
from personagent.infrastructure.config.settings import get_settings
from personagent.infrastructure.persistence.database import AsyncSessionLocal, init_db
from personagent.infrastructure.persistence.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from personagent.interfaces.config.di_container import get_container

app = typer.Typer(
    name="personagent",
    help="🤖 PersonAgent — Sistema de Agente Pessoal com llama.cpp + TurboQuant",
    no_args_is_help=True,
)
console = Console()
logger = structlog.get_logger(__name__)


@app.command()
def chat(
    message: str = typer.Option(..., "-m", "--message", help="Mensagem para o agente"),
    conversation_id: str = typer.Option(None, "-c", "--conversation", help="ID da conversa"),
    system_prompt: str = typer.Option(None, "-s", "--system", help="Prompt de sistema"),
    temperature: float = typer.Option(0.7, "-t", "--temp", help="Temperatura"),
    stream: bool = typer.Option(True, "--stream/--no-stream", help="Streaming de resposta"),
    no_think: bool = typer.Option(False, "--no-think", help="Oculta reasoning/thinking"),
) -> None:
    """Envia uma mensagem para o agente e recebe a resposta."""
    asyncio.run(_chat(message, conversation_id, system_prompt, temperature, stream, no_think))


async def _chat(
    message: str,
    conversation_id: str | None,
    system_prompt: str | None,
    temperature: float,
    stream: bool,
    no_think: bool,
) -> None:
    """Implementação assíncrona do comando chat."""
    container = get_container()

    # Inicializa banco
    await init_db()

    session = AsyncSessionLocal()
    try:
        conv_repo = PostgresConversationRepository(session)
        llm_backend = container.get_llm_backend()

        use_case = ChatCompletionUseCase(
            conversation_repo=conv_repo,
            llm_backend=llm_backend,
            tool_registry=container.get_tool_registry(),
            tool_runtime_config=container.get_tool_runtime_config(),
        )

        conv_id = UUID(conversation_id) if conversation_id else None
        dto = ChatRequestDTO(
            conversation_id=conv_id,
            message=message,
            system_prompt=system_prompt,
            stream=stream,
            temperature=temperature,
        )

        if not stream:
            # Modo síncrono
            with console.status("[bold green]🤖 Pensando..."):
                result = await use_case.execute(dto)

            console.print(
                Panel(
                    Markdown(result.content),
                    title="🤖 PersonAgent",
                    border_style="blue",
                )
            )
            console.print(f"\n[dim]Conversa: {result.conversation_id}[/dim]")
        else:
            # Modo streaming
            content_parts = []
            reasoning_parts = []

            with Live(console=console, refresh_per_second=10) as live:
                async for chunk in use_case.execute_stream(dto):
                    if chunk.reasoning_content and not no_think:
                        reasoning_parts.append(chunk.reasoning_content)
                    if chunk.content:
                        content_parts.append(chunk.content)

                    # Atualiza display
                    display = ""
                    if reasoning_parts and not no_think:
                        think_text = "".join(reasoning_parts)
                        display += f"[dim italic]💭 {think_text}[/dim italic]\n\n"
                    display += "".join(content_parts)

                    live.update(
                        Panel(
                            Markdown(display),
                            title="🤖 PersonAgent [streaming]",
                            border_style="green",
                        )
                    )

                console.print(f"\n[dim]Conversa: {dto.conversation_id or 'nova'}[/dim]")

    except PersonAgentError as exc:
        console.print(f"[red]❌ Erro: {exc}[/red]")
        raise typer.Exit(1) from exc
    finally:
        await session.close()


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", help="Host para o servidor"),
    port: int = typer.Option(8000, "--port", help="Porta para o servidor"),
    reload: bool = typer.Option(False, "--reload", help="Hot reload (dev)"),
) -> None:
    """Inicia o servidor API FastAPI."""
    import uvicorn

    console.print(f"[bold green]🚀 Iniciando PersonAgent API em http://{host}:{port}[/bold green]")
    uvicorn.run(
        "personagent.interfaces.api.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


@app.command()
def model(
    status: bool = typer.Option(False, "--status", help="Verifica status do modelo"),
    info: bool = typer.Option(False, "--info", help="Mostra informações do modelo"),
) -> None:
    """Gerencia o modelo LLM local."""
    asyncio.run(_model(status, info))


async def _model(status: bool, info: bool) -> None:
    """Implementação assíncrona do comando model."""
    container = get_container()
    llm = container.get_llm_backend()

    settings = get_settings()

    console.print(
        Panel.fit(
            f"[bold]Modelo:[/bold] {settings.llama_model_path}\n"
            f"[bold]Servidor:[/bold] {settings.llama_server_url}\n"
            f"[bold]TurboQuant:[/bold] K={settings.llama_cache_type_k}, V={settings.llama_cache_type_v}\n"
            f"[bold]Contexto:[/bold] {settings.llama_ctx_size} tokens\n"
            f"[bold]GPU Layers:[/bold] {settings.llama_n_gpu_layers}",
            title="📊 Configuração do Modelo",
            border_style="cyan",
        )
    )

    if status:
        health = await llm.health_check()
        is_healthy = health.get("status") == "healthy"
        console.print(
            Panel.fit(
                f"[bold]Status:[/bold] {'✅ Saudável' if is_healthy else '❌ Indisponível'}\n"
                f"[bold]Detalhes:[/bold] {health.get('details', 'N/A')}",
                title="🏥 Health Check",
                border_style="green" if is_healthy else "red",
            )
        )

    if info:
        model_info = await llm.get_model_info()
        if model_info:
            console.print(
                Panel.fit(
                    str(model_info),
                    title="ℹ️ Informações do Modelo",
                    border_style="blue",
                )
            )
        else:
            console.print("[yellow]⚠️ Não foi possível obter informações do modelo[/yellow]")


@app.command()
def conversations_list(
    limit: int = typer.Option(20, "--limit", help="Número máximo de resultados"),
) -> None:
    """Lista todas as conversas."""
    asyncio.run(_conversations_list(limit))


async def _conversations_list(limit: int) -> None:
    """Implementação assíncrona do comando conversations."""
    await init_db()
    session = AsyncSessionLocal()
    try:
        repo = PostgresConversationRepository(session)
        convs = await repo.list_all(limit=limit)

        if not convs:
            console.print("[dim]Nenhuma conversa encontrada.[/dim]")
            return

        for conv in convs:
            console.print(
                f"[bold]{conv.title}[/bold] [dim]({conv.id})[/dim]\n"
                f"  {len(conv.messages)} mensagens · {conv.updated_at.strftime('%Y-%m-%d %H:%M')}\n"
            )
    finally:
        await session.close()


@app.command()
def conversation_delete(
    conversation_id: str = typer.Argument(..., help="ID da conversa para remover"),
) -> None:
    """Remove uma conversa."""
    asyncio.run(_conversation_delete(conversation_id))


async def _conversation_delete(conversation_id: str) -> None:
    """Implementação assíncrona do comando delete."""
    await init_db()
    session = AsyncSessionLocal()
    try:
        repo = PostgresConversationRepository(session)
        deleted = await repo.delete(UUID(conversation_id))
        if deleted:
            console.print(f"[green]✅ Conversa {conversation_id} removida[/green]")
        else:
            console.print(f"[yellow]⚠️ Conversa {conversation_id} não encontrada[/yellow]")
    finally:
        await session.close()


# Entrypoint para `python -m personagent` ou `personagent`
if __name__ == "__main__":
    app()
