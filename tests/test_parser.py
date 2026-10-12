import os
from pathlib import Path
from triage.parser import strip_ansi, parse_error_details, TestOutputParser, parse_test_output

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def read_fixture(filename: str) -> str:
    path = FIXTURES_DIR / filename
    return path.read_text(encoding="utf-8")


def test_strip_ansi():
    raw = "\x1b[31mFAILED\x1b[0m test_order.py::test_create - \x1b[1mAssertionError\x1b[0m"
    cleaned = strip_ansi(raw)
    assert cleaned == "FAILED test_order.py::test_create - AssertionError"


def test_parse_error_details():
    err_type, err_msg = parse_error_details("django.db.utils.OperationalError: could not connect to server")
    assert err_type == "django.db.utils.OperationalError"
    assert err_msg == "could not connect to server"

    err_type, err_msg = parse_error_details("AssertionError: expected 201, got 500")
    assert err_type == "AssertionError"
    assert err_msg == "expected 201, got 500"

    err_type, err_msg = parse_error_details("AssertionError")
    assert err_type == "AssertionError"
    assert err_msg == ""


def test_parse_pytest_db_cascade():
    content = read_fixture("pytest_django_db_cascade.txt")
    run = parse_test_output(content)

    assert run.framework == "pytest"
    assert run.total_failed == 15
    assert run.total_passed == 30
    assert run.duration_str == "2.14s"
    assert len(run.failures) == 15

    # Check first failure
    first = run.failures[0]
    assert first.test_id == "orders/tests/test_orders.py::test_order_creation_flow"
    assert first.file_path == "orders/tests/test_orders.py"
    assert first.test_name == "test_order_creation_flow"
    assert first.error_type == "django.db.utils.OperationalError"
    assert "could not connect to server" in first.error_message
    assert "TCP/IP connections on port 5432" in first.traceback
    assert first.line_number == 28


def test_parse_pytest_missing_dependency():
    content = read_fixture("pytest_missing_dependency.txt")
    run = parse_test_output(content)

    assert run.framework == "pytest"
    assert run.total_failed == 5
    assert len(run.failures) == 5

    for f in run.failures:
        assert f.error_type == "ModuleNotFoundError"
        assert "stripe" in f.error_message

    # First test should have traceback attached
    assert "import stripe" in run.failures[0].traceback


def test_parse_pytest_drf_status_mismatch():
    content = read_fixture("pytest_drf_status_mismatch.txt")
    run = parse_test_output(content)

    assert run.total_failed == 4
    assert len(run.failures) == 4

    f0 = run.failures[0]
    assert f0.test_id == "orders/tests/test_views.py::test_order_post_endpoint"
    assert f0.error_type == "AssertionError"
    assert f0.error_message == "expected 201, got 500"
    assert f0.line_number == 52

    f2 = run.failures[2]
    assert f2.error_type == "AssertionError"
    assert f2.error_message == "expected 200, got 401"


def test_parse_pytest_parameterized():
    content = read_fixture("pytest_parameterized.txt")
    run = parse_test_output(content)

    assert run.total_failed == 4
    assert len(run.failures) == 4

    names = [f.test_name for f in run.failures]
    assert "test_tax_calc[standard-NY]" in names
    assert "test_tax_calc[express-CA]" in names
    assert "TestAuth::test_login[invalid_pwd-lockout]" in names or "test_login[invalid_pwd-lockout]" in names[2]


def test_parse_pytest_ansi_colored():
    content = read_fixture("pytest_ansi_colored.txt")
    run = parse_test_output(content)

    assert run.total_failed == 2
    assert len(run.failures) == 2
    assert run.failures[0].test_id == "tests/test_db.py::test_database_connection"
    assert run.failures[0].error_type == "ConnectionError"
    assert "Could not connect to postgres" in run.failures[0].error_message
    assert run.failures[1].error_type == "ConnectionRefusedError"


def test_parse_django_manage_py_test():
    content = read_fixture("django_manage_py_test.txt")
    parser = TestOutputParser(content)
    assert parser.detect_framework() == "django"

    run = parser.parse()
    assert run.framework == "django"
    assert run.total_failed == 2
    assert run.total_errors == 1
    assert run.total_passed == 4
    assert len(run.failures) == 3

    # Check order creation failure
    order_fail = next(f for f in run.failures if "test_create_order" in f.test_name)
    assert order_fail.error_type == "AssertionError"
    assert order_fail.error_message == "500 != 201"
    assert "Traceback" in order_fail.traceback
    assert order_fail.line_number == 42

    # Check DB error
    db_fail = next(f for f in run.failures if "test_db_connection" in f.test_name)
    assert db_fail.status == "ERROR"
    assert db_fail.error_type == "django.db.utils.OperationalError"
    assert "Connection refused" in db_fail.error_message


def test_parse_django_fatal_database_setup_crash():
    raw_output = """
Running: python manage.py test carts
Creating test database for alias 'default'...
Found 2 test(s).
Traceback (most recent call last):
  File "C:\\project\\backend\\manage.py", line 22, in <module>
    main()
  File "c:\\project\\.venv\\Lib\\site-packages\\django\\db\\backends\\base\\creation.py", line 75, in create_test_db
    self._create_test_db(verbosity, autoclobber, keepdb)
django.db.utils.OperationalError: connection failed: connection to server at "127.0.0.1", port 5432 failed: FATAL:  password authentication failed for user "postgres"
"""
    parser = TestOutputParser(raw_output)
    assert parser.detect_framework() == "django"

    run = parser.parse()
    assert run.framework == "django"
    assert len(run.failures) == 1
    assert run.total_errors == 1

    failure = run.failures[0]
    assert failure.error_type == "django.db.utils.OperationalError"
    assert "password authentication failed" in failure.error_message
    assert failure.test_name == "database_setup"
    assert failure.file_path == "C:\\project\\backend\\manage.py"
    assert failure.line_number == 22


def test_parse_bare_exception_fatal_crash():
    raw_output = """
django.core.exceptions.ImproperlyConfigured: Requested setting INSTALLED_APPS, but settings are not configured.
"""
    run = parse_test_output(raw_output)
    assert len(run.failures) == 1
    assert run.failures[0].error_type == "django.core.exceptions.ImproperlyConfigured"
    assert "INSTALLED_APPS" in run.failures[0].error_message
