import pytest


class OperationalError(Exception):
    pass


class ModuleNotFoundError(Exception):
    pass


def test_db_order_checkout():
    """Simulates Django ORM attempting to query PostgreSQL when container is down."""
    raise OperationalError(
        "could not connect to server: Connection refused\n"
        "\tIs the server running on host 'localhost' (127.0.0.1) and accepting\n"
        "\tTCP/IP connections on port 5432?"
    )


def test_db_user_login():
    """Simulates another endpoint hit by the same DB outage."""
    raise OperationalError("could not connect to server: Connection refused")


def test_stripe_card_charge():
    """Simulates missing third-party payment dependency."""
    raise ModuleNotFoundError("No module named 'stripe'")


def test_api_status_response():
    """Simulates unhandled internal server error (500)."""
    actual_status = 500
    expected_status = 201
    assert actual_status == expected_status, f"expected {expected_status}, got {actual_status}"


def test_health_check_passes():
    """Passing test to verify runner handles mixed results."""
    assert True
