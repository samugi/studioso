"""
quiz.py — Quiz mode: agent asks questions, user answers, agent evaluates.
"""

import random
import threading
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
            "[bold yellow]Quiz Mode[/bold yellow]\n"
            "[dim]The agent will ask you questions based on your study materials.\n"
            "Answer each question, then get instant feedback.\n"
            "Type [bold]/back[/bold] to return to the menu, [bold]/skip[/bold] to skip a question.[/dim]",
            border_style="yellow",
            expand=False,
        )
    )
    console.print()

    default_n = agent.config.get("default_quiz_length", 10)
    session = PromptSession(style=PROMPT_STYLE)

    try:
        n_input = session.prompt(
            f"How many questions? (default: {default_n}) › "
        ).strip()
        n_questions = (
            int(n_input) if n_input.isdigit() and int(n_input) > 0 else default_n
        )
    except (KeyboardInterrupt, EOFError):
        return

    console.print(
        f"\n[dim]Starting quiz: {n_questions} questions. Good luck! 🎯[/dim]\n"
    )

    # Pre-generate queues: (question_text, chunks, error) or (eval_text, error)
    next_q_text = None
    next_q_chunks = None
    next_q_error = None
    next_q_ready = False
    next_q_lock = threading.Lock()

    # Stats
    correct = 0
    partial = 0
    wrong = 0
    skipped = 0
    previous_questions: list[str] = []

    def generate_next_question():
        nonlocal next_q_text, next_q_chunks, next_q_error, next_q_ready

        try:
            all_chunks = rag.get_all_chunks_sample(n=15)
            if not all_chunks:
                return

            random.shuffle(all_chunks)
            question_chunks = all_chunks[:5]
            question = agent.generate_question(question_chunks, previous_questions)

            with next_q_lock:
                next_q_text = question
                next_q_chunks = question_chunks
                next_q_error = None
                next_q_ready = True

        except Exception as e:
            with next_q_lock:
                next_q_error = str(e)
                next_q_ready = True

    for q_num in range(1, n_questions + 1):
        question = None
        question_chunks = None

        # Check if we have a pre-generated question
        with next_q_lock:
            if next_q_ready and next_q_text:
                # Use pre-generated question
                question = next_q_text
                question_chunks = next_q_chunks
                next_q_text = None
                next_q_chunks = None
                next_q_ready = False
                # Clear error if any
                if next_q_error:
                    next_q_error = None
            elif question:
                continue
            else:
                # Need to generate synchronously
                console.print(
                    Rule(
                        f"[yellow]Question {q_num} of {n_questions}[/yellow]",
                        style="yellow",
                    )
                )
                console.print()

                all_chunks = rag.get_all_chunks_sample(n=15)
                if not all_chunks:
                    console.print(
                        "[red]No study material indexed. Cannot generate questions.[/red]"
                    )
                    break

                random.shuffle(all_chunks)
                question_chunks = all_chunks[:5]

                with console.status(
                    "[dim]Generating question...[/dim]", spinner="dots"
                ):
                    question = agent.generate_question(
                        question_chunks, previous_questions
                    )

                # Start background thread for next question (async pre-loading)
                thread = threading.Thread(target=generate_next_question)
                thread.daemon = True
                thread.start()

        previous_questions.append(question)

        console.print(
            Panel(
                Markdown(question),
                title=f"[yellow bold]Question {q_num}[/yellow bold]",
                border_style="yellow",
            )
        )
        console.print()

        # Get user answer
        try:
            user_answer = session.prompt("Your answer › ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Quiz interrupted.[/dim]")
            break

        if not user_answer:
            console.print("[dim]No answer provided. Skipping.[/dim]")
            skipped += 1
            continue

        if user_answer.lower() in ("/skip", "/s"):
            console.print("[dim]Skipped.[/dim]")
            skipped += 1
            continue

        if user_answer.lower() in ("/back", "/exit", "/quit", "/menu"):
            break

        # Retrieve relevant context for evaluation
        with console.status("[dim]Evaluating your answer...[/dim]", spinner="dots"):
            eval_chunks = rag.retrieve(question)
            if not eval_chunks:
                eval_chunks = question_chunks

        # Evaluate the answer (synchronous - wait for response)
        console.print()
        console.print("[bold green]Feedback ›[/bold green]")

        full_eval = ""
        try:
            for token in agent.evaluate_answer_stream(
                question, user_answer, eval_chunks
            ):
                console.print(token, end="", markup=False)
                full_eval += token
            console.print()
        except Exception as e:
            console.print(f"\n[red]Error getting evaluation: {e}[/red]")
            continue

        # Parse result using first word (as defined in AGENT.md)
        full_eval_stripped = full_eval.strip()
        eval_lower = full_eval_stripped.lower()

        is_correct = False
        is_wrong = False
        is_partial = False

        # Check what the response starts with (per AGENT.md specification)
        if eval_lower.startswith("corretto") or eval_lower.startswith("giusta"):
            is_correct = True
        elif eval_lower.startswith("sbagliato") or eval_lower.startswith("errata"):
            is_wrong = True
        elif eval_lower.startswith("parzialmente"):
            is_partial = True
        else:
            # Default to correct if format is unclear (safety fallback)
            is_correct = True

        if is_wrong:
            wrong += 1
            console.print(
                "\n[red]✗ Risposta errata: continua a studiare questo argomento![/red]"
            )
        elif is_partial:
            partial += 1
            console.print(
                "\n[yellow]◑ Parzialmente corretto: c'è ancora qualcosa da migliorare![/yellow]"
            )
        else:
            correct += 1
            console.print("\n[green]✓ Risposta corretta! Bravo![/green]")

        console.print()

        # Ask if they want to continue (only if not last question)
        if q_num < n_questions:
            try:
                input("Press Enter for next question (or /back to quit) › ").strip()
            except (KeyboardInterrupt, EOFError):
                break

    # Summary
    console.print()
    console.print(Rule("[yellow]Quiz Complete[/yellow]", style="yellow"))
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
                f"  [bold]Punteggio: {score_pct}%[/bold]  {'🎉 Ottimo!' if score_pct >= 80 else '📚 Continua a studiare!' if score_pct >= 50 else '💪 Hai bisogno di più pratica!'}",
                title="[yellow bold]Riepilogo[/yellow bold]",
                border_style="yellow",
            )
        )
    else:
        console.print("[dim]Nessuna domanda risposta.[/dim]")

    console.print()
