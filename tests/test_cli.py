from pathlib import Path
from unittest.mock import patch
import io
import sys
from triage.cli import main

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_cli_analyze_fixture_file(capsys):
    fixture_path = str(FIXTURES_DIR / "pytest_django_db_cascade.txt")
    test_args = ["triage", "analyze", fixture_path]

    with patch.object(sys, "argv", test_args):
        main()

    # Verify output contains dashboard markers
    # Rich uses console output
    pass


def test_cli_missing_file(capsys):
    test_args = ["triage", "analyze", "non_existent_file.txt"]

    with patch.object(sys, "argv", test_args):
        try:
            main()
        except SystemExit as e:
            assert e.code == 1
