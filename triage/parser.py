import re
from typing import List, Dict, Tuple, Optional
from triage.models import TestFailure, ParsedRun

# Matches ANSI escape sequences (colors, cursor movements, bold/dim, etc.)
ANSI_ESCAPE_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

# Pytest short test summary info line regex
# Pytest separates status, test_id, and error details with ' - '
# Examples:
# FAILED tests/test_orders.py::test_create_order - AssertionError: expected 201, got 500
# ERROR tests/test_db.py::test_setup - django.db.utils.OperationalError: could not connect to server
# FAILED orders/tests/test_tax.py::test_tax_calc[standard-NY] - AssertionError: assert 108.5 == 108.0
PYTEST_SUMMARY_LINE_RE = re.compile(
    r'^(FAILED|ERROR)\s+(.+?)\s+-\s+(.+)$'
)

# Pytest traceback header regex
# Examples:
# ________________________ test_order_creation_flow ________________________
# ____________________ ERROR at setup of test_setup ____________________
PYTEST_TB_HEADER_RE = re.compile(
    r'^_{3,}\s*(?:ERROR at setup of\s+|ERROR at teardown of\s+)?(.+?)\s*_{3,}$'
)

# Pytest file and line location at the end of traceback
# Example: orders/tests/test_orders.py:28: OperationalError
PYTEST_LOC_RE = re.compile(
    r'^([A-Za-z0-9_\-/\\]+\.py):(\d+):\s*([A-Za-z0-9_.]+)$'
)

# Pytest overall footer summary regex
# Example: ======================== 15 failed, 30 passed in 2.14s =========================
PYTEST_FOOTER_RE = re.compile(
    r'=+\s*(?:(\d+)\s+failed)?(?:[,\s]*(\d+)\s+error(?:s)?)?(?:[,\s]*(\d+)\s+passed)?.*?(?:in\s+([\d\.]+)s)?\s*=+'
)

# Django manage.py test failure header regex
# Example: FAIL: test_create_order (orders.tests.test_views.OrderAPITestCase)
# or ERROR: test_db_connection (users.tests.test_auth.AuthTestCase.test_db_connection)
DJANGO_HEADER_RE = re.compile(
    r'^(FAIL|ERROR):\s*([^\s(]+)\s*\(([^)]+)\)',
    re.MULTILINE
)

# Django manage.py test summary regex
# Example: FAILED (failures=2, errors=1)
DJANGO_SUMMARY_RE = re.compile(
    r'^FAILED\s*\((?:failures=(\d+))?(?:[,\s]*errors=(\d+))?\)',
    re.MULTILINE
)
DJANGO_RAN_RE = re.compile(
    r'^Ran\s+(\d+)\s+tests\s+in\s+([\d\.]+)s',
    re.MULTILINE
)
EXCEPTION_LINE_RE = re.compile(
    r'^\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?:Error|Exception|Failure|Warning|Exit|Interrupt|Fault|Configured)):\s*(.*)$',
    re.MULTILINE
)


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes and clean carriage returns from terminal output."""
    if not text:
        return ""
    clean = ANSI_ESCAPE_RE.sub('', text)
    return clean.replace('\r\n', '\n').replace('\r', '\n')


def parse_error_details(error_str: str) -> Tuple[str, str]:
    """
    Split an error string like 'django.db.utils.OperationalError: could not connect'
    into ('django.db.utils.OperationalError', 'could not connect').
    """
    error_str = error_str.strip()
    if not error_str:
        return "UnknownError", ""

    # Common pattern: ExceptionClass: message
    # Handle dotted modules like django.db.utils.OperationalError
    match = re.match(r'^([A-Za-z_][A-Za-z0-9_\.]*(?:Error|Exception|Failure|Warning|Exit|Interrupt|Fault)?):\s*(.*)$', error_str, re.DOTALL)
    if match:
        err_type = match.group(1).strip()
        err_msg = match.group(2).strip()
        return err_type, err_msg

    # If format is just 'AssertionError' with no colon
    if re.match(r'^[A-Za-z_][A-Za-z0-9_\.]*(?:Error|Exception)$', error_str):
        return error_str, ""

    # Check if there is any colon separating type and message
    if ":" in error_str:
        parts = error_str.split(":", 1)
        potential_type = parts[0].strip()
        if " " not in potential_type:
            return potential_type, parts[1].strip()

    return "AssertionError", error_str


class TestOutputParser:
    """Universal parser for Pytest and Django test outputs."""
    __test__ = False  # Prevent pytest from treating this helper class as a test suite

    def __init__(self, raw_output: str):
        self.raw_output = raw_output
        self.clean_text = strip_ansi(raw_output)
        self.lines = self.clean_text.splitlines()

    def detect_framework(self) -> str:
        """Detect whether the output is from pytest or Django manage.py test."""
        clean = self.clean_text
        if "=== test session starts ===" in clean or "short test summary info" in clean or "collected " in clean:
            return "pytest"
        if "Ran " in clean and ("FAILED" in clean or "OK" in clean):
            return "django"
        if re.search(r'^(?:FAIL|ERROR):\s*\S+\s*\(', clean, re.MULTILINE):
            return "django"
        if "Creating test database" in clean or "Destroying test database" in clean or re.search(r'Found \d+ test\(s\)', clean):
            return "django"
        if "manage.py" in clean:
            return "django"
        if re.search(r'^(?:FAILED|ERROR)\s+[^\s\-]+::', clean, re.MULTILINE):
            return "pytest"
        if "django" in clean.lower():
            return "django"
        return "pytest"  # Default to pytest

    def parse(self) -> ParsedRun:
        """Parse the test output into structured test failures and run metadata."""
        framework = self.detect_framework()
        if framework == "django":
            run = self._parse_django()
        else:
            run = self._parse_pytest()

        if not run.failures and ("Traceback (most recent call last):" in self.clean_text or EXCEPTION_LINE_RE.search(self.clean_text)):
            tb_failures = self._extract_unhandled_tracebacks(framework=framework)
            if tb_failures:
                run.failures = tb_failures
                run.total_errors = len(tb_failures)

        return run

    def _parse_pytest_traceback_blocks(self) -> Dict[str, Tuple[str, Optional[str], Optional[int]]]:
        """
        Extract detailed traceback sections from pytest output.
        Returns a dict mapping normalized test identifier -> (traceback_text, file_path, line_number)
        """
        blocks: Dict[str, Tuple[str, Optional[str], Optional[int]]] = {}
        in_block = False
        current_test_name = ""
        current_lines: List[str] = []
        captured_file: Optional[str] = None
        captured_line: Optional[int] = None

        for line in self.lines:
            header_match = PYTEST_TB_HEADER_RE.match(line)
            if header_match:
                if in_block and current_test_name:
                    blocks[current_test_name] = ("\n".join(current_lines).strip(), captured_file, captured_line)
                in_block = True
                current_test_name = header_match.group(1).strip()
                current_lines = [line]
                captured_file = None
                captured_line = None
                continue

            if in_block:
                # Check if we hit end of failures section or short test summary info
                if line.startswith("===") and ("short test summary info" in line or "passed" in line or "failed" in line):
                    blocks[current_test_name] = ("\n".join(current_lines).strip(), captured_file, captured_line)
                    in_block = False
                    current_test_name = ""
                    current_lines = []
                    continue

                current_lines.append(line)
                # Check if this line is file:line: Error
                loc_match = PYTEST_LOC_RE.match(line.strip())
                if loc_match:
                    captured_file = loc_match.group(1)
                    captured_line = int(loc_match.group(2))

        if in_block and current_test_name:
            blocks[current_test_name] = ("\n".join(current_lines).strip(), captured_file, captured_line)

        return blocks

    def _parse_pytest(self) -> ParsedRun:
        """Parse pytest test output."""
        failures: List[TestFailure] = []
        tb_blocks = self._parse_pytest_traceback_blocks()

        total_failed = 0
        total_errors = 0
        total_passed: Optional[int] = None
        duration_str: Optional[str] = None
        summary_line_found = ""

        in_short_summary = False

        for line in self.lines:
            stripped = line.strip()

            # Check for short summary start
            if "short test summary info" in stripped:
                in_short_summary = True
                continue

            # Check for footer line (e.g., ======================== 15 failed, 30 passed in 2.14s =========================)
            if stripped.startswith("=") and ("failed" in stripped or "passed" in stripped or "error" in stripped):
                footer_match = PYTEST_FOOTER_RE.search(stripped)
                if footer_match:
                    summary_line_found = stripped
                    if footer_match.group(1):
                        total_failed = int(footer_match.group(1))
                    if footer_match.group(2):
                        total_errors = int(footer_match.group(2))
                    if footer_match.group(3):
                        total_passed = int(footer_match.group(3))
                    if footer_match.group(4):
                        duration_str = f"{footer_match.group(4)}s"
                in_short_summary = False
                continue

            # Parse lines within short test summary
            if in_short_summary:
                summary_match = PYTEST_SUMMARY_LINE_RE.match(stripped)
                if summary_match:
                    status = summary_match.group(1)
                    test_id = summary_match.group(2)
                    err_rest = summary_match.group(3)

                    err_type, err_msg = parse_error_details(err_rest)

                    # Extract file_path and test_name from test_id
                    # Example: orders/tests/test_orders.py::test_create_order
                    # or users/tests/test_auth.py::TestAuth::test_login[invalid]
                    if "::" in test_id:
                        parts = test_id.split("::")
                        file_path = parts[0]
                        test_name = parts[-1]
                    else:
                        file_path = test_id
                        test_name = test_id

                    # Find matching traceback block
                    traceback_text = ""
                    line_no = None

                    # Try exact match on test_name or test_id
                    for tb_name, (tb_content, tb_file, tb_line) in tb_blocks.items():
                        if tb_name == test_name or tb_name in test_id or test_name in tb_name:
                            traceback_text = tb_content
                            line_no = tb_line
                            if tb_file and not file_path:
                                file_path = tb_file
                            break

                    failures.append(
                        TestFailure(
                            test_id=test_id,
                            file_path=file_path,
                            test_name=test_name,
                            error_type=err_type,
                            error_message=err_msg,
                            traceback=traceback_text,
                            status=status,
                            framework="pytest",
                            line_number=line_no,
                        )
                    )

        # Fallback if no short test summary info was generated
        if not failures and tb_blocks:
            for tb_name, (tb_content, tb_file, tb_line) in tb_blocks.items():
                # Extract error from 'E       ErrorType: message'
                e_lines = [l for l in tb_content.splitlines() if l.strip().startswith("E ")]
                err_type = "AssertionError"
                err_msg = ""
                if e_lines:
                    first_e = e_lines[0].strip()[2:].strip()
                    err_type, err_msg = parse_error_details(first_e)

                file_path = tb_file or "unknown_test.py"
                test_id = f"{file_path}::{tb_name}"

                failures.append(
                    TestFailure(
                        test_id=test_id,
                        file_path=file_path,
                        test_name=tb_name,
                        error_type=err_type,
                        error_message=err_msg,
                        traceback=tb_content,
                        status="FAILED",
                        framework="pytest",
                        line_number=tb_line,
                    )
                )

        if not failures:
            tb_fails = self._extract_unhandled_tracebacks(framework="pytest")
            if tb_fails:
                failures = tb_fails
                total_errors = len(tb_fails)

        if total_failed == 0 and not total_errors:
            total_failed = sum(1 for f in failures if f.status == "FAILED")
            total_errors = sum(1 for f in failures if f.status == "ERROR")

        return ParsedRun(
            failures=failures,
            total_failed=total_failed,
            total_passed=total_passed,
            total_errors=total_errors,
            framework="pytest",
            duration_str=duration_str,
            raw_summary_line=summary_line_found,
        )

    def _parse_django(self) -> ParsedRun:
        """Parse standard Django manage.py test runner output."""
        failures: List[TestFailure] = []
        total_failed = 0
        total_errors = 0
        total_ran = 0
        duration_str = None

        # Split into blocks by ======================================================================
        content = self.clean_text
        blocks = re.split(r'={40,}', content)

        for block in blocks:
            header_match = DJANGO_HEADER_RE.search(block)
            if not header_match:
                continue

            status_raw = header_match.group(1)  # FAIL or ERROR
            status = "FAILED" if status_raw == "FAIL" else "ERROR"
            test_method = header_match.group(2).strip()
            class_or_module = header_match.group(3).strip()

            test_id = f"{class_or_module}.{test_method}"

            # Extract traceback and error
            tb_match = re.search(r'(Traceback \(most recent call last\):[\s\S]+)', block)
            tb_text = tb_match.group(1).strip() if tb_match else block.strip()

            # Find file path and line number from traceback
            file_match = re.findall(r'File "([^"]+)", line (\d+)', tb_text)
            file_path = file_match[-1][0] if file_match else class_or_module.replace('.', '/') + ".py"
            line_no = int(file_match[-1][1]) if file_match else None

            # The last non-empty line of traceback usually contains the exception:
            tb_lines = [l.strip() for l in tb_text.splitlines() if l.strip()]
            last_line = tb_lines[-1] if tb_lines else "AssertionError"
            err_type, err_msg = parse_error_details(last_line)

            failures.append(
                TestFailure(
                    test_id=test_id,
                    file_path=file_path,
                    test_name=test_method,
                    error_type=err_type,
                    error_message=err_msg,
                    traceback=tb_text,
                    status=status,
                    framework="django",
                    line_number=line_no,
                )
            )

        # Parse final summary
        summary_match = DJANGO_SUMMARY_RE.search(content)
        if summary_match:
            if summary_match.group(1):
                total_failed = int(summary_match.group(1))
            if summary_match.group(2):
                total_errors = int(summary_match.group(2))

        ran_match = DJANGO_RAN_RE.search(content)
        if ran_match:
            total_ran = int(ran_match.group(1))
            duration_str = f"{ran_match.group(2)}s"

        if total_failed == 0 and total_errors == 0:
            total_failed = sum(1 for f in failures if f.status == "FAILED")
            total_errors = sum(1 for f in failures if f.status == "ERROR")

        total_passed = max(0, total_ran - (total_failed + total_errors)) if total_ran > 0 else None

        if not failures:
            failures = self._extract_unhandled_tracebacks(framework="django")
            if failures:
                total_errors = len(failures)

        return ParsedRun(
            failures=failures,
            total_failed=total_failed,
            total_passed=total_passed,
            total_errors=total_errors,
            framework="django",
            duration_str=duration_str,
            raw_summary_line=summary_match.group(0) if summary_match else "",
        )

    def _extract_unhandled_tracebacks(self, framework: str = "django") -> List[TestFailure]:
        """
        Extract unhandled Python exception tracebacks or runner crash blocks
        when tests fail during setup, database initialization, or collection.
        """
        failures: List[TestFailure] = []
        tb_indices = [m.start() for m in re.finditer(r'Traceback \(most recent call last\):', self.clean_text)]
        if not tb_indices:
            # Check for bare fatal exceptions (e.g. ImproperlyConfigured, ModuleNotFoundError without traceback)
            exc_match = EXCEPTION_LINE_RE.search(self.clean_text)
            if exc_match:
                err_type = exc_match.group(1).strip()
                err_msg = exc_match.group(2).strip()
                failures.append(
                    TestFailure(
                        test_id=f"runner::{err_type}",
                        file_path="runner",
                        test_name="runner_execution",
                        error_type=err_type,
                        error_message=err_msg,
                        traceback=self.clean_text.strip(),
                        status="ERROR",
                        framework=framework,
                        line_number=None,
                    )
                )
            return failures

        first_tb = tb_indices[0]
        tb_block = self.clean_text[first_tb:].strip()

        # Extract file frames: File "...", line X
        all_frames = re.findall(r'File "([^"]+)", line (\d+)(?:, in (\w+))?', tb_block)
        # Identify user/project frames (exclude virtualenvs, site-packages, standard lib)
        user_frames = [
            f for f in all_frames
            if "site-packages" not in f[0].lower()
            and "dist-packages" not in f[0].lower()
            and "lib\\" not in f[0].lower()
            and "lib/" not in f[0].lower()
        ]
        primary_frame = user_frames[-1] if user_frames else (all_frames[-1] if all_frames else ("runner", 1, ""))
        file_path = primary_frame[0]
        line_no = int(primary_frame[1]) if primary_frame[1] else None

        # Find the exception line from the traceback
        lines = [l.strip() for l in tb_block.splitlines() if l.strip()]
        err_type = "RunnerError"
        err_msg = ""
        for l in reversed(lines):
            if re.match(r'^[A-Za-z_][A-Za-z0-9_\.]*(?:Error|Exception|Failure|Warning|Exit|Interrupt|Fault)?:\s*', l):
                err_type, err_msg = parse_error_details(l)
                break

        test_scope = "runner_setup"
        if "setup_databases" in tb_block or "create_test_db" in tb_block or "database" in err_msg.lower() or "creating test database" in self.clean_text.lower():
            test_scope = "database_setup"
        elif "collecting" in tb_block or "collection" in tb_block:
            test_scope = "collection"
        elif "import" in err_msg.lower() or "modulenotfound" in err_type.lower():
            test_scope = "import_setup"

        test_id = f"{file_path}::{test_scope}"

        failures.append(
            TestFailure(
                test_id=test_id,
                file_path=file_path,
                test_name=test_scope,
                error_type=err_type,
                error_message=err_msg,
                traceback=tb_block,
                status="ERROR",
                framework=framework,
                line_number=line_no,
            )
        )
        return failures


def parse_test_output(raw_output: str) -> ParsedRun:
    """Convenience helper to parse raw test output directly."""
    parser = TestOutputParser(raw_output)
    return parser.parse()
