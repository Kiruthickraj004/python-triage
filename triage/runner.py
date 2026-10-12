import sys
import subprocess
from typing import Tuple, Optional


def run_test_command(command: str, cwd: Optional[str] = None) -> Tuple[int, str]:
    """
    Execute a test runner command, streaming output in real time to the terminal
    while capturing the full buffer for post-run failure triage.

    Returns:
        (exit_code, full_captured_output)
    """
    captured_lines = []

    try:
        from pathlib import Path
        import os

        # If the command invokes pytest, normalize to current python interpreter for reliability on Windows/virtualenvs
        if command.strip() == "pytest" or command.strip().startswith("pytest "):
            rest = command.strip()[6:]
            command = f'"{sys.executable}" -m pytest {rest}'.strip()

        sub_env = os.environ.copy()
        python_dir = str(Path(sys.executable).parent)
        sub_env["PATH"] = python_dir + os.pathsep + sub_env.get("PATH", "")

        # Use shell=True to support commands like "pytest tests/ -v" or "python manage.py test"
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=cwd,
            env=sub_env,
        )

        # Stream line-by-line in real-time
        if process.stdout:
            for line in iter(process.stdout.readline, ""):
                sys.stdout.write(line)
                sys.stdout.flush()
                captured_lines.append(line)

        process.wait()
        return process.returncode, "".join(captured_lines)

    except KeyboardInterrupt:
        # Cleanly abort child process if user presses Ctrl+C
        try:
            process.terminate()
            process.wait(timeout=2.0)
        except Exception:
            process.kill()
        sys.stdout.write("\n[TRIAGE] Test execution interrupted by user.\n")
        sys.stdout.flush()
        return 130, "".join(captured_lines)
