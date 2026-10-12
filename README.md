# Triage (`triage-ai`)

[![PyPI Version](https://img.shields.io/pypi/v/triage-ai.svg?color=blue)](https://pypi.org/project/triage-ai/)
[![Python Version](https://img.shields.io/pypi/pyversions/triage-ai.svg)](https://pypi.org/project/triage-ai/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

> **AI-Powered & Deterministic Test Failure Root-Cause Analyzer & Triage CLI for Python & Django**

When 35 tests fail simultaneously on CI or locally due to a single database connection drop, unapplied migration, or missing pip dependency, scrolling through hundreds of lines of terminal tracebacks is slow and exhausting.

`triage` intercepts and parses test outputs, cleans terminal ANSI codes, and **deterministically pre-groups failures into prioritized root cause clusters**—sampling exactly one representative traceback per cluster to slash LLM token overhead by 90%+ before root-cause analysis.

---

## 📑 Table of Contents

- [Architecture Overview](#architecture-overview)
- [Core Features](#core-features)
- [How to Use Triage](#how-to-use-triage)
  - [1. In a Single Project (Virtual Environment)](#1-in-a-single-project-virtual-environment)
  - [2. Globally on Your Machine (Available Everywhere via pipx)](#2-globally-on-your-machine-available-everywhere-via-pipx)
  - [3. Locally by Cloning the Repository (Development & Contribution)](#3-locally-by-cloning-the-repository-development--contribution)
  - [4. Inside Docker & Containerized Environments](#4-inside-docker--containerized-environments)
- [Configuration & AI Providers](#configuration--ai-providers)
- [CLI Reference & Usage Examples](#cli-reference--usage-examples)
- [Publishing to PyPI (Maintainer Guide)](#publishing-to-pypi-maintainer-guide)
- [License](#license)

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
               │  • ANSI Escape Stripper      │
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
               │     Compound LLM Engine      │
               │  • Groq (Llama-3.3 / OSS)    │
               │  • OpenAI (GPT-4o-mini)      │
               │  • Google Gemini (2.0-Flash) │
               └──────────────┬───────────────┘
                              │
                              ▼
               ┌──────────────────────────────┐
               │    Guardrail Set-Validator   │
               │  • Set Theory Invariant      │
               │  • Auto-repair Missing Tests │
               │  • Strip Hallucinations      │
               │  • Zero-Crash Fallback       │
               └──────────────┬───────────────┘
                              │
                              ▼
               ┌──────────────────────────────┐
               │    Rich Terminal Dashboard   │
               │  • Priority Badges           │
               │  • Root Cause Explanations   │
               │  • Actionable Fix Steps      │
               └──────────────────────────────┘
```

---

## Core Features

- **Universal Test Output Parser**:
  - Full support for `pytest` (standard, verbose, parameterized `[param1-param2]`, `--tb=short`, and ANSI colors).
  - Full support for Django's `python manage.py test` runner.
  - Robust regex extraction of test identifiers, file locations, line numbers, error types, and traceback excerpts.
- **Deterministic Pre-Grouper**:
  - Clusters cascading errors into categorized buckets (Database connections, unapplied migrations, missing pip packages, server 500 cascades, and auth 401/403 rejections).
  - Samples exactly 1 representative traceback per cluster, reducing LLM token consumption by over 90%.
  - High-confidence rule-based fallback when offline or without API keys.
- **Compound LLM Engine**:
  - Multi-provider support: **Groq** (`llama-3.3-70b-versatile`), **OpenAI** (`gpt-4o-mini`), and **Google Gemini** (`gemini-2.0-flash`).
  - Zero heavy external HTTP/LLM SDK dependencies: built entirely on Python standard library `urllib.request`.
- **Set-Theory Guardrail Validator**:
  - Strict invariant: `set(reported_tests) == set(input_tests)`.
  - Auto-repairs missing tests by re-attaching them to matching clusters.
  - Strips hallucinated test IDs before dashboard rendering.
  - Graceful deterministic fallback ensures the CLI never crashes on API timeouts or network errors.
- **Rich Terminal UI & Multi-Format Exporters**:
  - Color-coded group cards, priority badges (`HIGH PRIORITY`, `MEDIUM`, `LOW`), affected test trees, and preview blocks.
  - Cross-platform UTF-8 terminal encoding support for Windows PowerShell, Linux, and macOS.
  - Export to structured JSON, CI/CD Markdown summaries, and executable fix scripts (`.sh` or `.ps1`).

---

## How to Use Triage

### 1. In a Single Project (Virtual Environment)

Add `triage-ai` as a development dependency inside your existing Python or Django project:

#### Installation
```bash
# Using standard pip
pip install triage-ai

# Using Poetry
poetry add --group dev triage-ai

# Using uv
uv add --dev triage-ai
```

#### Running Tests with Triage
Activate your project's virtual environment and run:

```bash
# Wrap Pytest directly
triage run "pytest"

# Wrap Django tests
triage run "python manage.py test"

# Or pipe test outputs directly into triage
pytest | triage
```

---

### 2. Globally on Your Machine (Available Everywhere via `pipx`)

If you want `triage` available in any terminal window across all your projects without installing it into every virtual environment, use **`pipx`** (or global pip):

#### Installation
```bash
# Recommended: isolated global install via pipx
pipx install triage-ai

# Or user-level pip install
pip install --user triage-ai
```

#### Global Configuration (Shared API Key)
When installed globally, you don't need to create a `.env` in every repository. Simply create a global config file:

- **Linux / macOS:** `~/.triage/.env`
- **Windows:** `C:\Users\<YourUsername>\.triage\.env`

Add your preferred API key to this file:
```ini
GROQ_API_KEY=gsk_your_groq_api_key_here
```

Now, navigate to **any project directory** on your machine and run:
```bash
triage run "pytest"
# or
pytest | triage
```
`triage` will automatically pick up your global API key.

---

### 3. Locally by Cloning the Repository (Development & Contribution)

If you cloned this repository (`Kiruthickraj004/python-triage`) and want to hack on the code or run it locally:

#### Step 1: Clone and Enter the Directory
```bash
git clone https://github.com/Kiruthickraj004/python-triage.git
cd python-triage
```

#### Step 2: Create and Activate a Virtual Environment
```bash
# Create virtual environment
python -m venv .venv

# Activate on Windows (PowerShell):
.venv\Scripts\Activate.ps1

# Activate on Linux / macOS:
source .venv/bin/activate
```

#### Step 3: Install in Editable (`-e`) Mode with Dev Tools
```bash
pip install -e ".[dev]"
```

#### Step 4: Configure Your Environment
Copy the example environment file and add your API key:
```bash
# Windows
Copy-Item .env.example .env

# Linux / macOS
cp .env.example .env
```
Edit `.env` and set `GROQ_API_KEY`, `OPENAI_API_KEY`, or `GEMINI_API_KEY`.

#### Step 5: Run Unit Tests
```bash
pytest
```

#### Step 6: Test the Local CLI
```bash
# Using installed entry point
triage --help

# Or via Python module directly
python -m triage --help
```

---

### 4. Inside Docker & Containerized Environments

You have multiple ways to use `triage` with Docker:

#### Pattern A: Pipe Docker Test Output to Host `triage` (Zero Docker Modification)
The simplest approach is keeping your Docker container clean and running `triage` on your host machine:

```bash
# Docker Compose (Pytest)
docker compose run --rm web pytest | triage

# Docker Compose (Django)
docker compose run --rm web python manage.py test | triage

# Plain Docker run
docker run --rm my-django-app pytest | triage
```

#### Pattern B: Install `triage-ai` Inside your Docker Container
If your CI/CD or development workflow runs entirely inside containers:

1. **Add `triage-ai` to your Dockerfile or requirements-dev.txt**:
   ```dockerfile
   # Dockerfile
   FROM python:3.11-slim
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install -r requirements.txt
   
   # Install triage for test environments
   RUN pip install triage-ai
   
   COPY . .
   ```

2. **Run tests inside the container with your API key passed through**:
   ```bash
   # Pass API key as an environment variable
   docker run --rm -e GROQ_API_KEY=$GROQ_API_KEY my-django-app triage run "pytest"
   ```

3. **In `docker-compose.yml`**:
   ```yaml
   services:
     web:
       build: .
       environment:
         - GROQ_API_KEY=${GROQ_API_KEY}
       # ...
   ```
   Execute tests:
   ```bash
   docker compose run --rm web triage run "pytest"
   ```

#### Pattern C: Export CI/CD Reports in Dockerized CI Pipelines
Generate clean GitHub Action summaries or GitLab artifacts directly:
```bash
# In GitHub Actions workflow
docker compose run --rm web triage run "pytest" --format markdown >> $GITHUB_STEP_SUMMARY
```

---

## Configuration & AI Providers

`triage` supports **Groq**, **OpenAI**, and **Google Gemini** out of the box with **zero third-party API SDK dependencies**.

### 🔑 How API Keys Work (Bring Your Own Key - BYOK)

`triage` follows the standard **BYOK (Bring Your Own Key)** model:
- **Your Private Keys Stay Private:** The package **does NOT** include any API keys. When users install `triage-ai`, requests are made using **their own** API accounts directly to the respective AI provider.
- **Direct HTTPS Requests:** No intermediary servers or telemetry. The CLI connects directly from the user's terminal to the provider's official endpoint (e.g., `api.groq.com`, `api.openai.com`, or `generativelanguage.googleapis.com`) using Python's standard library.
- **100% Free Without Keys:** If no key is configured, `triage` automatically activates its **Deterministic Rule Engine** (`triage.grouper`), which clusters test failures, detects root causes (database errors, missing migrations, missing packages), and displays the full Rich terminal dashboard **completely free with zero setup**.

Configure one of the following in your project's `.env`, your global user config (`~/.triage/.env`), or as system environment variables:

```ini
# 1. Groq (Recommended: ~400ms ultra-low latency, free tier available at console.groq.com)
GROQ_API_KEY=gsk_your_groq_api_key_here

# 2. OpenAI (GPT-4o-mini: platform.openai.com)
OPENAI_API_KEY=sk-proj-your_openai_api_key_here

# 3. Google Gemini (Gemini-2.0-Flash: aistudio.google.com)
GEMINI_API_KEY=AIzaSy_your_gemini_api_key_here
```

> **⚙ Offline & Zero-Key Fallback:** If you don't have an AI key set, `triage` automatically runs its rule-based engine. It **never crashes**, never blocks, and requires zero paid subscriptions.

---

## CLI Reference & Usage Examples

### 1. Execute Test Commands (`run`)
Runs your test suite, captures stdout/stderr, and immediately triggers the root cause analyzer if tests fail:

```bash
# Run pytest
triage run "pytest"

# Run Django tests
triage run "python manage.py test --settings=myproject.settings.test"

# Run specific test file
triage run "pytest tests/test_orders.py"
```

### 2. Analyze Saved Logs or Piped Input (`analyze`)
```bash
# Analyze a test log file
triage analyze failures.log

# Pipe test output directly
pytest | triage
```

### 3. Generate Executable Fix Scripts
Auto-generate a shell script (`.sh` or `.ps1`) containing actionable remediation steps (e.g., `pip install stripe`, `python manage.py migrate`):

```bash
# PowerShell fix script
triage run "pytest" --export-script fix.ps1

# Bash fix script
triage run "pytest" --export-script fix.sh
```

### 4. Filter by Priority & Alternate Formats
```bash
# Show only HIGH priority root cause groups
triage run "pytest" --priority HIGH

# Output clean JSON for automation tools
triage run "pytest" --format json

# Output GitHub-flavored Markdown for CI summaries
triage run "pytest" --format markdown
```

---

## Publishing to PyPI (Maintainer Guide)

### What is PyPI?
The **Python Package Index (PyPI)** ([pypi.org](https://pypi.org)) is the official repository for Python packages. Publishing packages to PyPI is **100% free and open source**.

When published, any developer in the world can install this package simply with:
```bash
pip install triage-ai
```

### Release Steps for Maintainers

1. **Create an account & token on PyPI:**
   - Register at [pypi.org](https://pypi.org) and enable 2FA.
   - Generate an API token under **Account Settings → API tokens**.

2. **Install Build Tools:**
   ```bash
   pip install --upgrade build twine
   ```

3. **Bump the Version:**
   Update the `version` field in `pyproject.toml` (e.g., `0.1.0` -> `0.1.1`). PyPI does not permit re-uploading an existing version number.

4. **Build the Distribution Package:**
   ```bash
   # Remove stale build artifacts
   # On Windows:
   Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue
   # On Linux/macOS:
   rm -rf dist/

   # Build sdist (.tar.gz) and wheel (.whl)
   python -m build
   ```

5. **Verify the Build:**
   ```bash
   twine check dist/*
   ```

6. **(Optional) Test on TestPyPI Sandbox:**
   ```bash
   python -m twine upload --repository testpypi dist/*
   ```

7. **Upload to Production PyPI:**
   ```bash
   python -m twine upload dist/*
   ```
   - **Username:** `__token__`
   - **Password:** `<paste your pypi- API token>`

Your package will immediately be live at: `https://pypi.org/project/triage-ai/`!

---

## License

This project is licensed under the [MIT License](LICENSE).
