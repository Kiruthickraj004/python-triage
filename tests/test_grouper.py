from pathlib import Path
from triage.parser import parse_test_output
from triage.grouper import pre_group_failures, FailureGrouper

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def read_fixture(filename: str) -> str:
    path = FIXTURES_DIR / filename
    return path.read_text(encoding="utf-8")


def test_group_empty():
    groups = pre_group_failures([])
    assert groups == []


def test_group_db_cascade():
    content = read_fixture("pytest_django_db_cascade.txt")
    run = parse_test_output(content)
    assert len(run.failures) == 15

    groups = pre_group_failures(run.failures)
    # All 15 should be collapsed into 1 single high-priority root-cause group
    assert len(groups) == 1

    group = groups[0]
    assert group.group_id == 1
    assert group.category == "Database Connection Refused"
    assert group.count == 15
    assert group.priority == "HIGH"
    assert group.confidence >= 0.95
    assert "docker compose up -d postgres" in group.suggested_fix or "PostgreSQL" in group.suggested_fix

    # Check affected files: should span orders, users, products, cart
    assert len(group.affected_files) >= 4
    assert any("orders/" in f for f in group.affected_files)
    assert any("users/" in f for f in group.affected_files)
    assert any("products/" in f for f in group.affected_files)
    assert any("cart/" in f for f in group.affected_files)

    # Representative traceback should be non-empty and contain the connection refused error
    assert "OperationalError" in group.representative_traceback
    assert "5432" in group.representative_traceback


def test_group_missing_dependency():
    content = read_fixture("pytest_missing_dependency.txt")
    run = parse_test_output(content)
    assert len(run.failures) == 5

    groups = pre_group_failures(run.failures)
    assert len(groups) == 1

    group = groups[0]
    assert "stripe" in group.category.lower()
    assert group.count == 5
    assert group.priority == "HIGH"
    assert group.confidence == 1.0
    assert "pip install stripe" in group.suggested_fix
    assert "import stripe" in group.representative_traceback


def test_group_drf_status_mismatch():
    content = read_fixture("pytest_drf_status_mismatch.txt")
    run = parse_test_output(content)
    assert len(run.failures) == 4

    groups = pre_group_failures(run.failures)
    # Should group into 500 errors and auth/permission errors (401/403)
    categories = [g.category for g in groups]
    assert any("500" in cat for cat in categories)
    assert any("Authentication" in cat or "40" in cat for cat in categories)

    total_grouped = sum(g.count for g in groups)
    assert total_grouped == 4


def test_group_mixed_35_failures():
    content = read_fixture("pytest_mixed_35_failures.txt")
    run = parse_test_output(content)
    assert len(run.failures) == 35

    groups = pre_group_failures(run.failures)

    # 35 failures should be clustered into exactly 4 distinct root cause groups:
    # 1. DB connection (18 failures)
    # 2. Server 500 cascade (7 failures)
    # 3. Missing dependency stripe (5 failures)
    # 4. Auth/Permission 401/403 (5 failures)
    assert len(groups) == 4

    # Crucial property: Exact conservation of failures (no hallucinations, no dropped tests)
    total_failures_in_groups = sum(g.count for g in groups)
    assert total_failures_in_groups == 35

    # Group 1 must be the largest cascade (18 DB failures)
    g1 = groups[0]
    assert g1.category == "Database Connection Refused"
    assert g1.count == 18
    assert g1.priority == "HIGH"

    # Verify each group has a representative traceback
    for g in groups:
        assert isinstance(g.representative_traceback, str)
        assert len(g.affected_files) >= 1
        assert g.suggested_fix != ""

    # Token savings verification:
    # Instead of 35 tracebacks, an LLM call will only receive 4 representative tracebacks!
    assert len(groups) == 4


def test_group_django_manage_py():
    content = read_fixture("django_manage_py_test.txt")
    run = parse_test_output(content)
    assert len(run.failures) == 3

    groups = pre_group_failures(run.failures)
    assert len(groups) == 3  # DB error, 500 error, 403 error

    categories = [g.category for g in groups]
    assert any("Database Connection" in c for c in categories)
    assert any("500" in c for c in categories)
    assert any("403" in c or "Permission" in c for c in categories)

    assert sum(g.count for g in groups) == 3
