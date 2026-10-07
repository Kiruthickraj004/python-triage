from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class TestFailure:
    """Represents an individual test failure or error extracted from test output."""
    test_id: str
    file_path: str
    test_name: str
    error_type: str
    error_message: str
    traceback: str = ""
    status: str = "FAILED"  # FAILED or ERROR or FAIL
    framework: str = "pytest"  # pytest or django
    line_number: Optional[int] = None
    raw_snippet: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "file_path": self.file_path,
            "test_name": self.test_name,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "traceback": self.traceback,
            "status": self.status,
            "framework": self.framework,
            "line_number": self.line_number,
        }


@dataclass
class PreGroup:
    """Represents a deterministic cluster of related test failures sharing root cause symptoms."""
    group_id: int
    category: str
    error_type: str
    root_cause_pattern: str
    failures: List[TestFailure] = field(default_factory=list)
    suggested_fix: str = ""
    confidence: float = 0.90
    priority: str = "MEDIUM"  # HIGH, MEDIUM, LOW

    @property
    def count(self) -> int:
        return len(self.failures)

    @property
    def affected_files(self) -> List[str]:
        seen = set()
        result = []
        for f in self.failures:
            if f.file_path not in seen:
                seen.add(f.file_path)
                result.append(f.file_path)
        return result

    @property
    def representative_traceback(self) -> str:
        """Picks the best, most comprehensive traceback from the group for token-optimized LLM analysis."""
        if not self.failures:
            return ""
        # Prefer a failure that has a substantial traceback
        sorted_by_tb = sorted(self.failures, key=lambda f: len(f.traceback.strip()), reverse=True)
        return sorted_by_tb[0].traceback

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "category": self.category,
            "error_type": self.error_type,
            "root_cause_pattern": self.root_cause_pattern,
            "count": self.count,
            "priority": self.priority,
            "suggested_fix": self.suggested_fix,
            "confidence": self.confidence,
            "affected_files": self.affected_files,
            "failures": [f.to_dict() for f in self.failures],
            "representative_traceback": self.representative_traceback,
        }


@dataclass
class ParsedRun:
    """Represents the complete parsed results from test runner output."""
    failures: List[TestFailure] = field(default_factory=list)
    total_failed: int = 0
    total_passed: Optional[int] = None
    total_errors: int = 0
    framework: str = "pytest"
    duration_str: Optional[str] = None
    raw_summary_line: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_failed": self.total_failed,
            "total_passed": self.total_passed,
            "total_errors": self.total_errors,
            "framework": self.framework,
            "duration": self.duration_str,
            "failures": [f.to_dict() for f in self.failures],
        }
