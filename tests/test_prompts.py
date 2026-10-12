from pathlib import Path
from triage.parser import parse_test_output
from triage.grouper import pre_group_failures
from triage.llm.prompts import build_triage_prompt, TRIAGE_JSON_SCHEMA

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def read_fixture(filename: str) -> str:
    path = FIXTURES_DIR / filename
    return path.read_text(encoding="utf-8")


def test_build_triage_prompt_structure():
    content = read_fixture("pytest_missing_dependency.txt")
    run = parse_test_output(content)
    groups = pre_group_failures(run.failures)

    system_prompt, user_prompt = build_triage_prompt(groups, framework="pytest")

    # Check system prompt instructions
    assert "Principal Software Engineer" in system_prompt
    assert "CONSERVATION OF TESTS" in system_prompt

    # Check user prompt contents
    assert "Test Framework: PYTEST" in user_prompt
    assert "Total Failing Tests: 5" in user_prompt
    assert "Pre-grouped Failure Clusters: 1" in user_prompt
    assert "payments/tests/test_stripe.py::test_stripe_card_charge" in user_prompt
    assert "import stripe" in user_prompt  # Representative traceback included
    assert "Output JSON Schema requirements:" in user_prompt


def test_build_triage_prompt_token_optimization():
    content = read_fixture("pytest_mixed_35_failures.txt")
    run = parse_test_output(content)
    groups = pre_group_failures(run.failures)

    system_prompt, user_prompt = build_triage_prompt(groups, framework="pytest")

    # The prompt should be compact (< 4,000 characters for 35 failures!)
    # compared to 35 raw full tracebacks which would be 20,000+ characters!
    assert len(user_prompt) < 6000
    assert "Cluster #1" in user_prompt
    assert "Cluster #2" in user_prompt
    assert "Cluster #3" in user_prompt
    assert "Cluster #4" in user_prompt
