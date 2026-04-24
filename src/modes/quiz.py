"""
quiz.py — Quiz mode: agent asks questions, user answers, agent evaluates.
"""

import random
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style

from src.agent import StudyAgent
from src.rag import RAGEngine

console = Console()

PROMPT_STYLE = Style.from_dict(
    {
        "prompt": "#ffaa00 bold",
    }
)


def run_quiz_mode(agent: StudyAgent, rag: RAGEngine):
    console.print()
    console.print(
        Panel(
            "[bold yellow]Modalita Quiz[/bold yellow]\n"
            "[dim]L'agente ti fara domande basate sui tuoi materiali di studio.\n"
            "Rispondi e ricevi un feedback immediato.\n"
            "Comandi: [bold]/back[/bold] per tornare al menu, [bold]/skip[/bold] per saltare la domanda.[/dim]",
            border_style="yellow",
            expand=False,
        )
    )
    console.print()

    default_n = agent.config.get("default_quiz_length", 10)
    session = PromptSession(style=PROMPT_STYLE)

    try:
        n_input = session.prompt(f"Quante domande? (predefinito: {default_n}) › ").strip()
        n_questions = (
            int(n_input) if n_input.isdigit() and int(n_input) > 0 else default_n
        )
    except (KeyboardInterrupt, EOFError):
        return

    console.print(
        f"\n[dim]Avvio del quiz: {n_questions} domande.[/dim]\n"
    )

    # Stats
    correct = 0
    partial = 0
    wrong = 0
    skipped = 0
    previous_questions: list[str] = []

    for q_num in range(1, n_questions + 1):
        console.print(
            Rule(
                f"[yellow]Domanda {q_num} di {n_questions}[/yellow]",
                style="yellow",
            )
        )
        console.print()

        all_chunks = rag.get_all_chunks_sample(n=15)
        if not all_chunks:
            console.print(
                "[red]Nessun materiale di studio indicizzato. Impossibile generare domande.[/red]"
            )
            break

        random.shuffle(all_chunks)
        question_chunks = all_chunks[:5]

        with console.status("[dim]Generazione della domanda...[/dim]", spinner="dots"):
            question = agent.generate_question(question_chunks, previous_questions)

        previous_questions.append(question)

        console.print(
            Panel(
                Markdown(question),
                title=f"[yellow bold]Domanda {q_num}[/yellow bold]",
                border_style="yellow",
            )
        )
        console.print()

        # Get user answer
        try:
            user_answer = session.prompt("La tua risposta › ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Quiz interrotto.[/dim]")
            break

        if not user_answer:
            console.print("[dim]Nessuna risposta fornita. Domanda saltata.[/dim]")
            skipped += 1
            continue

        if user_answer.lower() in ("/skip", "/s"):
            console.print("[dim]Domanda saltata.[/dim]")
            skipped += 1
            continue

        if user_answer.lower() in ("/back", "/exit", "/quit", "/menu"):
            break

        # Retrieve relevant context for evaluation
        with console.status("[dim]Valutazione della risposta...[/dim]", spinner="dots"):
            eval_chunks = rag.retrieve(question)
            if not eval_chunks:
                eval_chunks = question_chunks

        # Evaluate the answer
        console.print()
        console.print("[bold green]Feedback[/bold green]")

        try:
            full_eval = agent.evaluate_answer(question, user_answer, eval_chunks)
            console.print(full_eval, markup=False)
        except Exception as e:
            console.print(f"\n[red]Errore durante la valutazione: {e}[/red]")
            continue

        label = agent.extract_quiz_feedback_label(full_eval)

        if label == "errato":
            wrong += 1
            console.print(
                "\n[red]✗ Classificazione: errato[/red]"
            )
        elif label == "parzialmente corretto":
            partial += 1
            console.print(
                "\n[yellow]◑ Classificazione: parzialmente corretto[/yellow]"
            )
        else:
            correct += 1
            console.print("\n[green]✓ Classificazione: corretto[/green]")

        console.print()

        if q_num < n_questions:
            try:
                next_step = session.prompt(
                    "Invio per la prossima domanda, /back per uscire › "
                ).strip()
                if next_step.lower() in ("/back", "/exit", "/quit", "/menu"):
                    break
            except (KeyboardInterrupt, EOFError):
                break

    # Summary
    console.print()
    console.print(Rule("[yellow]Quiz completato[/yellow]", style="yellow"))
    console.print()

    total_answered = correct + partial + wrong
    if total_answered > 0:
        score_pct = int(100 * (correct + 0.5 * partial) / total_answered)
        console.print(
            Panel(
                f"[bold]Risultati:[/bold]\n\n"
                f"  [green]✓ Corrette:          {correct}[/green]\n"
                f"  [yellow]◑ Parzialmente corrette: {partial}[/yellow]\n"
                f"  [red]✗ Errate:            {wrong}[/red]\n"
                f"  [dim]  Saltate:           {skipped}[/dim]\n\n"
                f"  [bold]Punteggio: {score_pct}%[/bold]  {'Ottimo.' if score_pct >= 80 else 'Continua a studiare.' if score_pct >= 50 else 'Hai bisogno di piu pratica.'}",
                title="[yellow bold]Riepilogo[/yellow bold]",
                border_style="yellow",
            )
        )
    else:
        console.print("[dim]Nessuna domanda risposta.[/dim]")

    console.print()
