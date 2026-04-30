import pytest

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.security.provider_data_policy import enforce_provider_data_policy
from personagent.domain.exceptions import InvalidRequestError


def test_hosted_provider_blocks_secret_like_prompt_context() -> None:
    request = ChatRequestDTO(
        message="Use this only for setup.",
        provider="nvidia",
        model="hosted-model",
    )

    with pytest.raises(InvalidRequestError) as exc_info:
        enforce_provider_data_policy(
            request=request,
            system_prompt="NVIDIA_API_KEY='nvapi-abcdefghijklmnopqrstuvwxyz123456'",
            user_context_message=None,
        )

    assert exc_info.value.code == "provider.data_policy_blocked"
    assert exc_info.value.safe_for_model is False


def test_local_provider_allows_secret_like_context() -> None:
    request = ChatRequestDTO(
        message="Local-only setup.",
        provider="llama",
        model="local-model",
    )

    result = enforce_provider_data_policy(
        request=request,
        system_prompt="NVIDIA_API_KEY='nvapi-abcdefghijklmnopqrstuvwxyz123456'",
        user_context_message=None,
    )

    assert result.policy == "local_only"
    assert result.blocked is False
