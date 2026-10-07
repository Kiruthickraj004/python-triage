# Triage (`triage-ai`)

> **AI-Powered & Deterministic Test Failure Root-Cause Analyzer & Triage CLI for Python & Django**

When 35 tests fail on CI or locally due to a single database connection drop or a missing dependency, scrolling through hundreds of lines of terminal tracebacks is slow and exhausting.

`triage` intercepts and parses test outputs, strips terminal ANSI codes, and **deterministically pre-groups failures into prioritized root cause clusters**—sampling exactly one representative traceback per cluster to slash token overhead by 90%+ before LLM analysis.

---

## Architecture Overview

```text
               ┌──────────────────────────────┐
               │    Raw Test Runner Output    │
               │  (Pytest / Django manage.py) │
               └──────────────┬───────────────┘
                              │
                              ▼
               ┌──────────────────────────────┐
               │         Parser Layer         │
               │  • ANSI Escape Cleaner       │
               │  • Short Summary Extractor   │
               │  • Traceback & Frame Mapper  │
               └──────────────┬───────────────┘
                              │
                              ▼
               ┌──────────────────────────────┐
               │      Pre-Grouper Engine      │
               │  • High-impact Cascades      │
               │  • DB Connection Refused     │
               │  • Missing Module (stripe)   │
               │  • Server 500 Cascades       │
               │  • Auth & Perm (401/403)     │
               └──────────────┬───────────────┘
                              │
                              ▼
               ┌──────────────────────────────┐
               │    Rich Terminal Dashboard   │
               │  • Priority Badges           │
               │  • Root Cause Explanations   │
               │  • Deterministic Fix Steps   │
               │  • 1 Representative Traceback│
               └──────────────────────────────┘
```

---

## Features (Milestone 1)

- **Universal Python Test Output Parser**:
  - Full support for `pytest` (standard, verbose, parameterized `[param1-param2]`, `--tb=short`, and ANSI colors).
  - Full support for Django's `python manage.py test` runner.
  - Robust regex extraction of test identifiers, file locations, line numbers, error types, and traceback excerpts.
- **Deterministic Pre-Grouper**:
  - Clusters cascading errors into categorized buckets (Database connections, unapplied migrations, missing pip packages, server 500 cascades, and auth 401/403 rejections).
  - Guaranteed conservation of failures: exactly accounts for all tests with 0 hallucinations or lost items.
  - Samples exactly 1 representative traceback per cluster (slashing downstream LLM token costs by over 90%).
  - Provides deterministic, rule-based suggested fixes even without an external API.
- **Rich Terminal UI**:
  - Color-coded group cards, priority badges (`HIGH PRIORITY`, `MEDIUM`, `LOW`), affected test trees, and preview blocks.
  - Cross-platform UTF-8 terminal encoding support for Windows PowerShell and Linux/macOS.
- **Production Fixture Suite**:
  - 6 realistic test fixtures covering DB outages, missing dependencies, DRF 500 status mismatches, parameterized tests, ANSI sequences, and Django `manage.py test` outputs.

---

## Quick Start

### 1. Setup Virtual Environment
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

### 2. Run the Test Suite
```powershell
pytest -v
```

### 3. Analyze Test Failure Logs
```powershell
# Analyze a 35-failure test run
triage analyze tests/fixtures/pytest_mixed_35_failures.txt

# Or pipe test outputs directly via stdin
Get-Content tests/fixtures/pytest_django_db_cascade.txt | triage
Get-Content tests/fixtures/django_manage_py_test.txt | triage
```

### 4. Run Tests Directly with Auto-Triage
```powershell
triage run "pytest"
```
