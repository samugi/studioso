"""
cli.py — Main CLI interface: startup checks, menu, mode dispatch.
"""

import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.rule import Rule
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style

console = Console()

MENU_STYLE = Style.from_dict({
    "prompt": "#aaaaaa",
})

BANNER = """
[bold cyan]
 ╔═══════════════════════════════╗
 ║        STUDY  AGENT          ║
 ╚═══════════════════════════════╝
[/bold cyan][dim]  Powered by Ollama · Grounded in your documents[/dim]
"""


def print_banner():
    console.print(BANNER)


def print_status_table(config: dict, rag_count: int, files: list[str], ollama_ok: bool):
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("key", style="dim")
    table.add_column("value", style="bold")

    table.add_row("Study material", str(Path(config["study_material"]).resolve()))
    table.add_row("Model", config.get("ollama_model", "?"))
    table.add_row("Ollama", "[green]Running ✓[/green]" if ollama_ok else "[red]Not running ✗[/red]")
    table.add_row("Indexed chunks", str(rag_count))

    if files:
        table.add_row("Documents", ", ".join(files[:3]) + (f" (+{len(files)-3} more)" if len(files) > 3 else ""))
    else:
        table.add_row("Documents", "[yellow]None indexed[/yellow]")

    console.print(Panel(table, title="[dim]Status[/dim]", border_style="dim", expand=False))
    console.print()


def run_setup_check(agent, rag) -> bool:
    """Run startup checks: Ollama, model, study folder. Returns True if ready."""
    console.print("[dim]Running startup checks...[/dim]")
    console.print()

    all_ok = True

    # Check Ollama
    ollama_ok, info = agent.check_ollama()
    if not ollama_ok:
        console.print("[red]✗ Ollama is not running.[/red]")
        console.print("  Start it with: [bold]ollama serve[/bold]")
        console.print(f"  Error: {info}")
        all_ok = False
    else:
        # Check model
        available = info  # list of model names when ollama is ok
        model = agent.ollama_model
        def normalize(n): return n.split(":")[0]
        model_found = any(normalize(m) == normalize(model) for m in available)

        if model_found:
            console.print(f"[green]✓ Ollama is running and model '{model}' is available.[/green]")
        else:
            console.print(f"[yellow]⚠ Model '{model}' was not found locally.[/yellow]")
            console.print(f"  Available models: {', '.join(available) if available else 'none'}")
            console.print(f"  Pulling '{model}' from Ollama... (the first download may take a few minutes)")
            console.print()
            try:
                last_status = ""
                for status in agent.pull_model_stream():
                    if status and status != last_status:
                        console.print(f"  [dim]{status}[/dim]", end="\r")
                        last_status = status
                console.print(f"\n[green]✓ Model '{model}' downloaded.[/green]")
            except Exception as e:
                console.print(f"\n[red]Model download failed: {e}[/red]")
                console.print(f"  Try manually: [bold]ollama pull {model}[/bold]")
                all_ok = False

    study_material = Path(agent.config["study_material"]).resolve()
    if not study_material.exists():
        console.print(f"[yellow]⚠ Study material path does not exist: {study_material}[/yellow]")
        if study_material.suffix:
            console.print("  [dim]This path looks like a file. Check that it exists or point to a valid folder.[/dim]")
        else:
            console.print("  Creating the folder for you...")
            study_material.mkdir(parents=True, exist_ok=True)
            console.print(f"  [green]✓ Created: {study_material}[/green]")
            console.print("  [dim]Add your study documents and restart, or use /reindex.[/dim]")
    else:
        label = "Study file" if study_material.is_file() else "Study folder"
        console.print(f"[green]✓ {label}: {study_material}[/green]")

    console.print()

    if not all_ok:
        console.print("[red]Some startup checks failed. Fix the issues and restart.[/red]")
        return False

    # Ingest documents
    count_before = rag.collection_count()
    console.print("[dim]Scanning for new or updated documents...[/dim]")
    new_chunks = rag.ingest()

    if new_chunks > 0:
        console.print(f"[green]✓ Indexed {new_chunks} new chunks from your documents.[/green]")
    elif count_before > 0:
        console.print(f"[green]✓ Documents already indexed ({count_before} chunks). No changes detected.[/green]")
    else:
        console.print(f"[yellow]⚠ No documents found in {study_material}[/yellow]")
        console.print(f"  Add PDF, DOCX, TXT, or MD files and use [bold]/reindex[/bold].")

    console.print()
    return True


def run_menu(agent, rag):
    from src.modes.qa import run_qa_mode
    from src.modes.quiz import run_quiz_mode, run_review_mode

    print_banner()

    ready = run_setup_check(agent, rag)
    if not ready:
        console.print("[dim]Press Enter to exit, or fix the issues and restart.[/dim]")
        input()
        sys.exit(1)

    ollama_ok, _ = agent.check_ollama()
    print_status_table(
        config=agent.config,
        rag_count=rag.collection_count(),
        files=rag.indexed_files(),
        ollama_ok=ollama_ok,
    )

    if not sys.stdin.isatty():
        console.print("[dim]Non-interactive session detected. Startup completed.[/dim]")
        return

    session = PromptSession(style=MENU_STYLE)

    while True:
        console.print(Panel(
            "[bold cyan][1][/bold cyan] Reference Mode — Ask questions about your material\n"
            "[bold yellow][2][/bold yellow] Quiz Mode — Let the agent quiz you\n"
            "[bold magenta][3][/bold magenta] Review Mode — Revisit missed questions\n"
            "[bold dim][4][/bold dim] [dim]Reindex   — Reload documents from the study material[/dim]\n"
            "[bold dim][5][/bold dim] [dim]Status    — Show the current configuration[/dim]\n"
            "[bold dim][q][/bold dim] [dim]Exit[/dim]",
            title="[bold]Main Menu[/bold]",
            border_style="bright_black",
            expand=False,
        ))

        try:
            choice = session.prompt("Choice › ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            break

        if choice in ("1", "qa", "q&a", "ask"):
            if rag.collection_count() == 0:
                console.print("[yellow]⚠ No documents are indexed yet. Add files to the study folder first.[/yellow]\n")
                continue
            run_qa_mode(agent, rag)

        elif choice in ("2", "quiz", "test"):
            if rag.collection_count() == 0:
                console.print("[yellow]⚠ No documents are indexed yet. Add files to the study folder first.[/yellow]\n")
                continue
            run_quiz_mode(agent, rag)

        elif choice in ("3", "review", "ripasso"):
            if rag.collection_count() == 0:
                console.print("[yellow]⚠ No documents are indexed yet. Add files to the study material first.[/yellow]\n")
                continue
            run_review_mode(agent, rag)

        elif choice in ("4", "reindex", "r"):
            console.print()
            console.print("[dim]Reindexing all documents...[/dim]")
            new_chunks = rag.ingest(force=True)
            console.print(f"[green]✓ Done. {new_chunks} chunks indexed.[/green]\n")

        elif choice in ("5", "status", "s"):
            ollama_ok, _ = agent.check_ollama()
            print_status_table(
                config=agent.config,
                rag_count=rag.collection_count(),
                files=rag.indexed_files(),
                ollama_ok=ollama_ok,
            )

        elif choice in ("q", "quit", "exit", "bye"):
            break

        else:
            console.print("[dim]Type 1, 2, 3, 4, 5, or q[/dim]\n")

    console.print("\n[dim]Goodbye. Happy studying.[/dim]\n")
