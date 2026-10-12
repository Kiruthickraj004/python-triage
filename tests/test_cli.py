from pathlib import Path
from unittest.mock import patch
import sys
import pytest
from triage.cli import main

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_cli_analyze_fixture_file():
    fixture_path = str(FIXTURES_DIR / "pytest_django_db_cascade.txt")
    test_args = ["triage", "analyze", fixture_path, "--deterministic"]

    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1


def test_cli_analyze_json_format(capsys):
    fixture_path = str(FIXTURES_DIR / "pytest_missing_dependency.txt")
    test_args = ["triage", "analyze", fixture_path, "--format", "json", "--deterministic"]

    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert '"total_failures": 5' in captured.out
    assert '"root_cause"' in captured.out


def test_cli_analyze_markdown_format(capsys):
    fixture_path = str(FIXTURES_DIR / "pytest_missing_dependency.txt")
    test_args = ["triage", "analyze", fixture_path, "--format", "markdown", "--deterministic"]

    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "## ⚡ Test Failure Triage Report" in captured.out
    assert "Missing Dependency" in captured.out


def test_cli_export_script(tmp_path):
    fixture_path = str(FIXTURES_DIR / "pytest_missing_dependency.txt")
    script_target = str(tmp_path / "fix_missing.ps1")
    test_args = ["triage", "analyze", fixture_path, "--export-script", script_target, "--deterministic"]

    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    assert Path(script_target).exists()
    content = Path(script_target).read_text(encoding="utf-8")
    assert "pip install stripe" in content


def test_cli_missing_file():
    test_args = ["triage", "analyze", "non_existent_file.txt"]

    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1


def test_cli_run_django_fatal_crash_triaged(capsys):
    crash_output = """
Running: python manage.py test carts
Creating test database for alias 'default'...
Traceback (most recent call last):
  File "C:\\backend\\manage.py", line 22, in <module>
    main()
django.db.utils.OperationalError: connection failed: connection to server at "127.0.0.1", port 5432 failed: FATAL:  password authentication failed for user "postgres"
"""
    test_args = ["triage", "run", "python manage.py test carts", "--deterministic"]

    with patch("triage.cli.run_test_command", return_value=(1, crash_output)):
        with patch.object(sys, "argv", test_args):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Database Connection Refused" in captured.out
    assert "docker" in captured.out
    assert "Suggested Fix:" in captured.out


def test_cli_execute_pipeline_nonzero_exit_hint():
    from triage.cli import execute_triage_pipeline
    ret = execute_triage_pipeline("No tests found or empty", exit_code_hint=2)
    assert ret == 2

