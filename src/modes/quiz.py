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
                raise RuntimeError("Nessun materiale di studio indicizzato.")
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
            raise RuntimeError("Nessun materiale di studio indicizzato.")
        question = self.agent.generate_question(question_chunks, previous_questions)
        return {"text": question, "source_chunks": question_chunks}


def _ask_question_count(session: PromptSession, default_n: int, label: str) -> int:
    try:
        n_input = session.prompt(f"Quante domande per {label}? (predefinito: {default_n}) › ").strip()
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

    with console.status("[dim]Valutazione della risposta...[/dim]", spinner="dots"):
        support_chunks = rag.retrieve(
            f"Domanda: {question}\nRisposta utente: {user_answer}",
            top_k=4,
        )
        eval_chunks = rag.merge_chunks(question_chunks, support_chunks, limit=6)

    console.print()
    console.print("[bold green]Feedback[/bold green]")
    full_eval = agent.evaluate_answer(question, user_answer, eval_chunks)
    console.print(full_eval, markup=False)
    return full_eval, agent.extract_quiz_feedback_label(full_eval)


def _print_classification(label: str):
    if label == "errato":
        console.print("\n[red]✗ Classificazione: errato[/red]")
    elif label == "parzialmente corretto":
        console.print("\n[yellow]◑ Classificazione: parzialmente corretto[/yellow]")
    else:
        console.print("\n[green]✓ Classificazione: corretto[/green]")


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

    console.print(f"\n[dim]Avvio di {session_title.lower()}: {n_questions} domande.[/dim]\n")

    correct = 0
    partial = 0
    wrong = 0
    skipped = 0
    previous_questions: list[str] = []

    q_num = 1
    while q_num <= n_questions:
        console.print(Rule(f"[yellow]Domanda {q_num} di {n_questions}[/yellow]", style="yellow"))
        console.print()

        with console.status("[dim]Generazione della domanda...[/dim]", spinner="dots"):
            try:
                question_data = question_supplier(previous_questions)
            except Exception as exc:
                console.print(f"[red]Impossibile generare la domanda successiva: {exc}[/red]")
                break

        question = question_data["text"]
        previous_questions.append(question)

        console.print(
            Panel(
                Markdown(question),
                title=f"[yellow bold]Domanda {q_num}[/yellow bold]",
                border_style="yellow",
            )
        )
        console.print()

        try:
            user_answer = session.prompt("La tua risposta › ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print(f"\n[dim]{session_title} interrotto.[/dim]")
            break

        if user_answer.lower() in ("/back", "/exit", "/quit", "/menu"):
            break

        if not user_answer or user_answer.lower() in ("/skip", "/s"):
            console.print("[dim]Domanda sostituita con una nuova.[/dim]")
            skipped += 1
            previous_questions.pop()
            continue

        try:
            full_eval, label = _evaluate_question(agent, rag, question_data, user_answer)
        except Exception as exc:
            console.print(f"\n[red]Errore durante la valutazione: {exc}[/red]")
            previous_questions.pop()
            continue

        if label == "errato":
            wrong += 1
        elif label == "parzialmente corretto":
            partial += 1
        else:
            correct += 1

        if review_store is not None:
            review_store.add(question_data, label)

        _print_classification(label)
        console.print()

        if q_num < n_questions:
            try:
                next_step = session.prompt("Invio per la prossima domanda, /back per uscire › ").strip()
                if next_step.lower() in ("/back", "/exit", "/quit", "/menu"):
                    break
            except (KeyboardInterrupt, EOFError):
                break

        q_num += 1

    console.print()
    console.print(Rule(f"[yellow]{session_title} completato[/yellow]", style="yellow"))
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
                f"  [dim]  Sostituite:        {skipped}[/dim]\n\n"
                f"  [bold]Punteggio: {score_pct}%[/bold]  {'Ottimo.' if score_pct >= 80 else 'Continua a studiare.' if score_pct >= 50 else 'Hai bisogno di piu pratica.'}",
                title="[yellow bold]Riepilogo[/yellow bold]",
                border_style="yellow",
            )
        )
    else:
        console.print("[dim]Nessuna domanda risposta.[/dim]")

    console.print()


def run_quiz_mode(agent: StudyAgent, rag: RAGEngine):
    review_store = ReviewStore(agent.config["study_material"])
    session = PromptSession(style=PROMPT_STYLE)
    default_n = agent.config.get("default_quiz_length", 10)
    n_questions = _ask_question_count(session, default_n, "il quiz")
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
            "[bold yellow]Modalita Quiz[/bold yellow]\n"
            "[dim]L'agente ti fara domande aperte basate sui tuoi materiali di studio.\n"
            "Le domande sono pensate per risposte articolate, in stile prova scritta.\n"
            "Comandi: [bold]/back[/bold] per tornare al menu, [bold]/skip[/bold] per sostituire la domanda con una nuova.[/dim]"
        ),
        n_questions=n_questions,
        question_supplier=supplier,
        review_store=review_store,
    )


def run_review_mode(agent: StudyAgent, rag: RAGEngine):
    review_store = ReviewStore(agent.config["study_material"])
    due_questions = review_store.list_all()
    if not due_questions:
        console.print("\n[dim]Nessuna domanda da ripassare per il materiale corrente.[/dim]\n")
        return

    session = PromptSession(style=PROMPT_STYLE)
    default_n = min(agent.config.get("default_quiz_length", 10), len(due_questions))
    n_questions = _ask_question_count(session, default_n, "il ripasso")
    if n_questions <= 0:
        return

    queue = review_store.pop_many(n_questions)

    def supplier(_previous_questions: list[str]) -> dict:
        if not queue:
            raise RuntimeError("Nessuna altra domanda disponibile per il ripasso.")
        return queue.pop(0)

    _run_quiz_like_mode(
        agent,
        rag,
        session_title="Ripasso",
        session_description=(
            "[bold yellow]Modalita Ripasso[/bold yellow]\n"
            "[dim]Ripassa le domande date in modo errato o parzialmente corretto per il materiale di studio attualmente caricato.\n"
            "Comandi: [bold]/back[/bold] per tornare al menu, [bold]/skip[/bold] per sostituire la domanda con un'altra del ripasso.[/dim]"
        ),
        n_questions=min(n_questions, len(queue)),
        question_supplier=supplier,
        review_store=review_store,
    )
