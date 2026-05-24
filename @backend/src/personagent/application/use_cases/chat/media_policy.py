"""Provider data policy + generated-image artifact handling.

Two small post-processing steps that historically lived as private
methods on :class:`ChatCompletionUseCase`:

* ``_enforce_provider_data_policy`` -- runs the security
  :func:`enforce_provider_data_policy` over the request + system
  prompt + user-context message and stamps the result onto the
  prompt package metadata. The chat use case fires this once per
  turn, right before handing the prompt package to the LLM backend.
* ``_store_generated_images`` -- when an inference result contains
  inline base64 image data, decode it and persist it via the
  :func:`store_bytes_artifact` infrastructure helper. Images that
  already carry a URL / artifact id (or that have no base64 payload)
  are passed through verbatim. Decoding failures are tolerated and
  the original image is returned unchanged.

Both responsibilities are independent of the streaming/tool loop and
are called from multiple paths (sync execute + streaming turn + per
streaming chunk), so consolidating them in a single
:class:`MediaPolicyHandler` collaborator removes duplication without
changing any side effect.

Backward compatibility: the policy metadata keys
(``provider_data_policy`` and ``provider_data_policy_findings``), the
image decoding / artifact storage behaviour, and the pass-through
rules for images without base64 payloads are preserved verbatim.
"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.security.provider_data_policy import (
    enforce_provider_data_policy,
)
from personagent.application.use_cases.chat.helpers import image_suffix
from personagent.application.use_cases.chat.state import PromptPackage
from personagent.domain.models.inference_result import GeneratedImage
from personagent.infrastructure.artifacts import store_bytes_artifact


class MediaPolicyHandler:
    """Apply provider-data-policy + persist generated images.

    The handler is stateless except for the artifact storage configuration
    captured at construction time.
    """

    def __init__(
        self,
        *,
        artifact_root: Path | None,
        artifact_ttl_seconds: int | None,
    ) -> None:
        self._artifact_root = artifact_root
        self._artifact_ttl_seconds = artifact_ttl_seconds

    def enforce_request_policy(
        self,
        request: ChatRequestDTO,
        prompt_package: PromptPackage,
    ) -> None:
        """Stamp provider-data-policy metadata onto the prompt package."""

        result = enforce_provider_data_policy(
            request=request,
            system_prompt=prompt_package.system_prompt,
            user_context_message=prompt_package.user_context_message,
        )
        prompt_package.metadata["provider_data_policy"] = result.policy
        prompt_package.metadata["provider_data_policy_findings"] = result.findings

    def store_generated_images(
        self,
        conversation_id: str,
        images: list[GeneratedImage],
    ) -> list[GeneratedImage]:
        """Persist inline base64 image payloads as artifacts.

        Images that already have a URL or artifact id, or that have no
        base64 ``data`` payload, are returned unchanged. Decoding
        failures (malformed base64) cause the image to be returned
        unchanged as well -- consistent with the legacy "best effort"
        behaviour.
        """

        stored: list[GeneratedImage] = []
        for image in images:
            if image.url or image.artifact_id or not image.data:
                stored.append(image)
                continue
            try:
                raw = base64.b64decode(image.data, validate=True)
            except (binascii.Error, ValueError):
                stored.append(image)
                continue
            mime_type = image.mime_type or "image/png"
            artifact = store_bytes_artifact(
                category="generated-images",
                conversation_id=conversation_id,
                content=raw,
                suffix=image_suffix(mime_type),
                mime_type=mime_type,
                root=self._artifact_root,
                ttl_seconds=self._artifact_ttl_seconds,
            )
            stored.append(
                GeneratedImage(
                    mime_type=mime_type,
                    alt=image.alt,
                    artifact_id=artifact.artifact_id,
                    url=artifact.url,
                    size_bytes=artifact.size_bytes,
                    sha256=artifact.sha256,
                )
            )
        return stored


__all__ = ["MediaPolicyHandler"]
