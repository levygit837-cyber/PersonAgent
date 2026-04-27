"""Public workflow canvas API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.application.workflows import (
    WorkflowNodeType,
    WorkflowRunner,
    WorkflowValidationError,
    default_workflow_document,
    node_config_schema,
    parse_workflow_document,
    serialize_workflow_document,
    validate_workflow_document,
)
from personagent.application.workflows.runner import WorkflowExecutionError
from personagent.application.workflows.store import (
    SqlAlchemyWorkflowStore,
    WorkflowStore,
)
from personagent.domain.exceptions import LLMBackendError
from personagent.infrastructure.persistence.database import AsyncSessionLocal
from personagent.infrastructure.persistence.models import LabGraphORM, WorkflowRunORM
from personagent.interfaces.api.routes.chat import get_db
from personagent.interfaces.config.di_container import get_container

router = APIRouter(prefix="/workflows", tags=["workflows"])
logger = structlog.get_logger(__name__)
DB_SESSION_DEPENDENCY = Depends(get_db)


class WorkflowCreateRequest(BaseModel):
    """Request body for creating a workflow."""

    title: str = Field(default="Untitled Workflow", min_length=1, max_length=255)
    workflow: dict[str, Any] | None = None


class WorkflowUpdateRequest(BaseModel):
    """Request body for updating a workflow."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    workflow: dict[str, Any] | None = None


class WorkflowRunRequest(BaseModel):
    """Request body for running a workflow."""

    input: Any = Field(default="")
    tool_context: dict[str, Any] = Field(default_factory=dict)


class WorkflowResponse(BaseModel):
    """Workflow API response."""

    id: str
    title: str
    workflow: dict[str, Any]
    created_at: str
    updated_at: str


async def get_workflow_store(
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> WorkflowStore:
    """Build the workflow store dependency."""

    return SqlAlchemyWorkflowStore(session)


WORKFLOW_STORE_DEPENDENCY = Depends(get_workflow_store)


def encode_sse(data: dict[str, Any]) -> str:
    """Encode a JSON payload as a server-sent event."""

    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def serialize_workflow_record(record: LabGraphORM) -> WorkflowResponse:
    """Serialize the shared lab_graphs ORM record as a workflow."""

    created_at = record.created_at or datetime.now()
    updated_at = record.updated_at or created_at
    return WorkflowResponse(
        id=str(record.id),
        title=record.title,
        workflow=record.graph or {},
        created_at=created_at.isoformat(),
        updated_at=updated_at.isoformat(),
    )


def validated_workflow_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse, validate, and serialize a workflow document."""

    document = parse_workflow_document(payload)
    validate_workflow_document(document)
    return serialize_workflow_document(document)


@router.get("", response_model=list[WorkflowResponse])
async def list_workflows(
    limit: int = 50,
    offset: int = 0,
    store: WorkflowStore = WORKFLOW_STORE_DEPENDENCY,
) -> list[WorkflowResponse]:
    """List workflows ordered by most recent update."""

    workflows = await store.list(limit=limit, offset=offset)
    return [serialize_workflow_record(workflow) for workflow in workflows]


@router.post("", response_model=WorkflowResponse)
async def create_workflow(
    request: WorkflowCreateRequest,
    store: WorkflowStore = WORKFLOW_STORE_DEPENDENCY,
) -> WorkflowResponse:
    """Create a workflow."""

    try:
        workflow = validated_workflow_payload(request.workflow or default_workflow_document())
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record = await store.create(title=request.title, workflow=workflow)
    return serialize_workflow_record(record)


@router.get("/node-types")
async def list_workflow_node_types() -> dict[str, Any]:
    """Return the node catalog and currently registered tools."""

    container = get_container()
    tools = [
        {
            "name": tool.definition.name,
            "description": tool.definition.description,
            "input_schema": tool.definition.input_schema,
            "output_schema": tool.definition.output_schema,
            "aliases": list(tool.definition.aliases),
            "read_only": tool.is_read_only({}),
        }
        for tool in container.get_tool_registry().list_enabled()
    ]
    return {
        "schema_version": "1.0",
        "supported_perks": ["tools", "workspace"],
        "unsupported_perks": ["browser", "queue", "redis", "database", "memory"],
        "tools": tools,
        "node_types": [
            _node_type(
                "trigger",
                "Trigger",
                "Starts a workflow from a run payload or on a schedule.",
                executable=True,
                outputs=["out"],
                config_schema=node_config_schema(WorkflowNodeType.TRIGGER),
            ),
            _node_type(
                "agent",
                "Agent Node",
                "Runs local LLM instructions with optional tools and workspace context.",
                executable=True,
                outputs=["out"],
                perks=["tools", "workspace"],
                config_schema=node_config_schema(WorkflowNodeType.AGENT),
            ),
            _node_type(
                "if_else",
                "If/Else Node",
                "Routes the previous output to then or else with an LLM router.",
                executable=True,
                outputs=["then", "else"],
                config_schema=node_config_schema(WorkflowNodeType.IF_ELSE),
            ),
            _node_type(
                "output",
                "Output Node",
                "Collects and emits the final workflow result.",
                executable=True,
                outputs=[],
                config_schema=node_config_schema(WorkflowNodeType.OUTPUT),
            ),
            _node_type(
                "browser",
                "Browser Node",
                "Future persistent browser automation node.",
                executable=False,
                future=True,
                outputs=["out"],
                perks=["browser"],
            ),
            _node_type(
                "tool",
                "Tool Node",
                "Executes one registered tool with explicit JSON arguments.",
                executable=True,
                outputs=["out"],
                perks=["tools", "workspace"],
                config_schema=node_config_schema(WorkflowNodeType.TOOL),
            ),
            _node_type(
                "schema_validator",
                "Schema Validator",
                "Validates JSON-like output before the next node.",
                executable=True,
                outputs=["out"],
                config_schema=node_config_schema(WorkflowNodeType.SCHEMA_VALIDATOR),
            ),
            _node_type("memory", "Memory Node", "Roadmap node for memory I/O.", outputs=["out"]),
            _node_type(
                "human_approval",
                "Human Approval",
                "Roadmap node that pauses for approval.",
                outputs=["out"],
            ),
            _node_type(
                "queue_delay", "Queue Delay", "Roadmap node for queue/delay.", outputs=["out"]
            ),
            _node_type(
                "subworkflow", "Subworkflow", "Roadmap node for nested workflows.", outputs=["out"]
            ),
            _node_type(
                "artifact_transform",
                "Artifact Transform",
                "Transforms prior output into text, Markdown, or JSON.",
                executable=True,
                outputs=["out"],
                config_schema=node_config_schema(WorkflowNodeType.ARTIFACT_TRANSFORM),
            ),
        ],
    }


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: UUID,
    store: WorkflowStore = WORKFLOW_STORE_DEPENDENCY,
) -> WorkflowResponse:
    """Load one workflow."""

    workflow = await store.get(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return serialize_workflow_record(workflow)


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: UUID,
    request: WorkflowUpdateRequest,
    store: WorkflowStore = WORKFLOW_STORE_DEPENDENCY,
) -> WorkflowResponse:
    """Update a workflow title and/or document."""

    workflow_payload = None
    if request.workflow is not None:
        try:
            workflow_payload = validated_workflow_payload(request.workflow)
        except WorkflowValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    workflow = await store.update(
        workflow_id,
        title=request.title,
        workflow=workflow_payload,
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return serialize_workflow_record(workflow)


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: UUID,
    store: WorkflowStore = WORKFLOW_STORE_DEPENDENCY,
) -> dict[str, bool]:
    """Delete a workflow."""

    deleted = await store.delete(workflow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"deleted": True}


@router.post("/{workflow_id}/runs/stream")
async def run_workflow_stream(
    workflow_id: UUID,
    request: WorkflowRunRequest,
    store: WorkflowStore = WORKFLOW_STORE_DEPENDENCY,
) -> StreamingResponse:
    """Run a workflow and stream execution events."""

    workflow = await store.get(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    container = get_container()
    runner = WorkflowRunner(
        llm_backend=container.get_llm_backend(),
        tool_registry=container.get_tool_registry(),
        tool_runtime_config=container.get_tool_runtime_config(),
    )

    async def event_generator() -> AsyncIterator[str]:
        trace_events: list[dict] = []
        final_output: Any = None
        run_status = "running"
        error_message: str | None = None

        try:
            document = parse_workflow_document(workflow.graph or {})
            async for event in runner.execute(
                workflow_id=str(workflow.id),
                title=workflow.title,
                document=document,
                run_input=request.input,
                tool_context=request.tool_context,
            ):
                trace_events.append(event)
                if event.get("event") == "workflow_run_completed":
                    run_status = "completed"
                    final_output = event.get("output")
                yield encode_sse(event)
        except (WorkflowValidationError, WorkflowExecutionError, ValueError) as exc:
            run_status = "failed"
            error_message = str(exc)
            yield encode_sse({"event": "node_error", "error": error_message, "status": 400})
        except LLMBackendError as exc:
            run_status = "failed"
            error_message = str(exc)
            yield encode_sse({"event": "node_error", "error": error_message, "status": 500})
        except Exception as exc:
            run_status = "failed"
            error_message = f"Unexpected workflow stream error: {exc}"
            logger.exception("workflow_stream_unhandled_error")
            yield encode_sse(
                {
                    "event": "node_error",
                    "error": error_message,
                    "status": 500,
                }
            )
        finally:
            logger.info("workflow_stream_closed", workflow_id=str(workflow_id))
            # Persist the run
            try:
                async with AsyncSessionLocal() as session:
                    run_orm = WorkflowRunORM(
                        workflow_id=workflow_id,
                        trigger_mode="manual",
                        status=run_status,
                        input={"run_input": request.input, "tool_context": request.tool_context},
                        output=final_output,
                        trace_events=trace_events,
                        error_message=error_message,
                        finished_at=datetime.utcnow(),
                    )
                    session.add(run_orm)
                    await session.commit()
                    logger.info(
                        "workflow_run_persisted",
                        run_id=str(run_orm.id),
                        workflow_id=str(workflow_id),
                        status=run_status,
                    )
            except Exception:
                logger.exception("workflow_run_persist_failed", workflow_id=str(workflow_id))
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _node_type(
    node_type: str,
    label: str,
    description: str,
    *,
    executable: bool = False,
    future: bool = False,
    outputs: list[str],
    perks: list[str] | None = None,
    config_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": node_type,
        "label": label,
        "description": description,
        "executable": executable,
        "future": future,
        "input_contract": {"kind": "any"},
        "output_contract": {"kind": "any"},
        "outputs": outputs,
        "perks": perks or [],
        "config_schema": config_schema or {"type": "object", "additionalProperties": True},
    }


@router.get("/{workflow_id}/runs")
async def list_workflow_runs(
    workflow_id: UUID,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """List execution runs for a workflow."""

    # Check workflow exists
    workflow = await db.execute(select(LabGraphORM).where(LabGraphORM.id == workflow_id))
    if workflow.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Count total
    count_result = await db.execute(
        select(func.count())
        .select_from(WorkflowRunORM)
        .where(WorkflowRunORM.workflow_id == workflow_id)
    )
    total = count_result.scalar() or 0

    # Fetch runs
    result = await db.execute(
        select(WorkflowRunORM)
        .where(WorkflowRunORM.workflow_id == workflow_id)
        .order_by(WorkflowRunORM.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    runs = result.scalars().all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "runs": [
            {
                "id": str(run.id),
                "trigger_mode": run.trigger_mode,
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "error_message": run.error_message,
            }
            for run in runs
        ],
    }


@router.get("/{workflow_id}/runs/{run_id}")
async def get_workflow_run(
    workflow_id: UUID,
    run_id: UUID,
    db: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Get a single workflow run with full trace events."""

    result = await db.execute(
        select(WorkflowRunORM)
        .where(WorkflowRunORM.id == run_id)
        .where(WorkflowRunORM.workflow_id == workflow_id)
    )
    run = result.scalar_one_or_none()

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return {
        "id": str(run.id),
        "workflow_id": str(run.workflow_id),
        "trigger_mode": run.trigger_mode,
        "status": run.status,
        "input": run.input,
        "output": run.output,
        "trace_events": run.trace_events,
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
