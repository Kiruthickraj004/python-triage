import json
from typing import List, Tuple, Dict, Any
from triage.models import PreGroup

TRIAGE_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
      "summary": {
        "type": "string",
        "description": "One sentence summary of the overall test run triage.",
      },
      "groups": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "group_id": {"type": "integer"},
            "root_cause": {
              "type": "string",
              "description": "Short, descriptive title of root cause (e.g. 'PostgreSQL Connection Refused').",
            },
            "explanation": {
              "type": "string",
              "description": "Plain English explanation of why the cascade occurred.",
            },
            "suggested_fix": {
              "type": "string",
              "description": "Exact terminal commands or code change to resolve the issue.",
            },
            "priority": {
              "type": "string",
              "enum": ["HIGH", "MEDIUM", "LOW"],
            },
            "confidence": {
              "type": "number",
              "description": "Confidence score between 0.0 and 1.0",
            },
            "affected_tests": {
              "type": "array",
              "items": {"type": "string"},
              "description": "List of exact test IDs belonging to this group.",
            },
          },
          "required": [
            "group_id",
            "root_cause",
            "explanation",
            "suggested_fix",
            "priority",
            "confidence",
            "affected_tests",
          ],
        },
      },
    },
    "required": ["summary", "groups"],
}

SYSTEM_PROMPT = """You are a Principal Software Engineer specializing in Python, Django, Django REST Framework, and Pytest.
Your task is to analyze clustered test failures, identify the true underlying root causes, and provide high-confidence, actionable fixes.

CRITICAL INSTRUCTIONS:
1. Return ONLY valid JSON matching the specified schema. No markdown formatting, no conversational filler.
2. CONSERVATION OF TESTS: Every single test ID provided in the input MUST appear in the 'affected_tests' array of exactly one group.
   - Do NOT omit any test IDs.
   - Do NOT invent or alter any test IDs.
3. Keep 'suggested_fix' concise, practical, and directly executable (e.g., 'docker compose up -d postgres', 'pip install stripe', 'python manage.py migrate', or specific code fixes).
4. Explain the 'why' in 'explanation' so developers immediately grasp why multiple tests failed from one issue.
5. Order groups by highest impact first (HIGH priority / most affected tests).
"""


def build_triage_prompt(pre_groups: List[PreGroup], framework: str = "pytest") -> Tuple[str, str]:
    """
    Construct system and user prompts with token-optimized pre-group summaries
    and representative tracebacks.
    """
    total_tests = sum(g.count for g in pre_groups)

    lines = [
        f"Test Framework: {framework.upper()}",
        f"Total Failing Tests: {total_tests}",
        f"Pre-grouped Failure Clusters: {len(pre_groups)}",
        "",
        "Analyze the following clusters and output the structured JSON triage report:",
        "----------------------------------------------------------------",
    ]

    for g in pre_groups:
        lines.append(f"### Cluster #{g.group_id}: {g.category}")
        lines.append(f"- Error Type: {g.error_type}")
        lines.append(f"- Count: {g.count} test(s)")
        lines.append(f"- Affected Files: {', '.join(g.affected_files)}")
        lines.append("- Test IDs:")
        for f in g.failures:
            lines.append(f"  * {f.test_id}")

        if g.suggested_fix:
            lines.append(f"- Heuristic Hint: {g.suggested_fix}")

        if g.representative_traceback:
            lines.append("- Sample Representative Traceback (1 sampled from cluster):")
            lines.append("```")
            tb_snippet = g.representative_traceback.strip()
            # Limit individual traceback to 15 lines max for token safety
            tb_lines = tb_snippet.splitlines()
            if len(tb_lines) > 15:
                tb_snippet = "\n".join(tb_lines[:15]) + "\n... (truncated for brevity)"
            lines.append(tb_snippet)
            lines.append("```")

        lines.append("")

    lines.append("----------------------------------------------------------------")
    lines.append("Output JSON Schema requirements:")
    lines.append(json.dumps(TRIAGE_JSON_SCHEMA, indent=2))

    user_prompt = "\n".join(lines)
    return SYSTEM_PROMPT.strip(), user_prompt.strip()
