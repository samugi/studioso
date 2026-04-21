"""
quiz.py — Quiz mode: agent asks questions, user answers, agent evaluates.
"""

import random
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style

from src.agent import StudyAgent
from src.rag import RAGEngine

console = Console()

PROMPT_STYLE = Style.from_dict({
    "prompt": "#ffaa00 bold",
})


def run_quiz_mode(agent: StudyAgent, rag: RAGEngine):
    console.print()
    console.print(Panel(
        "[bold yellow]Quiz Mode[/bold yellow]\n"
        "[dim]The agent will ask you questions based on your study materials.\n"
        "Answer each question, then get instant feedback.\n"
        "Type [bold]/back[/bold] to return to the menu, [bold]/skip[/bold] to skip a question.[/dim]",
        border_style="yellow",
        expand=False,
    ))
    console.print()

    # Ask how many questions
    default_n = agent.config.get("default_quiz_length", 10)
    session = PromptSession(style=PROMPT_STYLE)

    try:
        n_input = session.prompt(f"How many questions? (default: {default_n}) › ").strip()
        n_questions = int(n_input) if n_input.isdigit() and int(n_input) > 0 else default_n
    except (KeyboardInterrupt, EOFError):
        return

    console.print(f"\n[dim]Starting quiz: {n_questions} questions. Good luck! 🎯[/dim]\n")

    # Stats
    correct = 0
    partial = 0
    wrong = 0
    skipped = 0
    previous_questions: list[str] = []

    for q_num in range(1, n_questions + 1):
        console.print(Rule(f"[yellow]Question {q_num} of {n_questions}[/yellow]", style="yellow"))
        console.print()

        # Get diverse chunks for question generation
        all_chunks = rag.get_all_chunks_sample(n=15)
        if not all_chunks:
            console.print("[red]No study material indexed. Cannot generate questions.[/red]")
            break

        # Randomize to get variety
        random.shuffle(all_chunks)
        question_chunks = all_chunks[:5]

        # Generate question
        with console.status("[dim]Generating question...[/dim]", spinner="dots"):
            try:
                question = agent.generate_question(question_chunks, previous_questions)
            except Exception as e:
                console.print(f"[red]Error generating question: {e}[/red]")
                break

        previous_questions.append(question)

        console.print(Panel(
            Markdown(question),
            title=f"[yellow bold]Question {q_num}[/yellow bold]",
            border_style="yellow",
        ))
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

        # Stream evaluation
        console.print()
        console.print("[bold green]Feedback ›[/bold green]")

        full_eval = ""
        try:
            for token in agent.evaluate_answer_stream(question, user_answer, eval_chunks):
                console.print(token, end="", markup=False)
                full_eval += token
            console.print()
        except Exception as e:
            console.print(f"\n[red]Error getting evaluation: {e}[/red]")
            continue

        # Parse result for scoring (simple heuristic)
        eval_lower = full_eval.lower()
        if any(w in eval_lower for w in ["incorrect", "wrong", "not correct", "unfortunately"]):
            wrong += 1
            console.print("\n[red]✗ Keep studying this one![/red]")
        elif any(w in eval_lower for w in ["partially", "partly", "almost", "close", "incomplete"]):
            partial += 1
            console.print("\n[yellow]◑ Almost there![/yellow]")
        else:
            correct += 1
            console.print("\n[green]✓ Well done![/green]")

        console.print()

        # Ask if they want to continue (only if not last question)
        if q_num < n_questions:
            try:
                cont = session.prompt("Press Enter for next question (or /back to quit) › ").strip()
                if cont.lower() in ("/back", "/exit", "/quit", "/menu"):
                    break
            except (KeyboardInterrupt, EOFError):
                break

    # Summary
    console.print()
    console.print(Rule("[yellow]Quiz Complete[/yellow]", style="yellow"))
    console.print()

    total_answered = correct + partial + wrong
    if total_answered > 0:
        score_pct = int(100 * (correct + 0.5 * partial) / total_answered)
        console.print(Panel(
            f"[bold]Results:[/bold]\n\n"
            f"  [green]✓ Correct:          {correct}[/green]\n"
            f"  [yellow]◑ Partially correct: {partial}[/yellow]\n"
            f"  [red]✗ Wrong:            {wrong}[/red]\n"
            f"  [dim]  Skipped:           {skipped}[/dim]\n\n"
            f"  [bold]Score: {score_pct}%[/bold]  {'🎉 Great job!' if score_pct >= 80 else '📚 Keep studying!' if score_pct >= 50 else '💪 More practice needed!'}",
            title="[yellow bold]Summary[/yellow bold]",
            border_style="yellow",
        ))
    else:
        console.print("[dim]No questions answered.[/dim]")

    console.print()
