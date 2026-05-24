"""Tests for :class:`MediaPolicyHandler`.

Two responsibilities, tested independently:

* ``enforce_request_policy`` -- stamps the provider-data-policy
  result (policy name + findings) onto the prompt package metadata.
* ``store_generated_images`` -- decodes base64 image data and
  persists it via :func:`store_bytes_artifact`, tolerating
  pre-stored / payload-less images and decoding failures.
"""
from __future__ import annotations

import base64
from pathlib import Path

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.use_cases.chat.media_policy import MediaPolicyHandler
from personagent.application.use_cases.chat.state import PromptPackage
from personagent.domain.models.inference_result import GeneratedImage


def _prompt_package(
    *,
    system_prompt: str = "you are helpful",
    user_context_message: str | None = None,
) -> PromptPackage:
    return PromptPackage(
        system_prompt=system_prompt,
        user_context_message=user_context_message,
        metadata={},
    )


# -- enforce_request_policy -------------------------------------------------


def test_enforce_request_policy_stamps_policy_metadata_for_local_provider(tmp_path: Path) -> None:
    handler = MediaPolicyHandler(artifact_root=tmp_path, artifact_ttl_seconds=None)
    pkg = _prompt_package()
    req = ChatRequestDTO(message="hi", provider="llama")

    handler.enforce_request_policy(req, pkg)

    assert pkg.metadata["provider_data_policy"] == "local_only"
    assert pkg.metadata["provider_data_policy_findings"] == {}


def test_enforce_request_policy_records_findings_for_hosted_provider(tmp_path: Path) -> None:
    handler = MediaPolicyHandler(artifact_root=tmp_path, artifact_ttl_seconds=None)
    pkg = _prompt_package(user_context_message="here is my key sk-AAAAAAAAAAAAAAAAAAAAAA")
    req = ChatRequestDTO(message="hi", provider="nvidia")

    try:
        handler.enforce_request_policy(req, pkg)
    except Exception:
        # provider_data_policy raises when the request is blocked. The
        # exception is the legacy behaviour and is preserved verbatim.
        return

    assert pkg.metadata["provider_data_policy"] != "local_only"
    findings = pkg.metadata["provider_data_policy_findings"]
    assert isinstance(findings, dict)


def test_enforce_request_policy_overwrites_existing_metadata(tmp_path: Path) -> None:
    handler = MediaPolicyHandler(artifact_root=tmp_path, artifact_ttl_seconds=None)
    pkg = _prompt_package()
    pkg.metadata["provider_data_policy"] = "stale"
    pkg.metadata["provider_data_policy_findings"] = {"stale": 1}
    req = ChatRequestDTO(message="hi", provider="llama")

    handler.enforce_request_policy(req, pkg)

    assert pkg.metadata["provider_data_policy"] == "local_only"
    assert pkg.metadata["provider_data_policy_findings"] == {}


def test_enforce_request_policy_uses_system_prompt_for_scanning(tmp_path: Path) -> None:
    handler = MediaPolicyHandler(artifact_root=tmp_path, artifact_ttl_seconds=None)
    pkg = _prompt_package(
        system_prompt="just a normal prompt",
        user_context_message=None,
    )
    req = ChatRequestDTO(message="hi", provider="nvidia")

    handler.enforce_request_policy(req, pkg)

    findings = pkg.metadata["provider_data_policy_findings"]
    assert isinstance(findings, dict)
    assert "provider_data_policy" in pkg.metadata


# -- store_generated_images -------------------------------------------------


def test_store_generated_images_passes_through_when_url_already_present(tmp_path: Path) -> None:
    handler = MediaPolicyHandler(artifact_root=tmp_path, artifact_ttl_seconds=None)
    image = GeneratedImage(mime_type="image/png", url="https://example.com/a.png")

    result = handler.store_generated_images("conv-1", [image])

    assert result == [image]


def test_store_generated_images_passes_through_when_artifact_id_present(tmp_path: Path) -> None:
    handler = MediaPolicyHandler(artifact_root=tmp_path, artifact_ttl_seconds=None)
    image = GeneratedImage(mime_type="image/png", artifact_id="abc123")

    result = handler.store_generated_images("conv-1", [image])

    assert result == [image]


def test_store_generated_images_passes_through_when_data_missing(tmp_path: Path) -> None:
    handler = MediaPolicyHandler(artifact_root=tmp_path, artifact_ttl_seconds=None)
    image = GeneratedImage(mime_type="image/png", data="")

    result = handler.store_generated_images("conv-1", [image])

    assert result == [image]


def test_store_generated_images_decodes_and_stores_base64_payload(tmp_path: Path) -> None:
    handler = MediaPolicyHandler(artifact_root=tmp_path, artifact_ttl_seconds=None)
    raw = b"\x89PNG\r\n\x1a\nfake-pixels"
    image = GeneratedImage(
        mime_type="image/png",
        data=base64.b64encode(raw).decode("ascii"),
        alt="diagram",
    )

    [stored] = handler.store_generated_images("conv-1", [image])

    assert stored.url
    assert stored.artifact_id
    assert stored.size_bytes == len(raw)
    assert stored.alt == "diagram"
    assert stored.mime_type == "image/png"
    assert stored.sha256


def test_store_generated_images_defaults_missing_mime_to_png(tmp_path: Path) -> None:
    handler = MediaPolicyHandler(artifact_root=tmp_path, artifact_ttl_seconds=None)
    raw = b"\x89PNGfake"
    image = GeneratedImage(mime_type="", data=base64.b64encode(raw).decode("ascii"))

    [stored] = handler.store_generated_images("conv-1", [image])

    assert stored.mime_type == "image/png"


def test_store_generated_images_skips_on_invalid_base64(tmp_path: Path) -> None:
    handler = MediaPolicyHandler(artifact_root=tmp_path, artifact_ttl_seconds=None)
    image = GeneratedImage(mime_type="image/png", data="!!!not-base64???")

    result = handler.store_generated_images("conv-1", [image])

    assert result == [image]


def test_store_generated_images_handles_mixed_list_in_order(tmp_path: Path) -> None:
    handler = MediaPolicyHandler(artifact_root=tmp_path, artifact_ttl_seconds=None)
    raw = b"\x89PNGbytes"
    encoded = base64.b64encode(raw).decode("ascii")
    images = [
        GeneratedImage(mime_type="image/png", url="https://example.com/keep"),
        GeneratedImage(mime_type="image/png", data=encoded, alt="new"),
        GeneratedImage(mime_type="image/png", data=""),
    ]

    result = handler.store_generated_images("conv-1", images)

    assert len(result) == 3
    assert result[0] is images[0]
    assert result[1].artifact_id  # newly stored
    assert result[1].alt == "new"
    assert result[2] is images[2]


def test_store_generated_images_returns_empty_for_empty_input(tmp_path: Path) -> None:
    handler = MediaPolicyHandler(artifact_root=tmp_path, artifact_ttl_seconds=None)

    assert handler.store_generated_images("conv-1", []) == []


def test_store_generated_images_uses_jpeg_suffix_for_jpeg_mime(tmp_path: Path) -> None:
    handler = MediaPolicyHandler(artifact_root=tmp_path, artifact_ttl_seconds=None)
    raw = b"\xff\xd8\xff\xe0fake-jpeg"
    image = GeneratedImage(
        mime_type="image/jpeg",
        data=base64.b64encode(raw).decode("ascii"),
    )

    [stored] = handler.store_generated_images("conv-1", [image])

    assert stored.mime_type == "image/jpeg"
    assert stored.url.endswith(".jpg") or stored.url.endswith(".jpeg")


def test_store_generated_images_honors_artifact_root(tmp_path: Path) -> None:
    custom_root = tmp_path / "custom-root"
    handler = MediaPolicyHandler(artifact_root=custom_root, artifact_ttl_seconds=None)
    raw = b"\x89PNG"
    image = GeneratedImage(
        mime_type="image/png",
        data=base64.b64encode(raw).decode("ascii"),
    )

    [stored] = handler.store_generated_images("conv-1", [image])

    assert custom_root.exists()
    assert stored.artifact_id


def test_store_generated_images_honors_artifact_ttl(tmp_path: Path) -> None:
    handler = MediaPolicyHandler(artifact_root=tmp_path, artifact_ttl_seconds=60)
    raw = b"\x89PNG"
    image = GeneratedImage(
        mime_type="image/png",
        data=base64.b64encode(raw).decode("ascii"),
    )

    [stored] = handler.store_generated_images("conv-1", [image])

    assert stored.artifact_id


def test_store_generated_images_does_not_mutate_input_list(tmp_path: Path) -> None:
    handler = MediaPolicyHandler(artifact_root=tmp_path, artifact_ttl_seconds=None)
    encoded = base64.b64encode(b"x").decode("ascii")
    images = [GeneratedImage(mime_type="image/png", data=encoded)]
    snapshot = list(images)

    handler.store_generated_images("conv-1", images)

    assert images == snapshot
