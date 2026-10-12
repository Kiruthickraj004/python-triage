import os
import time
import json
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional, Tuple

from triage.models import PreGroup
from triage.llm.prompts import build_triage_prompt
from triage.llm.validator import TriageValidator, TriageResult


class BaseProvider:
    """Base interface for LLM providers."""
    name: str = "base"

    def is_configured(self) -> bool:
        return True

    def complete(self, system_prompt: str, user_prompt: str, timeout: float = 8.0) -> str:
        raise NotImplementedError


class GroqProvider(BaseProvider):
    """Ultra-low-latency provider via Groq."""
    name = "groq"

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile"):
        self.api_key = api_key
        self.model = model
        self.endpoint = "https://api.groq.com/openai/v1/chat/completions"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def complete(self, system_prompt: str, user_prompt: str, timeout: float = 8.0) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "triage-cli/0.1.0",
        }
        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]


class OpenAIProvider(BaseProvider):
    """OpenAI API provider."""
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.model = model
        self.endpoint = "https://api.openai.com/v1/chat/completions"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def complete(self, system_prompt: str, user_prompt: str, timeout: float = 8.0) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "triage-cli/0.1.0",
        }
        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]


class GeminiProvider(BaseProvider):
    """Google Gemini API provider."""
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model = model
        self.endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def complete(self, system_prompt: str, user_prompt: str, timeout: float = 8.0) -> str:
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {"response_mime_type": "application/json", "temperature": 0.1},
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "triage-cli/0.1.0",
        }
        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"]


class MockProvider(BaseProvider):
    """Mock LLM provider for unit tests, offline mode, and local demonstrations."""
    name = "mock"

    def __init__(self, response_data: Optional[Dict[str, Any]] = None):
        self.response_data = response_data

    def is_configured(self) -> bool:
        return True

    def complete(self, system_prompt: str, user_prompt: str, timeout: float = 8.0) -> str:
        if self.response_data:
            return json.dumps(self.response_data)

        # Generate sensible mock output based on standard patterns in prompt
        groups = []
        if "Missing Dependency" in user_prompt or "stripe" in user_prompt:
            groups.append({
                "group_id": 1,
                "root_cause": "Missing Python Package 'stripe'",
                "explanation": "Payment endpoints failed because the 'stripe' library is not installed in the virtual environment.",
                "suggested_fix": "pip install stripe",
                "priority": "HIGH",
                "confidence": 0.99,
                "affected_tests": [
                    "payments/tests/test_stripe.py::test_stripe_charge",
                    "payments/tests/test_stripe.py::test_stripe_refund",
                ],
            })
        else:
            groups.append({
                "group_id": 1,
                "root_cause": "PostgreSQL Service Unreachable",
                "explanation": "Multiple test modules failed trying to establish TCP connections on port 5432.",
                "suggested_fix": "docker compose up -d postgres",
                "priority": "HIGH",
                "confidence": 0.98,
                "affected_tests": [
                    "orders/tests/test_orders.py::test_create_order",
                ],
            })

        return json.dumps({
            "summary": "Mock LLM analyzed test failure clusters.",
            "groups": groups,
        })


from pathlib import Path


def load_dotenv_if_present(env_path: str = ".env") -> None:
    """
    Read key-value pairs from .env if present and set into os.environ.
    Checks:
    1. Current working directory .env (local project config)
    2. ~/.triage/.env (global user config)
    """
    candidates = [Path(env_path), Path.home() / ".triage" / ".env"]
    for path in candidates:
        if path.is_file():
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v
            except Exception:
                pass


class LLMClient:
    """
    Client orchestrating prompt generation, provider requests,
    latency tracking, and guardrail validation.
    """

    def __init__(self, provider: Optional[BaseProvider] = None, timeout: float = 8.0):
        # If provider is explicitly passed (even None), use it; otherwise detect
        self.provider = provider if provider is not None else self._detect_provider()
        self.timeout = timeout

    def _detect_provider(self) -> Optional[BaseProvider]:
        """Automatically select available provider from environment variables or .env."""
        load_dotenv_if_present()

        groq_key = os.environ.get("GROQ_API_KEY")
        if groq_key:
            return GroqProvider(groq_key)

        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key:
            return OpenAIProvider(openai_key)

        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key:
            return GeminiProvider(gemini_key)

        return None

    def triage(self, pre_groups: List[PreGroup], framework: str = "pytest") -> TriageResult:
        """
        Execute full compound AI triage pipeline:
        pre-groups -> prompt -> LLM call -> validator repair -> TriageResult
        """
        validator = TriageValidator(pre_groups)

        # If no failures
        if not pre_groups:
            return TriageResult(
                summary="No failures detected.",
                groups=[],
                is_fallback=False,
                provider="none",
                latency_ms=0.0,
            )

        if self.provider is None:
            return validator.fallback_to_deterministic("No LLM API key configured (set GROQ_API_KEY or OPENAI_API_KEY)")

        # Check if provider is configured
        is_configured = getattr(self.provider, "is_configured", lambda: True)()
        if not is_configured:
            return validator.fallback_to_deterministic(f"No API key configured for {self.provider.name}")

        system_prompt, user_prompt = build_triage_prompt(pre_groups, framework=framework)

        start_time = time.perf_counter()
        try:
            raw_response = self.provider.complete(system_prompt, user_prompt, timeout=self.timeout)
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return validator.validate_and_repair(
                raw_response=raw_response,
                provider=self.provider.name,
                latency_ms=latency_ms,
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            fallback = validator.fallback_to_deterministic(f"{self.provider.name} request failed: {e}")
            fallback.latency_ms = latency_ms
            return fallback


def get_llm_client(provider_name: Optional[str] = None) -> LLMClient:
    """Factory helper to obtain configured LLM client."""
    if provider_name == "mock":
        return LLMClient(MockProvider())
    return LLMClient()
