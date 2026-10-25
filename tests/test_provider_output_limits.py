"""The shared output budget must reach each provider SDK constructor."""

from unittest.mock import patch

import pytest

from tradingagents.llm_clients.azure_client import AzureOpenAIClient
from tradingagents.llm_clients.google_client import GoogleClient
from tradingagents.llm_clients.provider_kwargs import provider_llm_kwargs

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("value", [4096, "4096"])
@pytest.mark.parametrize("provider,client,constructor,key", [
    ("google", GoogleClient, "tradingagents.llm_clients.google_client.NormalizedChatGoogleGenerativeAI", "max_output_tokens"),
    ("azure", AzureOpenAIClient, "tradingagents.llm_clients.azure_client.NormalizedAzureChatOpenAI", "max_tokens"),
])
def test_shared_output_limit_reaches_sdk(value, provider, client, constructor, key):
    kwargs = provider_llm_kwargs({"llm_provider": provider, "llm_max_tokens": value})
    with patch(constructor) as sdk:
        client("test-model", **kwargs).get_llm()
    assert sdk.call_args.kwargs[key] == 4096


def test_google_explicit_native_limit_takes_precedence_over_alias():
    with patch("tradingagents.llm_clients.google_client.NormalizedChatGoogleGenerativeAI") as sdk:
        GoogleClient("test-model", max_tokens=4096, max_output_tokens=2048).get_llm()
    assert sdk.call_args.kwargs["max_output_tokens"] == 2048
