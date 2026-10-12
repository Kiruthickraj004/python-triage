import json
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Set, Optional, Tuple
from triage.models import PreGroup, TestFailure


@dataclass
class AnalyzedGroup:
    """Represents a validated, ranked failure group ready for presentation."""
    group_id: int
    root_cause: str
    explanation: str
    suggested_fix: str
    priority: str
    confidence: float
    affected_tests: List[str]
    source: str = "llm"  # "llm" or "deterministic_fallback"
    representative_traceback: str = ""

    @property
    def count(self) -> int:
        return len(self.affected_tests)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "root_cause": self.root_cause,
            "explanation": self.explanation,
            "suggested_fix": self.suggested_fix,
            "priority": self.priority,
            "confidence": self.confidence,
            "affected_tests": self.affected_tests,
            "count": self.count,
            "source": self.source,
            "representative_traceback": self.representative_traceback,
        }


@dataclass
class TriageResult:
    """The final validated triage report produced by the compound AI pipeline."""
    summary: str
    groups: List[AnalyzedGroup] = field(default_factory=list)
    is_fallback: bool = False
    validation_warnings: List[str] = field(default_factory=list)
    provider: str = "deterministic"
    latency_ms: float = 0.0

    @property
    def total_failures(self) -> int:
        return sum(len(g.affected_tests) for g in self.groups)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "total_failures": self.total_failures,
            "is_fallback": self.is_fallback,
            "provider": self.provider,
            "latency_ms": self.latency_ms,
            "validation_warnings": self.validation_warnings,
            "groups": [g.to_dict() for g in self.groups],
        }


class TriageValidator:
    """
    Guardrail validation layer that enforces set-theory invariants:
    all input test failures MUST be accounted for in the output,
    with zero hallucinated tests and zero dropped tests.
    """

    def __init__(self, pre_groups: List[PreGroup]):
        self.pre_groups = pre_groups
        self.test_id_to_failure: Dict[str, TestFailure] = {}
        self.test_id_to_pregroup: Dict[str, PreGroup] = {}

        for g in pre_groups:
            for f in g.failures:
                self.test_id_to_failure[f.test_id] = f
                self.test_id_to_pregroup[f.test_id] = g

        self.ground_truth_test_ids: Set[str] = set(self.test_id_to_failure.keys())

    def fallback_to_deterministic(self, reason: str = "LLM unavailable or failed") -> TriageResult:
        """Convert deterministic pre-groups into final AnalyzedGroup objects."""
        analyzed_groups: List[AnalyzedGroup] = []
        for g in self.pre_groups:
            ag = AnalyzedGroup(
                group_id=g.group_id,
                root_cause=g.category,
                explanation=g.root_cause_pattern,
                suggested_fix=g.suggested_fix,
                priority=g.priority,
                confidence=g.confidence,
                affected_tests=[f.test_id for f in g.failures],
                source="deterministic_fallback",
                representative_traceback=g.representative_traceback,
            )
            analyzed_groups.append(ag)

        summary = f"Triaged {len(self.ground_truth_test_ids)} failures into {len(analyzed_groups)} groups via deterministic rule engine ({reason})."
        return TriageResult(
            summary=summary,
            groups=analyzed_groups,
            is_fallback=True,
            validation_warnings=[f"Fallback activated: {reason}"],
            provider="deterministic",
            latency_ms=0.0,
        )

    def validate_and_repair(
        self,
        raw_response: str | Dict[str, Any],
        provider: str = "llm",
        latency_ms: float = 0.0,
    ) -> TriageResult:
        """
        Validate LLM response against schema and set invariants.
        Auto-repairs missing or hallucinated tests to ensure 100% fidelity.
        """
        warnings: List[str] = []

        # 1. Parse JSON
        data: Dict[str, Any] = {}
        if isinstance(raw_response, dict):
            data = raw_response
        else:
            cleaned = self._clean_json_string(str(raw_response))
            try:
                data = json.loads(cleaned)
            except Exception as e:
                return self.fallback_to_deterministic(f"JSON decode failed: {e}")

        if not isinstance(data, dict) or "groups" not in data or not isinstance(data["groups"], list):
            return self.fallback_to_deterministic("Invalid response format: 'groups' array missing")

        raw_groups = data["groups"]
        if not raw_groups:
            return self.fallback_to_deterministic("LLM returned 0 groups")

        # 2. Extract and sanitize groups
        analyzed_groups: List[AnalyzedGroup] = []
        accounted_tests: Set[str] = set()

        for idx, rg in enumerate(raw_groups, start=1):
            if not isinstance(rg, dict):
                continue

            root_cause = str(rg.get("root_cause") or f"Group {idx}").strip()
            explanation = str(rg.get("explanation") or "").strip()
            suggested_fix = str(rg.get("suggested_fix") or "").strip()
            priority = str(rg.get("priority") or "MEDIUM").upper()
            if priority not in ("HIGH", "MEDIUM", "LOW"):
                priority = "MEDIUM"

            try:
                confidence = float(rg.get("confidence", 0.90))
                confidence = max(0.0, min(1.0, confidence))
            except (ValueError, TypeError):
                confidence = 0.90

            raw_affected = rg.get("affected_tests", [])
            if not isinstance(raw_affected, list):
                raw_affected = []

            # Filter hallucinations: only keep tests that truly existed in input
            valid_tests: List[str] = []
            for tid in raw_affected:
                tid_str = str(tid).strip()
                if tid_str in self.ground_truth_test_ids:
                    if tid_str not in accounted_tests:
                        valid_tests.append(tid_str)
                        accounted_tests.add(tid_str)
                else:
                    warnings.append(f"Removed hallucinated test ID from group {idx}: {tid_str}")

            # Find best representative traceback for this group
            rep_tb = ""
            for tid in valid_tests:
                fail_obj = self.test_id_to_failure.get(tid)
                if fail_obj and fail_obj.traceback:
                    if len(fail_obj.traceback) > len(rep_tb):
                        rep_tb = fail_obj.traceback

            analyzed_groups.append(
                AnalyzedGroup(
                    group_id=idx,
                    root_cause=root_cause,
                    explanation=explanation,
                    suggested_fix=suggested_fix,
                    priority=priority,
                    confidence=confidence,
                    affected_tests=valid_tests,
                    source="llm",
                    representative_traceback=rep_tb,
                )
            )

        # 3. Check for dropped / missing tests (Set Theory Invariant)
        missing_tests = self.ground_truth_test_ids - accounted_tests
        if missing_tests:
            warnings.append(f"LLM omitted {len(missing_tests)} tests. Auto-repairing by re-attaching to matching groups.")

            # Attempt to re-attach each missing test to the most relevant group
            for missing_tid in sorted(missing_tests):
                origin_pregroup = self.test_id_to_pregroup.get(missing_tid)
                attached = False

                if origin_pregroup and analyzed_groups:
                    # Try to find group matching origin category or error type
                    for ag in analyzed_groups:
                        if (
                            origin_pregroup.category.lower() in ag.root_cause.lower()
                            or origin_pregroup.error_type.lower() in ag.explanation.lower()
                        ):
                            ag.affected_tests.append(missing_tid)
                            accounted_tests.add(missing_tid)
                            attached = True
                            break

                # If still not attached, add to the first group or create a catch-all group
                if not attached and analyzed_groups:
                    analyzed_groups[0].affected_tests.append(missing_tid)
                    accounted_tests.add(missing_tid)

        # Remove any groups that ended up with 0 tests after deduplication
        analyzed_groups = [g for g in analyzed_groups if g.affected_tests]

        # If all groups got pruned, fallback
        if not analyzed_groups:
            return self.fallback_to_deterministic("All LLM groups had 0 valid tests")

        # Re-number groups sequentially
        for i, g in enumerate(analyzed_groups, start=1):
            g.group_id = i

        summary_text = str(data.get("summary") or f"Triaged {len(accounted_tests)} test failures into {len(analyzed_groups)} groups.")

        return TriageResult(
            summary=summary_text,
            groups=analyzed_groups,
            is_fallback=False,
            validation_warnings=warnings,
            provider=provider,
            latency_ms=latency_ms,
        )

    def _clean_json_string(self, text: str) -> str:
        """Strip markdown code block fences and whitespace from model output."""
        text = text.strip()
        # Remove ```json ... ```
        fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if fence_match:
            return fence_match.group(1).strip()
        return text
