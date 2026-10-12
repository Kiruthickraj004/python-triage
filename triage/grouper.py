import re
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
from triage.models import TestFailure, PreGroup


# Pre-compiled regex patterns for diagnostic classification
DB_CONNECTION_RE = re.compile(
    r'(could not connect to server|connection refused|operationalerror|can\'t connect to (?:mysql|postgresql)|connection to localhost.*failed|database.*down|password authentication failed)',
    re.IGNORECASE
)
DB_MIGRATION_RE = re.compile(
    r'(relation ".*" does not exist|no such table|programmingerror)',
    re.IGNORECASE
)
MODULE_NOT_FOUND_RE = re.compile(
    r'no module named [\'"]([^\'"]+)[\'"]',
    re.IGNORECASE
)
CANNOT_IMPORT_RE = re.compile(
    r'cannot import name [\'"]([^\'"]+)[\'"]',
    re.IGNORECASE
)
HTTP_500_RE = re.compile(
    r'(expected 20[0-9], got 500|assert 500 == 20[0-9]|status_code == 500|500 != 20[0-9]|got 500)',
    re.IGNORECASE
)
HTTP_401_403_RE = re.compile(
    r'(assert 40[13] == 20[0-9]|expected 20[0-9], got 40[13]|40[13] != 20[0-9]|notauthenticated|permissiondenied)',
    re.IGNORECASE
)


class FailureGrouper:
    """
    Deterministic pre-grouping engine that clusters test failures by their
    symptomatic root causes before LLM analysis or for standalone CLI output.
    """

    def __init__(self, failures: List[TestFailure]):
        self.failures = failures

    def group(self) -> List[PreGroup]:
        """Cluster all failures into ranked, deduplicated PreGroup buckets."""
        if not self.failures:
            return []

        clusters: Dict[str, Dict] = defaultdict(lambda: {
            "category": "",
            "error_type": "",
            "root_cause_pattern": "",
            "failures": [],
            "suggested_fix": "",
            "confidence": 0.85,
            "priority": "MEDIUM",
        })

        for failure in self.failures:
            cluster_key, meta = self._classify_failure(failure)
            cluster = clusters[cluster_key]
            cluster["category"] = meta["category"]
            cluster["error_type"] = meta["error_type"]
            cluster["root_cause_pattern"] = meta["root_cause_pattern"]
            cluster["suggested_fix"] = meta["suggested_fix"]
            cluster["confidence"] = meta["confidence"]
            cluster["priority"] = meta["priority"]
            cluster["failures"].append(failure)

        # Build PreGroup objects
        result_groups: List[PreGroup] = []
        for idx, (key, data) in enumerate(clusters.items(), start=1):
            group = PreGroup(
                group_id=idx,
                category=data["category"],
                error_type=data["error_type"],
                root_cause_pattern=data["root_cause_pattern"],
                failures=data["failures"],
                suggested_fix=data["suggested_fix"],
                confidence=data["confidence"],
                priority=data["priority"],
            )
            result_groups.append(group)

        # Sort groups:
        # 1. High priority first (HIGH -> MEDIUM -> LOW)
        # 2. Largest failure count first (fix the root cause that resolves 18 tests first!)
        priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        result_groups.sort(
            key=lambda g: (priority_order.get(g.priority, 1), -g.count)
        )

        # Re-number group IDs sequentially after sorting
        for i, g in enumerate(result_groups, start=1):
            g.group_id = i

        return result_groups

    def _classify_failure(self, failure: TestFailure) -> Tuple[str, Dict]:
        """
        Determine the cluster key and diagnostic metadata for a single failure.
        """
        combined_text = f"{failure.error_type} {failure.error_message} {failure.traceback}".strip()

        # 1. Database connection / service unreachable
        if (
            "OperationalError" in failure.error_type
            or "ConnectionError" in failure.error_type
            or DB_CONNECTION_RE.search(combined_text)
        ):
            if DB_MIGRATION_RE.search(combined_text):
                return "db_migration_missing", {
                    "category": "Unapplied Database Migrations",
                    "error_type": failure.error_type,
                    "root_cause_pattern": "Database table or relation does not exist; migrations pending",
                    "suggested_fix": "Run 'python manage.py migrate' (or 'pytest --migrations')",
                    "confidence": 0.95,
                    "priority": "HIGH",
                }

            is_auth_failure = "password authentication failed" in combined_text.lower()
            pattern = (
                "Database authentication failed or database container not ready"
                if is_auth_failure
                else "Database service unreachable or connection refused on configured port"
            )
            suggested_fix = (
                "Ensure PostgreSQL container is running (e.g. 'docker compose up -d') and check DATABASE_URL / DB credentials"
                if is_auth_failure
                else "Ensure PostgreSQL/database is running (e.g. 'docker compose up -d postgres') and check DATABASE_URL"
            )

            return "db_connection_refused", {
                "category": "Database Connection Refused",
                "error_type": failure.error_type,
                "root_cause_pattern": pattern,
                "suggested_fix": suggested_fix,
                "confidence": 0.98,
                "priority": "HIGH",
            }

        # 2. Missing module or import error
        if (
            "ModuleNotFoundError" in failure.error_type
            or "ImportError" in failure.error_type
            or "ModuleNotFoundError" in combined_text
            or "ImportError" in combined_text
            or MODULE_NOT_FOUND_RE.search(combined_text)
        ):
            mod_match = MODULE_NOT_FOUND_RE.search(combined_text)
            missing_module = mod_match.group(1) if mod_match else "dependency"
            return f"missing_module_{missing_module}", {
                "category": f"Missing Dependency ({missing_module})",
                "error_type": failure.error_type,
                "root_cause_pattern": f"Required Python package '{missing_module}' is not installed in the environment",
                "suggested_fix": f"pip install {missing_module} (or add to requirements.txt / pyproject.toml)",
                "confidence": 1.0,
                "priority": "HIGH",
            }

        # 3. Server HTTP 500 Internal Server Error cascade
        if HTTP_500_RE.search(combined_text):
            return "http_500_server_error", {
                "category": "API Internal Server Error (500)",
                "error_type": "AssertionError",
                "root_cause_pattern": "API endpoint returned status 500 instead of expected successful status code",
                "suggested_fix": "Check server traceback or view implementation for unhandled exception or broken serializer",
                "confidence": 0.92,
                "priority": "HIGH",
            }

        # 4. Authentication / Permission 401 or 403 errors
        if HTTP_401_403_RE.search(combined_text) or "NotAuthenticated" in failure.error_type or "PermissionDenied" in failure.error_type:
            return "auth_permission_failure", {
                "category": "Authentication & Permission Failure (401/403)",
                "error_type": failure.error_type,
                "root_cause_pattern": "Request rejected with 401 Unauthorized or 403 Forbidden; test client not authenticated or lacks required roles",
                "suggested_fix": "Ensure test calls 'client.force_authenticate(user=...)' or provide valid authorization headers",
                "confidence": 0.90,
                "priority": "MEDIUM",
            }

        # 5. Validation errors (DRF or Django)
        if "ValidationError" in failure.error_type:
            return "validation_error", {
                "category": "Data Validation Error",
                "error_type": failure.error_type,
                "root_cause_pattern": "Request payload failed serializer or model field validation",
                "suggested_fix": "Inspect invalid serializer payload in test setup against schema rules",
                "confidence": 0.88,
                "priority": "MEDIUM",
            }

        # 6. Group by specific error_type and file path prefix or common error type
        key = f"{failure.error_type}:{failure.file_path}"
        category_name = f"{failure.error_type} in {failure.file_path}"
        if failure.error_type == "AssertionError":
            category_name = f"Assertion Mismatch ({failure.file_path})"

        return key, {
            "category": category_name,
            "error_type": failure.error_type,
            "root_cause_pattern": failure.error_message or f"Failure of type {failure.error_type}",
            "suggested_fix": "Inspect assertion logic or expected test values",
            "confidence": 0.80,
            "priority": "LOW",
        }


def pre_group_failures(failures: List[TestFailure]) -> List[PreGroup]:
    """Convenience helper to group failures into diagnostic clusters."""
    grouper = FailureGrouper(failures)
    return grouper.group()
