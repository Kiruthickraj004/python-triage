import sys
import io
import argparse
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from triage.parser import parse_test_output
from triage.grouper import pre_group_failures
from triage.models import ParsedRun
from triage.llm.client import get_llm_client, LLMClient, MockProvider
from triage.llm.validator import TriageResult, AnalyzedGroup
from triage.exporter import export_json, export_markdown, export_fix_script
from triage.runner import run_test_command

# Ensure UTF-8 output on Windows terminals
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console(force_terminal=True, legacy_windows=False)

PRIORITY_BADGES = {
    "HIGH": "[bold white on red] HIGH PRIORITY [/]",
    "MEDIUM": "[bold black on yellow] MEDIUM [/]",
    "LOW": "[bold white on green] LOW [/]",
}


def render_triage_dashboard(
    run: ParsedRun,
    triage_result: TriageResult,
    priority_filter: Optional[str] = None,
) -> None:
    """Render a structured, color-coded triage dashboard in the terminal."""
    if not run.failures:
        console.print("\n[bold green][PASS] All tests passed or no failures detected![/bold green]\n")
        return

    groups = triage_result.groups
    if priority_filter:
        groups = [g for g in groups if g.priority.upper() == priority_filter.upper()]

    console.print()
    banner = Text()
    banner.append("[TRIAGE] TEST FAILURE ROOT-CAUSE ANALYZER\n", style="bold cyan")
    banner.append(f"Framework: {run.framework.upper()}  •  ", style="dim")
    banner.append(f"{len(run.failures)} Total Failures  •  ", style="bold red")
    banner.append(f"{len(groups)} Root Cause Groups", style="bold yellow")
    if run.duration_str:
        banner.append(f"  •  Duration: {run.duration_str}", style="dim")

    # Mode and latency
    if not triage_result.is_fallback and triage_result.provider != "deterministic":
        banner.append(f"\n⚡ Mode: AI Diagnostics ({triage_result.provider.upper()})", style="bold green")
        if triage_result.latency_ms > 0:
            banner.append(f" in {int(triage_result.latency_ms)}ms", style="dim green")
    else:
        banner.append("\n⚙ Mode: Deterministic Rule Engine", style="dim cyan")
        banner.append("  (Set GROQ_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY for deep AI diagnostics)", style="dim italic")

    if priority_filter:
        banner.append(f"  [Filter: {priority_filter.upper()} Priority Only]", style="bold magenta")

    console.print(Panel(banner, border_style="cyan"))

    # Show guardrail warnings if auto-repair occurred
    if triage_result.validation_warnings and not triage_result.is_fallback:
        for w in triage_result.validation_warnings:
            console.print(f"[bold yellow]🛡 Guardrail:[/] [dim]{w}[/dim]")
        console.print()

    # Render summary table
    summary_table = Table(title="Root Cause Clusters Summary", border_style="dim")
    summary_table.add_column("Group", style="bold cyan", justify="center", width=8)
    summary_table.add_column("Priority", justify="center", width=18)
    summary_table.add_column("Root Cause", style="bold white")
    summary_table.add_column("Failures", justify="center", style="bold red", width=10)
    summary_table.add_column("Confidence", justify="center", style="green", width=12)

    for g in groups:
        summary_table.add_row(
            f"#{g.group_id}",
            PRIORITY_BADGES.get(g.priority, g.priority),
            g.root_cause,
            str(g.count),
            f"{int(g.confidence * 100)}%",
        )

    console.print(summary_table)
    console.print()

    # Detailed Group Cards
    for g in groups:
        title_text = f"Group #{g.group_id} — {g.root_cause} ({g.count} {'test' if g.count == 1 else 'tests'} affected)"
        border_col = "red" if g.priority == "HIGH" else ("yellow" if g.priority == "MEDIUM" else "green")

        card = Tree(f"[bold]{title_text}[/bold]")

        # Explanation
        if g.explanation:
            card.add(f"[bold dim]Explanation:[/] [white]{g.explanation}[/]")

        # Suggested Fix
        if g.suggested_fix:
            card.add(f"[bold green]Suggested Fix:[/] [bold cyan]{g.suggested_fix}[/]")

        # Affected Tests Tree
        tests_branch = card.add(f"[bold dim]Affected Tests ({len(g.affected_tests)}):[/]")
        for tid in g.affected_tests[:6]:
            if "::" in tid:
                file_p, t_name = tid.split("::", 1)
                tests_branch.add(f"[dim]{file_p}[/] :: [bold red]{t_name}[/]")
            else:
                tests_branch.add(f"[bold red]{tid}[/]")

        if len(g.affected_tests) > 6:
            tests_branch.add(f"[italic dim]... and {len(g.affected_tests) - 6} more tests[/]")

        # Representative Traceback preview
        if g.representative_traceback:
            tb_lines = g.representative_traceback.strip().splitlines()
            preview = "\n".join(tb_lines[-4:])
            tb_branch = card.add("[bold dim]Representative Traceback Excerpt:[/]")
            tb_branch.add(f"[dim white]{preview}[/]")

        console.print(Panel(card, border_style=border_col, padding=(0, 1)))

    console.print()


def execute_triage_pipeline(
    raw_output: str,
    provider_name: Optional[str] = None,
    force_deterministic: bool = False,
    output_format: str = "rich",
    priority_filter: Optional[str] = None,
    export_script_path: Optional[str] = None,
    exit_code_hint: Optional[int] = None,
) -> int:
    """Execute parsing, grouping, LLM triage, and handle formatting / script export."""
    parsed = parse_test_output(raw_output)

    if not parsed.failures:
        if exit_code_hint is not None and exit_code_hint != 0:
            console.print(f"\n[bold red][FAIL] Test command failed with exit code {exit_code_hint}, but no structured test failures were recognized.[/bold red]\n")
            return exit_code_hint
        if output_format == "json":
            print(export_json(TriageResult(summary="All tests passed.", groups=[]), parsed))
        elif output_format == "markdown":
            print(export_markdown(TriageResult(summary="All tests passed.", groups=[]), parsed))
        else:
            console.print("\n[bold green][PASS] All tests passed or no failures detected![/bold green]\n")
        return 0

    pre_groups = pre_group_failures(parsed.failures)

    if force_deterministic:
        from triage.llm.validator import TriageValidator
        validator = TriageValidator(pre_groups)
        triage_result = validator.fallback_to_deterministic("Forced deterministic mode via CLI flag")
    else:
        llm_client = get_llm_client(provider_name)
        with console.status("[bold cyan]Triaging test failures with AI...[/bold cyan]", spinner="dots"):
            triage_result = llm_client.triage(pre_groups, framework=parsed.framework)

    # Export fix script if requested
    if export_script_path:
        script_file = export_fix_script(triage_result, export_script_path)
        console.print(f"[bold green]✔ Generated fix script:[/] [bold cyan]{script_file}[/bold cyan]")

    # Output formatting
    if output_format == "json":
        print(export_json(triage_result, parsed))
    elif output_format == "markdown":
        print(export_markdown(triage_result, parsed))
    else:
        render_triage_dashboard(parsed, triage_result, priority_filter=priority_filter)

    return 1


def main():
    parser = argparse.ArgumentParser(
        prog="triage",
        description="AI-powered & deterministic test failure root-cause analyzer for Python & Django",
        epilog="""
AI Configuration (Bring Your Own Key):
  Triage uses your own API key to generate deep AI diagnostics and fix suggestions.
  Supported providers: Groq (GROQ_API_KEY), OpenAI (OPENAI_API_KEY), Google Gemini (GEMINI_API_KEY).
  
  Set your key in:
    • Local project:      ./.env
    • Global system:       ~/.triage/.env (Linux/macOS) or %USERPROFILE%\\.triage\\.env (Windows)
    • Environment var:    export GROQ_API_KEY="your-key"

  If no key is configured, triage automatically runs in 100% free deterministic mode.
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--mock", action="store_true", help="Force mock LLM provider for offline demo")
    parser.add_argument("--deterministic", action="store_true", help="Force deterministic rule engine only")
    parser.add_argument("--format", choices=["rich", "json", "markdown"], default="rich", help="Output format")
    parser.add_argument("--priority", choices=["HIGH", "MEDIUM", "LOW"], help="Filter display by priority")
    parser.add_argument("--export-script", help="Generate runnable fix script file (e.g. fix.ps1 or fix.sh)")

    subparsers = parser.add_subparsers(dest="command")

    # Command: triage analyze <file>
    analyze_parser = subparsers.add_parser("analyze", help="Analyze test failure log file or stdin")
    analyze_parser.add_argument("file", nargs="?", help="Path to raw test output log file (defaults to stdin)")
    analyze_parser.add_argument("--mock", action="store_true", help="Force mock LLM provider for offline demo")
    analyze_parser.add_argument("--deterministic", action="store_true", help="Force deterministic rule engine only")
    analyze_parser.add_argument("--format", choices=["rich", "json", "markdown"], default="rich", help="Output format")
    analyze_parser.add_argument("--priority", choices=["HIGH", "MEDIUM", "LOW"], help="Filter display by priority")
    analyze_parser.add_argument("--export-script", help="Generate runnable fix script file")

    # Command: triage run <command>
    run_parser = subparsers.add_parser("run", help="Run test command and triage failures")
    run_parser.add_argument("test_command", help="Command to run, e.g. 'pytest' or 'python manage.py test'")
    run_parser.add_argument("--mock", action="store_true", help="Force mock LLM provider for offline demo")
    run_parser.add_argument("--deterministic", action="store_true", help="Force deterministic rule engine only")
    run_parser.add_argument("--format", choices=["rich", "json", "markdown"], default="rich", help="Output format")
    run_parser.add_argument("--priority", choices=["HIGH", "MEDIUM", "LOW"], help="Filter display by priority")
    run_parser.add_argument("--export-script", help="Generate runnable fix script file")

    args = parser.parse_args()

    provider_name = "mock" if getattr(args, "mock", False) else None
    force_det = getattr(args, "deterministic", False)
    fmt = getattr(args, "format", "rich")
    p_filter = getattr(args, "priority", None)
    script_out = getattr(args, "export_script", None)

    # If no subcommand provided, check if input is piped into stdin
    if not args.command:
        if not sys.stdin.isatty():
            raw_input = sys.stdin.read()
            exit_code = execute_triage_pipeline(
                raw_input,
                provider_name=provider_name,
                force_deterministic=force_det,
                output_format=fmt,
                priority_filter=p_filter,
                export_script_path=script_out,
            )
            sys.exit(exit_code)
        else:
            parser.print_help()
            sys.exit(1)

    if args.command == "analyze":
        if args.file:
            path = Path(args.file)
            if not path.exists():
                console.print(f"[bold red]Error:[/] File not found: {args.file}")
                sys.exit(1)
            raw_input = path.read_text(encoding="utf-8")
        else:
            if sys.stdin.isatty():
                console.print("[bold yellow]Waiting for test output from stdin (press Ctrl+Z / Ctrl+D when finished)...[/]")
            raw_input = sys.stdin.read()

        exit_code = execute_triage_pipeline(
            raw_input,
            provider_name=provider_name,
            force_deterministic=force_det,
            output_format=fmt,
            priority_filter=p_filter,
            export_script_path=script_out,
        )
        sys.exit(exit_code)

    elif args.command == "run":
        console.print(f"[bold cyan]Running:[/] [dim]{args.test_command}[/dim]\n")
        exit_code, captured_output = run_test_command(args.test_command)

        if exit_code != 0:
            console.print("\n[bold yellow]Tests failed! Intercepting output for Triage...[/bold yellow]")
            execute_triage_pipeline(
                captured_output,
                provider_name=provider_name,
                force_deterministic=force_det,
                output_format=fmt,
                priority_filter=p_filter,
                export_script_path=script_out,
                exit_code_hint=exit_code,
            )
            sys.exit(exit_code)
        else:
            console.print("\n[bold green][PASS] All tests passed![/bold green]")
            sys.exit(0)


if __name__ == "__main__":
    main()
