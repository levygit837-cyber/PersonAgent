"""PersonAgent CLI with Typer + Rich."""

import asyncio
from uuid import UUID

import structlog
import typer
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

from personagent.adapters.composition import get_container
from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat_completion import ChatCompletionUseCase
from personagent.domain.exceptions import PersonAgentError
from personagent.infrastructure.persistence.database import AsyncSessionLocal, init_db
from personagent.infrastructure.persistence.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from personagent.infrastructure.settings.settings import get_settings

app = typer.Typer(
    name="personagent",
    help="🤖 PersonAgent — Personal agent system with llama.cpp + TurboQuant",
    no_args_is_help=True,
)
console = Console()
logger = structlog.get_logger(__name__)


@app.command()
def chat(
    message: str = typer.Option(..., "-m", "--message", help="Message for the agent"),
    conversation_id: str = typer.Option(None, "-c", "--conversation", help="Conversation ID"),
    system_prompt: str = typer.Option(None, "-s", "--system", help="System prompt"),
    temperature: float = typer.Option(0.7, "-t", "--temp", help="Temperature"),
    stream: bool = typer.Option(True, "--stream/--no-stream", help="Response streaming"),
    no_think: bool = typer.Option(False, "--no-think", help="Hide reasoning/thinking"),
) -> None:
    """Send a message to the agent and receive the response."""
    asyncio.run(_chat(message, conversation_id, system_prompt, temperature, stream, no_think))


async def _chat(
    message: str,
    conversation_id: str | None,
    system_prompt: str | None,
    temperature: float,
    stream: bool,
    no_think: bool,
) -> None:
    """Asynchronous implementation of the chat command."""
    container = get_container()

        # Initialize the database
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
            artifact_root=container.settings.personagent_artifact_root,
            artifact_ttl_seconds=container.settings.personagent_artifact_ttl_seconds,
            artifact_storage=container.get_artifact_storage(),
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
            # Synchronous mode
            with console.status("[bold green]🤖 Thinking..."):
                result = await use_case.execute(dto)

            console.print(
                Panel(
                    Markdown(result.content),
                    title="🤖 PersonAgent",
                    border_style="blue",
                )
            )
            console.print(f"\n[dim]Conversation: {result.conversation_id}[/dim]")
        else:
            # Streaming mode
            content_parts = []
            reasoning_parts = []

            with Live(console=console, refresh_per_second=10) as live:
                async for chunk in use_case.execute_stream(dto):
                    if chunk.reasoning_content and not no_think:
                        reasoning_parts.append(chunk.reasoning_content)
                    if chunk.content:
                        content_parts.append(chunk.content)

                    # Update display
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

                console.print(f"\n[dim]Conversation: {dto.conversation_id or 'new'}[/dim]")

    except PersonAgentError as exc:
        console.print(f"[red]❌ Error: {exc}[/red]")
        raise typer.Exit(1) from exc
    finally:
        await session.close()


@app.command()
def tui(
    backend_url: str = typer.Option(None, "--backend-url", help="PersonAgent backend URL"),
) -> None:
    """Launch the interactive terminal chat UI."""
    from personagent.adapters.tui.app import ChatApp

    app = ChatApp(base_url=backend_url)
    app.run(mouse=True)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Server host"),
    port: int = typer.Option(8000, "--port", help="Server port"),
    reload: bool = typer.Option(False, "--reload", help="Hot reload (dev)"),
) -> None:
    """Start the FastAPI server."""
    import uvicorn

    console.print(f"[bold green]🚀 Starting PersonAgent API at http://{host}:{port}[/bold green]")
    uvicorn.run(
        "personagent.adapters.api.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


@app.command()
def memory_worker() -> None:
    """Run the RabbitMQ operational-memory worker."""
    asyncio.run(_memory_worker())


async def _memory_worker() -> None:
    await init_db()
    container = get_container()
    queue = container.get_operational_memory_queue()
    service = container.get_operational_memory_service()
    if queue is None or service is None:
        console.print("[red]Memory queue is disabled. Set MEMORY_QUEUE_ENABLED=true.[/red]")
        raise typer.Exit(1)
    console.print("[green]Operational memory worker is consuming RabbitMQ jobs.[/green]")
    await queue.consume(service.process_outbox_message)


@app.command()
def model(
    status: bool = typer.Option(False, "--status", help="Check model status"),
    info: bool = typer.Option(False, "--info", help="Show model information"),
) -> None:
    """Manage the local LLM model."""
    asyncio.run(_model(status, info))


async def _model(status: bool, info: bool) -> None:
    """Asynchronous implementation of the model command."""
    container = get_container()
    llm = container.get_llm_backend()

    settings = get_settings()

    console.print(
        Panel.fit(
            f"[bold]Model:[/bold] {settings.llama_model_path}\n"
            f"[bold]Server:[/bold] {settings.llama_server_url}\n"
            f"[bold]TurboQuant:[/bold] K={settings.llama_cache_type_k}, V={settings.llama_cache_type_v}\n"
            f"[bold]Context:[/bold] {settings.llama_ctx_size} tokens\n"
            f"[bold]GPU Layers:[/bold] {settings.llama_n_gpu_layers}",
            title="📊 Model Configuration",
            border_style="cyan",
        )
    )

    if status:
        health = await llm.health_check()
        is_healthy = health.get("status") == "healthy"
        console.print(
            Panel.fit(
                f"[bold]Status:[/bold] {'✅ Healthy' if is_healthy else '❌ Unavailable'}\n"
                f"[bold]Details:[/bold] {health.get('details', 'N/A')}",
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
                    title="ℹ️ Model Information",
                    border_style="blue",
                )
            )
        else:
            console.print("[yellow]⚠️ Could not retrieve model information[/yellow]")


@app.command()
def conversations_list(
    limit: int = typer.Option(20, "--limit", help="Maximum number of results"),
) -> None:
    """List all conversations."""
    asyncio.run(_conversations_list(limit))


async def _conversations_list(limit: int) -> None:
    """Asynchronous implementation of the conversations command."""
    await init_db()
    session = AsyncSessionLocal()
    try:
        repo = PostgresConversationRepository(session)
        convs = await repo.list_all(limit=limit)

        if not convs:
            console.print("[dim]No conversations found.[/dim]")
            return

        for conv in convs:
            console.print(
                f"[bold]{conv.title}[/bold] [dim]({conv.id})[/dim]\n"
                f"  {len(conv.messages)} messages · {conv.updated_at.strftime('%Y-%m-%d %H:%M')}\n"
            )
    finally:
        await session.close()


@app.command()
def conversation_delete(
    conversation_id: str = typer.Argument(..., help="Conversation ID to delete"),
) -> None:
    """Delete a conversation."""
    asyncio.run(_conversation_delete(conversation_id))


async def _conversation_delete(conversation_id: str) -> None:
    """Asynchronous implementation of the delete command."""
    await init_db()
    session = AsyncSessionLocal()
    try:
        repo = PostgresConversationRepository(session)
        deleted = await repo.delete(UUID(conversation_id))
        if deleted:
            console.print(f"[green]✅ Conversation {conversation_id} deleted[/green]")
        else:
            console.print(f"[yellow]⚠️ Conversation {conversation_id} not found[/yellow]")
    finally:
        await session.close()


# Entrypoint for `python -m personagent` or `personagent`
if __name__ == "__main__":
    app()
