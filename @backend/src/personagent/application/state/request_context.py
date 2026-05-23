"""Per-request context object.

Before this module existed, request-scoped data (the active conversation
id, workspace root, system/user context, permission mode) was shoved into
a process-wide ``StateManager`` singleton. That singleton was a latent
multi-tenant bug: two concurrent requests would clobber each other's
``conversation_id`` and ``system_context``, and there was no way to scope
the data to a single caller.

:class:`RequestContext` replaces that pattern. It is:

* **Immutable** -- every field is frozen, so handing it down the call
  chain cannot accidentally smuggle state mutations back up.
* **Cheap to construct** -- one allocation per HTTP/WS request; callers
  can build it once at the edge and forward it without copying.
* **Multi-tenant ready** -- ``tenant_id`` and ``user_id`` slots are
  reserved now so later phases can populate them without another
  invasive refactor.

The intent is that anything which previously reached into
``StateManager.get_instance()`` now receives a ``RequestContext`` as an
explicit parameter, making the data flow visible in type signatures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from personagent.domain.context.models import (
    ContextBuildResult,
    SystemContext,
    UserContext,
)
from personagent.domain.models.tenancy import DEFAULT_TENANT_ID

PermissionMode = str
"""Symbolic alias for the allowed permission strings (``auto`` / ``manual`` /
``ask``). Kept as a plain string for now to avoid touching the dozens of
call sites that pass these values around. A future PR can promote it to a
``Literal`` or ``Enum`` once the call graph is mapped."""


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Snapshot of the data needed to serve one chat/team-mode request.

    Construct one per request at the API edge and pass it through to use
    cases and tool runtimes. Treat as read-only: if you need a mutated
    variant use :meth:`with_overrides`.
    """

    request_id: str = field(default_factory=lambda: str(uuid4()))
    conversation_id: str = ""
    workspace_root: str = ""
    permission_mode: PermissionMode = "manual"
    system_context: SystemContext | None = None
    user_context: UserContext | None = None
    tenant_id: UUID = DEFAULT_TENANT_ID
    user_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_build_result(
        cls,
        *,
        conversation_id: str,
        workspace_root: str,
        result: ContextBuildResult,
        permission_mode: PermissionMode = "manual",
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
        request_id: str | None = None,
    ) -> RequestContext:
        """Build a context from the output of :class:`BuildContextUseCase`.

        Kept as a classmethod (rather than a free function) so the most
        common construction path is discoverable from the type itself.

        ``tenant_id=None`` falls back to :data:`DEFAULT_TENANT_ID` so
        single-tenant installs never need to think about tenancy. Pass an
        explicit value once multi-tenant onboarding lands.
        """

        return cls(
            request_id=request_id or str(uuid4()),
            conversation_id=conversation_id,
            workspace_root=workspace_root,
            permission_mode=permission_mode,
            system_context=result.system_context,
            user_context=result.user_context,
            tenant_id=tenant_id if tenant_id is not None else DEFAULT_TENANT_ID,
            user_id=user_id,
        )

    def with_overrides(
        self,
        *,
        conversation_id: str | None = None,
        workspace_root: str | None = None,
        permission_mode: PermissionMode | None = None,
        system_context: SystemContext | None = None,
        user_context: UserContext | None = None,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
        extra: dict[str, Any] | None = None,
    ) -> RequestContext:
        """Return a copy with the supplied fields replaced.

        Useful when a downstream layer needs to refine the context -- for
        example, swapping ``permission_mode`` to ``ask`` while keeping
        every other field intact.
        """

        return RequestContext(
            request_id=self.request_id,
            conversation_id=conversation_id if conversation_id is not None else self.conversation_id,
            workspace_root=workspace_root if workspace_root is not None else self.workspace_root,
            permission_mode=permission_mode if permission_mode is not None else self.permission_mode,
            system_context=system_context if system_context is not None else self.system_context,
            user_context=user_context if user_context is not None else self.user_context,
            tenant_id=tenant_id if tenant_id is not None else self.tenant_id,
            user_id=user_id if user_id is not None else self.user_id,
            created_at=self.created_at,
            extra=extra if extra is not None else dict(self.extra),
        )


__all__ = ["PermissionMode", "RequestContext"]
