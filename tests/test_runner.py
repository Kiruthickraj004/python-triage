import sys
from triage.runner import run_test_command


def test_runner_successful_command():
    cmd = f'"{sys.executable}" -c "print(\'test output passed\'); exit(0)"'
    exit_code, output = run_test_command(cmd)

    assert exit_code == 0
    assert "test output passed" in output


def test_runner_failing_command():
    cmd = f'"{sys.executable}" -c "print(\'test output failed\'); exit(1)"'
    exit_code, output = run_test_command(cmd)

    assert exit_code == 1
    assert "test output failed" in output
