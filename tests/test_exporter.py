import json
from pathlib import Path
from triage.parser import parse_test_output
from triage.grouper import pre_group_failures
from triage.llm.validator import TriageValidator
from triage.exporter import export_json, export_markdown, export_fix_script

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def read_fixture(filename: str) -> str:
    path = FIXTURES_DIR / filename
    return path.read_text(encoding="utf-8")


def get_sample_triage_result():
    content = read_fixture("pytest_django_db_cascade.txt")
    run = parse_test_output(content)
    groups = pre_group_failures(run.failures)
    validator = TriageValidator(groups)
    result = validator.fallback_to_deterministic("test")
    return result, run


def test_export_json():
    result, run = get_sample_triage_result()
    json_str = export_json(result, run)

    data = json.loads(json_str)
    assert data["total_failures"] == 15
    assert data["framework"] == "pytest"
    assert len(data["groups"]) == 1
    assert data["groups"][0]["count"] == 15


def test_export_markdown():
    result, run = get_sample_triage_result()
    md_str = export_markdown(result, run)

    assert "## ⚡ Test Failure Triage Report" in md_str
    assert "| Group | Priority | Root Cause | Failures | Confidence |" in md_str
    assert "Database Connection Refused" in md_str
    assert "<details>" in md_str
    assert "<summary><b>Affected Tests (15)</b></summary>" in md_str


def test_export_fix_script(tmp_path):
    result, run = get_sample_triage_result()

    # PowerShell script export
    ps1_target = tmp_path / "fix.ps1"
    generated_path = export_fix_script(result, str(ps1_target))
    assert Path(generated_path).exists()
    content = Path(generated_path).read_text(encoding="utf-8")
    assert "# PowerShell Test Fix Automation Script" in content
    assert "docker compose up -d postgres" in content or "PostgreSQL" in content

    # Bash script export
    sh_target = tmp_path / "fix.sh"
    generated_sh = export_fix_script(result, str(sh_target))
    assert Path(generated_sh).exists()
    sh_content = Path(generated_sh).read_text(encoding="utf-8")
    assert "#!/usr/bin/env bash" in sh_content
