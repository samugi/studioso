"""
quiz.py — Quiz mode: agent asks questions, user answers, agent evaluates.
"""

import random
import threading
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

    default_n = agent.config.get("default_quiz_length", 10)
    session = PromptSession(style=PROMPT_STYLE)

    try:
        n_input = session.prompt(f"How many questions? (default: {default_n}) › ").strip()
        n_questions = int(n_input) if n_input.isdigit() and int(n_input) > 0 else default_n
    except (KeyboardInterrupt, EOFError):
        return

    console.print(f"\n[dim]Starting quiz: {n_questions} questions. Good luck! 🎯[/dim]\n")

    # Pre-generate queues: each entry is (question_text, chunks) or (eval_text, error)
    next_question_text = None
    next_question_chunks = None
    next_question_error = None
    next_question_ready = False
    next_q_lock = threading.Lock()

    current_eval_text = None
    current_eval_error = None
    current_eval_ready = False
    current_eval_lock = threading.Lock()

    # Stats
    correct = 0
    partial = 0
    wrong = 0
    skipped = 0
    previous_questions: list[str] = []

    def generate_next_question():
        nonlocal next_question_text, next_question_chunks, next_question_error, next_question_ready

        try:
            all_chunks = rag.get_all_chunks_sample(n=15)
            if not all_chunks:
                return

            random.shuffle(all_chunks)
            question_chunks = all_chunks[:5]
            question = agent.generate_question(question_chunks, previous_questions)

            with next_q_lock:
                next_question_text = question
                next_question_chunks = question_chunks
                next_question_error = None
                next_question_ready = True

        except Exception as e:
            with next_q_lock:
                next_question_error = str(e)
                next_question_ready = True

    def generate_next_evaluation(question: str, user_answer: str, eval_chunks: list[dict]):
        nonlocal current_eval_text, current_eval_error, current_eval_ready

        try:
            system = agent._build_reference_mode_system_prompt(eval_chunks, mode="quiz-evaluation")
            prompt = f"""Domanda del Quiz: {question}

Risposta dell'utente: {user_answer}

Valuta questa risposta basandoti rigorosamente sul contesto del materiale di studio fornito.

- La risposta è corretta, parzialmente corretta o errata?
- Cosa ha risposto correttamente l'utente?
- Cosa ha omesso o sbagliato?
- Qual è la risposta corretta o completa secondo il materiale di origine?
- Fai riferimento allo specifico documento sorgente.

Sii incoraggiante ma preciso. Non considerare risposte vaghe o incomplete come completamente corrette."""

            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ]

            response = agent._client.chat(
                model=agent.ollama_model,
                messages=messages,
                options={"temperature": 0.2, "num_predict": 512},
            )

            with current_eval_lock:
                current_eval_text = response.message.content
                current_eval_error = None
                current_eval_ready = True

        except Exception as e:
            with current_eval_lock:
                current_eval_error = str(e)
                current_eval_ready = True

    for q_num in range(1, n_questions + 1):
        question = None
        question_chunks = None

        # Check if we have a pre-generated question
        with next_q_lock:
            if next_question_ready and next_question_text:
                # Use pre-generated question - don't run sync generation
                question = next_question_text
                question_chunks = next_question_chunks
                next_question_text = None
                next_question_chunks = None
                next_question_ready = False
            elif question:
                continue
            else:
                # Need to generate synchronously
                console.print(Rule(f"[yellow]Question {q_num} of {n_questions}[/yellow]", style="yellow"))
                console.print()

                all_chunks = rag.get_all_chunks_sample(n=15)
                if not all_chunks:
                    console.print("[red]No study material indexed. Cannot generate questions.[/red]")
                    break

                random.shuffle(all_chunks)
                question_chunks = all_chunks[:5]

                with console.status("[dim]Generating question...[/dim]", spinner="dots"):
                    question = agent.generate_question(question_chunks, previous_questions)

                # Start background thread for next question
                thread = threading.Thread(target=generate_next_question)
                thread.daemon = True
                thread.start()

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
        is_wrong = any(w in eval_lower for w in ["incorrect", "wrong", "not correct", "unfortunately"])
        is_partial = any(w in eval_lower for w in ["partially", "partly", "almost", "close", "incomplete"])
        is_correct = not is_wrong and not is_partial

        if is_wrong:
            wrong += 1
            console.print("\n[red]✗ Keep studying this one![/red]")
            # Pre-generate evaluation for this question (in case it was wrong)
            thread_eval = threading.Thread(
                target=generate_next_evaluation,
                args=(question, user_answer, eval_chunks)
            )
            thread_eval.daemon = True
            thread_eval.start()
        elif is_partial:
            partial += 1
            console.print("\n[yellow]◑ Almost there![/yellow]")
        else:
            correct += 1
            console.print("\n[green]✓ Well done![/green]")

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
