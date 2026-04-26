"""
quiz.py - Quiz and review modes.
"""

from __future__ import annotations

import random
import threading

from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule

from src.agent import StudyAgent
from src.rag import RAGEngine
from src.review_store import ReviewStore

console = Console()

PROMPT_STYLE = Style.from_dict({"prompt": "#ffaa00 bold"})


def _sample_question_context(rag: RAGEngine) -> list[dict]:
    all_chunks = rag.get_all_chunks_sample(n=15)
    if not all_chunks:
        return []
    random.shuffle(all_chunks)
    return all_chunks[:5]


class QuestionPrefetcher:
    def __init__(self, agent: StudyAgent, rag: RAGEngine):
        self.agent = agent
        self.rag = rag
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._ready_question: dict | None = None
        self._error: Exception | None = None

    def _generate(self, previous_questions: list[str]):
        try:
            question_chunks = _sample_question_context(self.rag)
            if not question_chunks:
                raise RuntimeError("No indexed study material found.")
            question = self.agent.generate_question(question_chunks, previous_questions)
            with self._lock:
                self._ready_question = {"text": question, "source_chunks": question_chunks}
                self._error = None
        except Exception as exc:
            with self._lock:
                self._ready_question = None
                self._error = exc
        finally:
            with self._lock:
                self._thread = None

    def start(self, previous_questions: list[str]):
        with self._lock:
            if self._thread is not None or self._ready_question is not None:
                return
            self._error = None
            self._thread = threading.Thread(
                target=self._generate,
                args=(list(previous_questions),),
                daemon=True,
            )
            self._thread.start()

    def consume(self, previous_questions: list[str]) -> dict:
        thread = None
        with self._lock:
            if self._ready_question is not None:
                result = self._ready_question
                self._ready_question = None
                return result
            thread = self._thread

        if thread is not None:
            thread.join()

        with self._lock:
            if self._ready_question is not None:
                result = self._ready_question
                self._ready_question = None
                return result
            if self._error is not None:
                error = self._error
                self._error = None
                raise error

        question_chunks = _sample_question_context(self.rag)
        if not question_chunks:
            raise RuntimeError("No indexed study material found.")
        question = self.agent.generate_question(question_chunks, previous_questions)
        return {"text": question, "source_chunks": question_chunks}


def _question_count_label(session_title: str) -> str:
    if session_title == "Review":
        return "review"
    return "quiz"


def _user_answer_query(question: str, user_answer: str) -> str:
    return f"Question: {question}\nUser answer: {user_answer}"


def _label_counts(agent: StudyAgent, label: str) -> tuple[int, int, int]:
    labels = agent.prompt_config.quiz_labels
    if label == labels["wrong"]:
        return 0, 0, 1
    if label == labels["partial"]:
        return 0, 1, 0
    return 1, 0, 0


def _ask_question_count(session: PromptSession, default_n: int, label: str) -> int:
    try:
        n_input = session.prompt(f"How many questions for {label}? (default: {default_n}) › ").strip()
        return int(n_input) if n_input.isdigit() and int(n_input) > 0 else default_n
    except (KeyboardInterrupt, EOFError):
        return 0


def _evaluate_question(
    agent: StudyAgent,
    rag: RAGEngine,
    question_data: dict,
    user_answer: str,
) -> tuple[str, str]:
    question = question_data["text"]
    question_chunks = question_data["source_chunks"]

    with console.status("[dim]Evaluating answer...[/dim]", spinner="dots"):
        support_chunks = rag.retrieve(
            _user_answer_query(question, user_answer),
            top_k=4,
        )
        eval_chunks = rag.merge_chunks(question_chunks, support_chunks, limit=6)

    console.print()
    console.print("[bold green]Feedback[/bold green]")
    full_eval = agent.evaluate_answer(question, user_answer, eval_chunks)
    console.print(full_eval, markup=False)
    return full_eval, agent.extract_quiz_feedback_label(full_eval)


def _print_classification(agent: StudyAgent, label: str):
    labels = agent.prompt_config.quiz_labels
    if label == labels["wrong"]:
        console.print(f"\n[red]✗ Classification: {labels['wrong']}[/red]")
    elif label == labels["partial"]:
        console.print(f"\n[yellow]◑ Classification: {labels['partial']}[/yellow]")
    else:
        console.print(f"\n[green]✓ Classification: {labels['correct']}[/green]")


def _run_quiz_like_mode(
    agent: StudyAgent,
    rag: RAGEngine,
    *,
    session_title: str,
    session_description: str,
    n_questions: int,
    question_supplier,
    review_store: ReviewStore | None = None,
):
    console.print()
    console.print(
        Panel(
            session_description,
            border_style="yellow",
            expand=False,
        )
    )
    console.print()

    session = PromptSession(style=PROMPT_STYLE)
    if n_questions <= 0:
        return

    console.print(f"\n[dim]Starting {session_title.lower()}: {n_questions} questions.[/dim]\n")

    correct = 0
    partial = 0
    wrong = 0
    skipped = 0
    previous_questions: list[str] = []

    q_num = 1
    while q_num <= n_questions:
        console.print(Rule(f"[yellow]Question {q_num} of {n_questions}[/yellow]", style="yellow"))
        console.print()

        with console.status("[dim]Generating question...[/dim]", spinner="dots"):
            try:
                question_data = question_supplier(previous_questions)
            except Exception as exc:
                console.print(f"[red]Could not generate the next question: {exc}[/red]")
                break

        question = question_data["text"]
        previous_questions.append(question)

        console.print(
            Panel(
                Markdown(question),
                title=f"[yellow bold]Question {q_num}[/yellow bold]",
                border_style="yellow",
            )
        )
        console.print()

        try:
            user_answer = session.prompt("Your answer › ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print(f"\n[dim]{session_title} interrupted.[/dim]")
            break

        if user_answer.lower() in ("/back", "/exit", "/quit", "/menu"):
            break

        if not user_answer or user_answer.lower() in ("/skip", "/s"):
            console.print("[dim]Question replaced with a new one.[/dim]")
            skipped += 1
            previous_questions.pop()
            continue

        try:
            full_eval, label = _evaluate_question(agent, rag, question_data, user_answer)
        except Exception as exc:
            console.print(f"\n[red]Error during evaluation: {exc}[/red]")
            previous_questions.pop()
            continue

        correct_delta, partial_delta, wrong_delta = _label_counts(agent, label)
        correct += correct_delta
        partial += partial_delta
        wrong += wrong_delta

        if review_store is not None:
            review_store.add(question_data, label)

        _print_classification(agent, label)
        console.print()

        if q_num < n_questions:
            try:
                next_step = session.prompt("Enter for the next question, /back to exit › ").strip()
                if next_step.lower() in ("/back", "/exit", "/quit", "/menu"):
                    break
            except (KeyboardInterrupt, EOFError):
                break

        q_num += 1

    console.print()
    console.print(Rule(f"[yellow]{session_title} complete[/yellow]", style="yellow"))
    console.print()

    total_answered = correct + partial + wrong
    if total_answered > 0:
        score_pct = int(100 * (correct + 0.5 * partial) / total_answered)
        score_message = (
            "Excellent."
            if score_pct >= 80
            else "Keep studying."
            if score_pct >= 50
            else "You need more practice."
        )
        console.print(
            Panel(
                f"[bold]Results:[/bold]\n\n"
                f"  [green]✓ Correct:            {correct}[/green]\n"
                f"  [yellow]◑ Partially correct:  {partial}[/yellow]\n"
                f"  [red]✗ Wrong:              {wrong}[/red]\n"
                f"  [dim]  Skipped:            {skipped}[/dim]\n\n"
                f"  [bold]Score: {score_pct}%[/bold]  {score_message}",
                title="[yellow bold]Summary[/yellow bold]",
                border_style="yellow",
            )
        )
    else:
        console.print("[dim]No questions answered.[/dim]")

    console.print()


def run_quiz_mode(agent: StudyAgent, rag: RAGEngine):
    review_store = ReviewStore(
        agent.config["study_material"],
        retained_labels={
            agent.prompt_config.quiz_labels["wrong"],
            agent.prompt_config.quiz_labels["partial"],
        },
    )
    session = PromptSession(style=PROMPT_STYLE)
    default_n = agent.config.get("default_quiz_length", 10)
    n_questions = _ask_question_count(session, default_n, _question_count_label("Quiz"))
    if n_questions <= 0:
        return

    prefetcher = QuestionPrefetcher(agent, rag)
    prefetcher.start([])

    def supplier(previous_questions: list[str]) -> dict:
        question_data = prefetcher.consume(previous_questions)
        prefetcher.start(previous_questions + [question_data["text"]])
        return question_data

    _run_quiz_like_mode(
        agent,
        rag,
        session_title="Quiz",
        session_description=(
            "[bold yellow]Quiz Mode[/bold yellow]\n"
            "[dim]The agent will ask open-ended questions based on your study material.\n"
            "These questions are meant for longer written answers.\n"
            "Commands: [bold]/back[/bold] to return to the menu, [bold]/skip[/bold] to replace the current question.[/dim]"
        ),
        n_questions=n_questions,
        question_supplier=supplier,
        review_store=review_store,
    )


def run_review_mode(agent: StudyAgent, rag: RAGEngine):
    review_store = ReviewStore(
        agent.config["study_material"],
        retained_labels={
            agent.prompt_config.quiz_labels["wrong"],
            agent.prompt_config.quiz_labels["partial"],
        },
    )
    due_questions = review_store.list_all()
    if not due_questions:
        console.print("\n[dim]No review questions for the current material.[/dim]\n")
        return

    session = PromptSession(style=PROMPT_STYLE)
    default_n = min(agent.config.get("default_quiz_length", 10), len(due_questions))
    n_questions = _ask_question_count(session, default_n, _question_count_label("Review"))
    if n_questions <= 0:
        return

    queue = due_questions[:n_questions]

    def supplier(_previous_questions: list[str]) -> dict:
        if not queue:
            raise RuntimeError("No more review questions available.")
        return queue.pop(0)

    _run_quiz_like_mode(
        agent,
        rag,
        session_title="Review",
        session_description=(
            "[bold yellow]Review Mode[/bold yellow]\n"
            "[dim]Revisit questions previously answered incorrectly or partially correctly for the current study material.\n"
            "Commands: [bold]/back[/bold] to return to the menu, [bold]/skip[/bold] to replace the current review question.[/dim]"
        ),
        n_questions=min(n_questions, len(queue)),
        question_supplier=supplier,
        review_store=review_store,
    )
