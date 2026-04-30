"""Local artifact storage for large runtime payloads."""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import quote

DEFAULT_ARTIFACT_ROOT = Path(
    os.getenv("PERSONAGENT_ARTIFACT_ROOT", "~/.cache/personagent/artifacts")
).expanduser()

_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_ALLOWED_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "text/html",
    "text/plain",
}


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    """Reference to a payload stored outside chat/tool JSON."""

    artifact_id: str
    category: str
    conversation_id: str
    path: Path
    mime_type: str
    size_bytes: int
    sha256: str
    url: str
    expires_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "artifact_id": self.artifact_id,
            "category": self.category,
            "conversation_id": self.conversation_id,
            "path": str(self.path),
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "url": self.url,
        }
        if self.expires_at is not None:
            data["expires_at"] = self.expires_at
        return data


def artifact_root(raw_root: str | Path | None = None) -> Path:
    return Path(raw_root).expanduser() if raw_root else DEFAULT_ARTIFACT_ROOT


def safe_segment(value: str | None, *, fallback: str = "default") -> str:
    cleaned = _SAFE_SEGMENT_RE.sub("_", (value or "").strip()).strip("._")
    return cleaned[:160] or fallback


def artifact_url(conversation_id: str, category: str, artifact_id: str) -> str:
    return (
        f"/artifacts/{quote(safe_segment(conversation_id), safe='')}/"
        f"{quote(safe_segment(category), safe='')}/{quote(safe_segment(artifact_id), safe='')}"
    )


def store_text_artifact(
    *,
    category: str,
    conversation_id: str,
    content: str,
    suffix: str = ".txt",
    mime_type: str = "text/plain",
    root: str | Path | None = None,
    ttl_seconds: float | None = None,
    artifact_id: str | None = None,
) -> StoredArtifact:
    return store_bytes_artifact(
        category=category,
        conversation_id=conversation_id,
        content=content.encode("utf-8"),
        suffix=suffix,
        mime_type=mime_type,
        root=root,
        ttl_seconds=ttl_seconds,
        artifact_id=artifact_id,
    )


def store_bytes_artifact(
    *,
    category: str,
    conversation_id: str,
    content: bytes,
    suffix: str,
    mime_type: str,
    root: str | Path | None = None,
    ttl_seconds: float | None = None,
    artifact_id: str | None = None,
) -> StoredArtifact:
    safe_category = safe_segment(category, fallback="artifacts")
    safe_conversation = safe_segment(conversation_id, fallback="conversation")
    extension = suffix if suffix.startswith(".") else f".{suffix}"
    safe_artifact_id = safe_segment(
        artifact_id or f"{safe_category}_{secrets.token_urlsafe(18)}{extension}",
        fallback=f"artifact_{secrets.token_urlsafe(8)}{extension}",
    )
    storage_dir = artifact_root(root) / safe_category / safe_conversation
    storage_dir.mkdir(parents=True, exist_ok=True)
    path = storage_dir / safe_artifact_id
    path.write_bytes(content)
    digest = sha256(content).hexdigest()
    now = datetime.now(UTC)
    expires_at = now.timestamp() + float(ttl_seconds) if ttl_seconds and ttl_seconds > 0 else None
    metadata = {
        "artifact_id": safe_artifact_id,
        "category": safe_category,
        "conversation_id": safe_conversation,
        "mime_type": mime_type,
        "size_bytes": len(content),
        "sha256": digest,
        "created_at": now.isoformat(),
        "expires_at": expires_at,
    }
    (storage_dir / f"{safe_artifact_id}.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return StoredArtifact(
        artifact_id=safe_artifact_id,
        category=safe_category,
        conversation_id=safe_conversation,
        path=path,
        mime_type=mime_type,
        size_bytes=len(content),
        sha256=digest,
        url=artifact_url(safe_conversation, safe_category, safe_artifact_id),
        expires_at=expires_at,
    )


def load_artifact(
    *,
    category: str,
    conversation_id: str,
    artifact_id: str,
    root: str | Path | None = None,
) -> StoredArtifact:
    safe_category = safe_segment(category, fallback="artifacts")
    safe_conversation = safe_segment(conversation_id, fallback="conversation")
    safe_artifact_id = safe_segment(artifact_id, fallback="")
    if not safe_artifact_id:
        raise FileNotFoundError("Missing artifact id.")
    storage_dir = artifact_root(root) / safe_category / safe_conversation
    path = storage_dir / safe_artifact_id
    metadata_path = storage_dir / f"{safe_artifact_id}.json"
    if not path.is_file() or not metadata_path.is_file():
        raise FileNotFoundError(safe_artifact_id)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    mime_type = str(metadata.get("mime_type") or "")
    if _base_mime_type(mime_type) not in _ALLOWED_MIME_TYPES:
        raise PermissionError(f"Blocked artifact MIME type: {mime_type}")
    expires_at = metadata.get("expires_at")
    if isinstance(expires_at, (int, float)) and expires_at > 0 and expires_at <= datetime.now(UTC).timestamp():
        delete_artifact(category=safe_category, conversation_id=safe_conversation, artifact_id=safe_artifact_id, root=root)
        raise FileNotFoundError(safe_artifact_id)
    return StoredArtifact(
        artifact_id=safe_artifact_id,
        category=safe_category,
        conversation_id=safe_conversation,
        path=path,
        mime_type=mime_type,
        size_bytes=int(metadata.get("size_bytes") or path.stat().st_size),
        sha256=str(metadata.get("sha256") or ""),
        url=artifact_url(safe_conversation, safe_category, safe_artifact_id),
        expires_at=float(expires_at) if isinstance(expires_at, (int, float)) else None,
    )


def delete_artifact(
    *,
    category: str,
    conversation_id: str,
    artifact_id: str,
    root: str | Path | None = None,
) -> None:
    storage_dir = artifact_root(root) / safe_segment(category) / safe_segment(conversation_id)
    safe_artifact_id = safe_segment(artifact_id, fallback="")
    if not safe_artifact_id:
        return
    for path in (storage_dir / safe_artifact_id, storage_dir / f"{safe_artifact_id}.json"):
        with suppress(FileNotFoundError):
            path.unlink()


def delete_artifact_tree(
    *,
    category: str,
    conversation_id: str,
    root: str | Path | None = None,
) -> None:
    path = artifact_root(root) / safe_segment(category) / safe_segment(conversation_id)
    shutil.rmtree(path, ignore_errors=True)


def _base_mime_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()
