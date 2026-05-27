from __future__ import annotations

from typing import Any

from personagent.application.qa.contracts import QASessionData, QASessionStatus, TraceMode


def _session_data_from_orm(orm: Any) -> QASessionData:
    return QASessionData(
        id=str(orm.id),
        repo_root=str(orm.repo_root),
        sandbox_path=str(orm.sandbox_path) if orm.sandbox_path else None,
        base_commit=str(orm.base_commit) if orm.base_commit else None,
        branch_name=str(orm.branch_name) if orm.branch_name else None,
        branch_mode=str(orm.branch_mode),
        env_profile=orm.env_profile,
        trace_mode=TraceMode(str(orm.trace_mode or TraceMode.FUNCTION.value)),
        agent_id=str(orm.agent_id) if orm.agent_id else None,
        status=QASessionStatus(str(orm.status or QASessionStatus.ACTIVE.value)),
        metadata=dict(orm.metadata_ or {}),
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )
