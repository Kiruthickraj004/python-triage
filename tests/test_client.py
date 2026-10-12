import os
from unittest.mock import patch, MagicMock
from pathlib import Path

from triage.parser import parse_test_output
from triage.grouper import pre_group_failures
from triage.llm.client import LLMClient, MockProvider, GroqProvider, OpenAIProvider, GeminiProvider

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def read_fixture(filename: str) -> str:
    path = FIXTURES_DIR / filename
    return path.read_text(encoding="utf-8")


def test_mock_provider_client():
    content = read_fixture("pytest_missing_dependency.txt")
    run = parse_test_output(content)
    groups = pre_group_failures(run.failures)

    client = LLMClient(provider=MockProvider())
    result = client.triage(groups, framework="pytest")

    assert result.is_fallback is False
    assert result.provider == "mock"
    assert len(result.groups) >= 1
    # Check that tests are accounted for
    total_triaged = sum(g.count for g in result.groups)
    assert total_triaged == 5


def test_client_handles_network_failure_with_fallback():
    content = read_fixture("pytest_django_db_cascade.txt")
    run = parse_test_output(content)
    groups = pre_group_failures(run.failures)

    # Provider that raises exception
    failing_provider = MagicMock()
    failing_provider.name = "failing_api"
    failing_provider.complete.side_effect = TimeoutError("Connection to API timed out after 8s")

    client = LLMClient(provider=failing_provider)
    result = client.triage(groups, framework="pytest")

    assert result.is_fallback is True
    assert result.provider == "deterministic"
    assert any("failing_api request failed" in w for w in result.validation_warnings)
    assert len(result.groups) == 1
    assert result.groups[0].count == 15


def test_client_provider_auto_detection():
    # When GROQ_API_KEY is present
    with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test123"}, clear=True):
        client = LLMClient()
        assert isinstance(client.provider, GroqProvider)

    # When OPENAI_API_KEY is present
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test123"}, clear=True):
        client = LLMClient()
        assert isinstance(client.provider, OpenAIProvider)

    # When GEMINI_API_KEY is present
    with patch.dict(os.environ, {"GEMINI_API_KEY": "ai-test123"}, clear=True):
        client = LLMClient()
        assert isinstance(client.provider, GeminiProvider)
