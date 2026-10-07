import sys
import io
import argparse
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from triage.parser import parse_test_output
from triage.grouper import pre_group_failures
from triage.models import ParsedRun, PreGroup

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

PRIORITY_COLORS = {
    "HIGH": "bold red",
    "MEDIUM": "bold yellow",
    "LOW": "bold green",
}

PRIORITY_BADGES = {
    "HIGH": "[bold white on red] HIGH PRIORITY [/]",
    "MEDIUM": "[bold black on yellow] MEDIUM [/]",
    "LOW": "[bold white on green] LOW [/]",
}


def render_triage_dashboard(run: ParsedRun) -> None:
    """Render a structured, color-coded triage dashboard in the terminal."""
    if not run.failures:
        console.print("\n[bold green][PASS] All tests passed or no failures detected![/bold green]\n")
        return

    groups = pre_group_failures(run.failures)

    console.print()
    banner = Text()
    banner.append("[TRIAGE] AI & DETERMINISTIC TEST FAILURE ANALYZER\n", style="bold cyan")
    banner.append(f"Framework: {run.framework.upper()}  •  ", style="dim")
    banner.append(f"{len(run.failures)} Total Failures  •  ", style="bold red")
    banner.append(f"Condensed into {len(groups)} Root Cause Groups", style="bold yellow")
    if run.duration_str:
        banner.append(f"  •  Duration: {run.duration_str}", style="dim")

    console.print(Panel(banner, border_style="cyan"))

    # Render summary table
    summary_table = Table(title="Root Cause Clusters Summary", border_style="dim")
    summary_table.add_column("Group", style="bold cyan", justify="center", width=8)
    summary_table.add_column("Priority", justify="center", width=18)
    summary_table.add_column("Root Cause Category", style="bold white")
    summary_table.add_column("Failures", justify="center", style="bold red", width=10)
    summary_table.add_column("Files", justify="center", style="dim", width=8)
    summary_table.add_column("Confidence", justify="center", style="green", width=12)

    for g in groups:
        summary_table.add_row(
            f"#{g.group_id}",
            PRIORITY_BADGES.get(g.priority, g.priority),
            g.category,
            str(g.count),
            str(len(g.affected_files)),
            f"{int(g.confidence * 100)}%",
        )

    console.print(summary_table)
    console.print()

    # Detailed Group Cards
    for g in groups:
        title_text = f"Group #{g.group_id} — {g.category} ({g.count} {'test' if g.count == 1 else 'tests'} affected)"
        border_col = "red" if g.priority == "HIGH" else ("yellow" if g.priority == "MEDIUM" else "green")

        card = Tree(f"[bold]{title_text}[/bold]")

        # Pattern
        card.add(f"[bold dim]Root Cause:[/] [white]{g.root_cause_pattern}[/]")

        # Suggested Fix
        if g.suggested_fix:
            card.add(f"[bold green]Suggested Fix:[/] [bold cyan]{g.suggested_fix}[/]")

        # Affected Tests Tree
        tests_branch = card.add(f"[bold dim]Affected Tests ({len(g.failures)}):[/]")
        for f in g.failures[:6]:  # Show top 6
            tests_branch.add(f"[dim]{f.file_path}[/] :: [bold red]{f.test_name}[/]")
        if len(g.failures) > 6:
            tests_branch.add(f"[italic dim]... and {len(g.failures) - 6} more tests[/]")

        # Representative Traceback preview
        if g.representative_traceback:
            tb_lines = g.representative_traceback.strip().splitlines()
            preview = "\n".join(tb_lines[-4:])  # Last 4 lines
            tb_branch = card.add("[bold dim]Representative Traceback (sampled 1 for LLM optimization):[/]")
            tb_branch.add(f"[dim white]{preview}[/]")

        console.print(Panel(card, border_style=border_col, padding=(0, 1)))

    console.print()


def main():
    parser = argparse.ArgumentParser(
        prog="triage",
        description="AI-powered & deterministic test failure root-cause analyzer for Python & Django",
    )
    subparsers = parser.add_subparsers(dest="command")

    # Command: triage analyze <file>
    analyze_parser = subparsers.add_parser("analyze", help="Analyze test failure log file or stdin")
    analyze_parser.add_argument("file", nargs="?", help="Path to raw test output log file (defaults to stdin)")

    # Command: triage run <command>
    run_parser = subparsers.add_parser("run", help="Run test command and triage failures")
    run_parser.add_argument("test_command", help="Command to run, e.g. 'pytest' or 'python manage.py test'")

    args = parser.parse_args()

    # If no subcommand provided, check if input is piped into stdin
    if not args.command:
        if not sys.stdin.isatty():
            raw_input = sys.stdin.read()
            parsed = parse_test_output(raw_input)
            render_triage_dashboard(parsed)
            return
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

        parsed = parse_test_output(raw_input)
        render_triage_dashboard(parsed)

    elif args.command == "run":
        import subprocess
        console.print(f"[bold cyan]Running:[/] [dim]{args.test_command}[/dim]\n")
        proc = subprocess.run(args.test_command, shell=True, capture_output=True, text=True)
        # Print the live output
        if proc.stdout:
            sys.stdout.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)

        if proc.returncode != 0:
            console.print("\n[bold yellow]Tests failed! Intercepting output for Triage...[/bold yellow]")
            combined_output = (proc.stdout or "") + "\n" + (proc.stderr or "")
            parsed = parse_test_output(combined_output)
            render_triage_dashboard(parsed)
        else:
            console.print("\n[bold green]✔ Tests passed![/bold green]")


if __name__ == "__main__":
    main()
