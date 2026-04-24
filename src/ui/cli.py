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
[/bold cyan][dim]  Powered by Ollama · Basato sui tuoi documenti[/dim]
"""


def print_banner():
    console.print(BANNER)


def print_status_table(config: dict, rag_count: int, files: list[str], ollama_ok: bool):
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("key", style="dim")
    table.add_column("value", style="bold")

    table.add_row("Cartella studio", str(Path(config["study_folder"]).resolve()))
    table.add_row("Modello", config.get("ollama_model", "?"))
    table.add_row("Ollama", "[green]Running ✓[/green]" if ollama_ok else "[red]Not running ✗[/red]")
    table.add_row("Chunk indicizzati", str(rag_count))

    if files:
        table.add_row("Documenti", ", ".join(files[:3]) + (f" (+{len(files)-3} altri)" if len(files) > 3 else ""))
    else:
        table.add_row("Documenti", "[yellow]Nessuno indicizzato[/yellow]")

    console.print(Panel(table, title="[dim]Status[/dim]", border_style="dim", expand=False))
    console.print()


def run_setup_check(agent, rag) -> bool:
    """Run startup checks: Ollama, model, study folder. Returns True if ready."""
    console.print("[dim]Controlli iniziali in corso...[/dim]")
    console.print()

    all_ok = True

    # Check Ollama
    ollama_ok, info = agent.check_ollama()
    if not ollama_ok:
        console.print("[red]✗ Ollama non e in esecuzione.[/red]")
        console.print("  Avvialo con: [bold]ollama serve[/bold]")
        console.print(f"  Errore: {info}")
        all_ok = False
    else:
        # Check model
        available = info  # list of model names when ollama is ok
        model = agent.ollama_model
        def normalize(n): return n.split(":")[0]
        model_found = any(normalize(m) == normalize(model) for m in available)

        if model_found:
            console.print(f"[green]✓ Ollama attivo, modello '{model}' disponibile.[/green]")
        else:
            console.print(f"[yellow]⚠ Modello '{model}' non trovato in locale.[/yellow]")
            console.print(f"  Modelli disponibili: {', '.join(available) if available else 'nessuno'}")
            console.print(f"  Scarico '{model}' da Ollama... (la prima volta puo richiedere alcuni minuti)")
            console.print()
            try:
                last_status = ""
                for status in agent.pull_model_stream():
                    if status and status != last_status:
                        console.print(f"  [dim]{status}[/dim]", end="\r")
                        last_status = status
                console.print(f"\n[green]✓ Modello '{model}' scaricato.[/green]")
            except Exception as e:
                console.print(f"\n[red]Download del modello non riuscito: {e}[/red]")
                console.print(f"  Prova manualmente: [bold]ollama pull {model}[/bold]")
                all_ok = False

    # Check study folder
    study_folder = Path(agent.config["study_folder"]).resolve()
    if not study_folder.exists():
        console.print(f"[yellow]⚠ La cartella di studio non esiste: {study_folder}[/yellow]")
        console.print("  La creo ora...")
        study_folder.mkdir(parents=True, exist_ok=True)
        console.print(f"  [green]✓ Creata: {study_folder}[/green]")
        console.print(f"  [dim]Aggiungi i documenti di studio e riavvia, oppure usa /reindex.[/dim]")
    else:
        console.print(f"[green]✓ Cartella di studio: {study_folder}[/green]")

    console.print()

    if not all_ok:
        console.print("[red]Alcuni controlli non sono andati a buon fine. Correggi i problemi e riavvia.[/red]")
        return False

    # Ingest documents
    count_before = rag.collection_count()
    console.print("[dim]Scansione dei documenti nuovi o aggiornati...[/dim]")
    new_chunks = rag.ingest()

    if new_chunks > 0:
        console.print(f"[green]✓ Indicizzati {new_chunks} nuovi chunk dai tuoi documenti.[/green]")
    elif count_before > 0:
        console.print(f"[green]✓ Documenti gia indicizzati ({count_before} chunk). Nessuna modifica rilevata.[/green]")
    else:
        console.print(f"[yellow]⚠ Nessun documento trovato in {study_folder}[/yellow]")
        console.print(f"  Aggiungi file PDF, DOCX, TXT o MD e usa [bold]/reindex[/bold].")

    console.print()
    return True


def run_menu(agent, rag):
    from src.modes.qa import run_qa_mode
    from src.modes.quiz import run_quiz_mode

    print_banner()

    ready = run_setup_check(agent, rag)
    if not ready:
        console.print("[dim]Premi Invio per uscire, oppure correggi i problemi e riavvia.[/dim]")
        input()
        sys.exit(1)

    ollama_ok, _ = agent.check_ollama()
    print_status_table(
        config=agent.config,
        rag_count=rag.collection_count(),
        files=rag.indexed_files(),
        ollama_ok=ollama_ok,
    )

    session = PromptSession(style=MENU_STYLE)

    while True:
        console.print(Panel(
            "[bold cyan][1][/bold cyan] Modalita Reference — Fai domande sui materiali\n"
            "[bold yellow][2][/bold yellow] Modalita Quiz — Lascia che l'agente ti interroghi\n"
            "[bold dim][3][/bold dim] [dim]Reindex   — Ricarica i documenti dalla cartella di studio[/dim]\n"
            "[bold dim][4][/bold dim] [dim]Stato     — Mostra la configurazione corrente[/dim]\n"
            "[bold dim][q][/bold dim] [dim]Esci[/dim]",
            title="[bold]Menu principale[/bold]",
            border_style="bright_black",
            expand=False,
        ))

        try:
            choice = session.prompt("Scelta › ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            break

        if choice in ("1", "qa", "q&a", "ask"):
            if rag.collection_count() == 0:
                console.print("[yellow]⚠ Nessun documento indicizzato. Aggiungi prima i file nella cartella di studio.[/yellow]\n")
                continue
            run_qa_mode(agent, rag)

        elif choice in ("2", "quiz", "test"):
            if rag.collection_count() == 0:
                console.print("[yellow]⚠ Nessun documento indicizzato. Aggiungi prima i file nella cartella di studio.[/yellow]\n")
                continue
            run_quiz_mode(agent, rag)

        elif choice in ("3", "reindex", "r"):
            console.print()
            console.print("[dim]Reindicizzazione completa dei documenti...[/dim]")
            new_chunks = rag.ingest(force=True)
            console.print(f"[green]✓ Fatto. {new_chunks} chunk indicizzati.[/green]\n")

        elif choice in ("4", "status", "s"):
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
            console.print("[dim]Digita 1, 2, 3, 4 oppure q[/dim]\n")

    console.print("\n[dim]Arrivederci. Buono studio.[/dim]\n")
