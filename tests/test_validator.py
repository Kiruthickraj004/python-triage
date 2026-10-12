import json
from pathlib import Path
from triage.parser import parse_test_output
from triage.grouper import pre_group_failures
from triage.llm.validator import TriageValidator

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def read_fixture(filename: str) -> str:
    path = FIXTURES_DIR / filename
    return path.read_text(encoding="utf-8")


def test_validator_perfect_match():
    content = read_fixture("pytest_missing_dependency.txt")
    run = parse_test_output(content)
    groups = pre_group_failures(run.failures)
    validator = TriageValidator(groups)

    mock_llm_json = {
        "summary": "5 payment tests failed due to missing stripe package.",
        "groups": [
            {
                "group_id": 1,
                "root_cause": "Missing Dependency 'stripe'",
                "explanation": "Payment modules require the stripe SDK which is not installed.",
                "suggested_fix": "pip install stripe",
                "priority": "HIGH",
                "confidence": 0.99,
                "affected_tests": [f.test_id for f in run.failures],
            }
        ],
    }

    result = validator.validate_and_repair(mock_llm_json, provider="test")
    assert result.is_fallback is False
    assert len(result.validation_warnings) == 0
    assert len(result.groups) == 1
    assert result.groups[0].count == 5
    assert set(result.groups[0].affected_tests) == validator.ground_truth_test_ids


def test_validator_markdown_fence_cleaning():
    content = read_fixture("pytest_missing_dependency.txt")
    run = parse_test_output(content)
    groups = pre_group_failures(run.failures)
    validator = TriageValidator(groups)

    raw_markdown = f"""
Here is the triage output:
```json
{{
  "summary": "Missing stripe dependency.",
  "groups": [
    {{
      "group_id": 1,
      "root_cause": "Missing stripe",
      "explanation": "Stripe is not installed.",
      "suggested_fix": "pip install stripe",
      "priority": "HIGH",
      "confidence": 0.95,
      "affected_tests": {[f.test_id for f in run.failures]}
    }}
  ]
}}
```
Hope this helps!
""".replace("'", '"')

    result = validator.validate_and_repair(raw_markdown, provider="test")
    assert result.is_fallback is False
    assert len(result.groups) == 1
    assert result.groups[0].count == 5


def test_validator_auto_repair_missing_tests():
    content = read_fixture("pytest_missing_dependency.txt")
    run = parse_test_output(content)
    groups = pre_group_failures(run.failures)
    validator = TriageValidator(groups)

    # Simulate LLM omitting 2 out of 5 tests
    provided_tests = [run.failures[0].test_id, run.failures[1].test_id, run.failures[2].test_id]
    mock_llm_json = {
        "summary": "Some payment tests failed.",
        "groups": [
            {
                "group_id": 1,
                "root_cause": "Missing Dependency 'stripe'",
                "explanation": "Missing stripe",
                "suggested_fix": "pip install stripe",
                "priority": "HIGH",
                "confidence": 0.99,
                "affected_tests": provided_tests,  # only 3 tests!
            }
        ],
    }

    result = validator.validate_and_repair(mock_llm_json, provider="test")
    assert result.is_fallback is False
    # Check warning emitted
    assert any("omitted 2 tests" in w for w in result.validation_warnings)
    # INVARIANT: Set of all output tests MUST equal ground truth (5 tests)
    all_output_tests = set(result.groups[0].affected_tests)
    assert all_output_tests == validator.ground_truth_test_ids
    assert result.groups[0].count == 5


def test_validator_strips_hallucinated_tests():
    content = read_fixture("pytest_missing_dependency.txt")
    run = parse_test_output(content)
    groups = pre_group_failures(run.failures)
    validator = TriageValidator(groups)

    # Simulate LLM hallucinating tests that never failed
    all_tests = [f.test_id for f in run.failures]
    all_tests.append("tests/fake_test.py::test_imaginary_bug")
    all_tests.append("tests/ghost.py::test_hallucination")

    mock_llm_json = {
        "summary": "Failures triaged",
        "groups": [
            {
                "group_id": 1,
                "root_cause": "Missing stripe",
                "explanation": "No stripe",
                "suggested_fix": "pip install stripe",
                "priority": "HIGH",
                "confidence": 0.95,
                "affected_tests": all_tests,
            }
        ],
    }

    result = validator.validate_and_repair(mock_llm_json, provider="test")
    assert result.is_fallback is False
    assert any("Removed hallucinated test ID" in w for w in result.validation_warnings)
    assert "tests/fake_test.py::test_imaginary_bug" not in result.groups[0].affected_tests
    assert result.groups[0].count == 5


def test_validator_fallback_on_invalid_json():
    content = read_fixture("pytest_django_db_cascade.txt")
    run = parse_test_output(content)
    groups = pre_group_failures(run.failures)
    validator = TriageValidator(groups)

    corrupted_json = "I am an AI and here is your result: { invalid json without brackets"

    result = validator.validate_and_repair(corrupted_json, provider="test")
    assert result.is_fallback is True
    assert result.provider == "deterministic"
    assert len(result.groups) == 1
    assert result.groups[0].count == 15
    assert result.groups[0].source == "deterministic_fallback"
    assert "docker compose up -d postgres" in result.groups[0].suggested_fix or "PostgreSQL" in result.groups[0].suggested_fix


def test_validator_fallback_on_empty_groups():
    content = read_fixture("pytest_django_db_cascade.txt")
    run = parse_test_output(content)
    groups = pre_group_failures(run.failures)
    validator = TriageValidator(groups)

    mock_llm_json = {"summary": "Nothing here", "groups": []}

    result = validator.validate_and_repair(mock_llm_json, provider="test")
    assert result.is_fallback is True
    assert len(result.groups) == 1
    assert result.groups[0].count == 15
