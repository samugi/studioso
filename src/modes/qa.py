"""
qa.py — Interactive Q&A mode.
User asks questions; agent answers from the study materials.
"""

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style

from src.agent import StudyAgent
from src.rag import RAGEngine

console = Console()

PROMPT_STYLE = Style.from_dict({
    "prompt": "#00aaff bold",
})


def format_sources(chunks: list[dict], excerpt_length: int = 200) -> str:
    """Format retrieved source citations."""
    seen = {}
    for chunk in chunks:
        fn = chunk["filename"]
        rel = chunk.get("relevance", 0)
        if fn not in seen or seen[fn]["relevance"] < rel:
            seen[fn] = {"relevance": rel, "text": chunk["text"]}

    lines = []
    for fn, data in sorted(seen.items(), key=lambda x: -x[1]["relevance"]):
        excerpt = data["text"][:excerpt_length].replace("\n", " ").strip()
        if len(data["text"]) > excerpt_length:
            excerpt += "…"
        lines.append(f"📄 **{fn}** (relevance: {data['relevance']:.0%})\n   _{excerpt}_")

    return "\n\n".join(lines) if lines else ""


def run_qa_mode(agent: StudyAgent, rag: RAGEngine):
    console.print()
    console.print(Panel(
        "[bold cyan]Q&A Mode[/bold cyan]\n"
        "[dim]Ask anything about your study materials.\n"
        "Type [bold]/back[/bold] to return to the menu, [bold]/sources[/bold] to toggle source display.[/dim]",
        border_style="cyan",
        expand=False,
    ))
    console.print()

    session = PromptSession(style=PROMPT_STYLE)
    history: list[dict] = []
    show_sources = agent.show_sources

    while True:
        try:
            user_input = session.prompt("You › ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not user_input:
            continue

        # Commands
        if user_input.lower() in ("/back", "/exit", "/quit", "/menu"):
            break

        if user_input.lower() == "/sources":
            show_sources = not show_sources
            state = "ON" if show_sources else "OFF"
            console.print(f"[dim]Source display: {state}[/dim]")
            continue

        if user_input.lower() == "/clear":
            history.clear()
            console.print("[dim]Conversation history cleared.[/dim]")
            continue

        if user_input.lower() == "/help":
            console.print(
                "[dim]/back[/dim] — return to menu\n"
                "[dim]/sources[/dim] — toggle source citations\n"
                "[dim]/clear[/dim] — clear conversation history\n"
                "[dim]/files[/dim] — list indexed files"
            )
            continue

        if user_input.lower() == "/files":
            files = rag.indexed_files()
            if files:
                console.print("[dim]Indexed files:[/dim]")
                for f in files:
                    console.print(f"  [cyan]•[/cyan] {f}")
            else:
                console.print("[yellow]No files indexed yet.[/yellow]")
            continue

        # Retrieve relevant chunks
        with console.status("[dim]Searching study materials...[/dim]", spinner="dots"):
            chunks = rag.retrieve(user_input)

        if not chunks:
            console.print(
                "\n[yellow]⚠ No relevant content found in your study materials for that question.\n"
                "Try rephrasing, or check that the right folder is loaded.[/yellow]\n"
            )
            continue

        # Stream response
        console.print()
        console.print("[bold green]Agent ›[/bold green]")
        full_response = ""
        try:
            for token in agent.answer_question_stream(user_input, chunks, history):
                console.print(token, end="", markup=False)
                full_response += token
            console.print()  # newline after stream
        except Exception as e:
            console.print(f"\n[red]Error communicating with Ollama: {e}[/red]")
            console.print("[dim]Make sure Ollama is running: [bold]ollama serve[/bold][/dim]")
            continue

        # Show sources
        if show_sources and chunks:
            console.print()
            sources_text = format_sources(chunks, agent.source_excerpt_length)
            if sources_text:
                console.print(Panel(
                    Markdown(sources_text),
                    title="[dim]Sources[/dim]",
                    border_style="dim",
                    expand=False,
                ))

        console.print()
        console.print(Rule(style="dim"))
        console.print()

        # Update history
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": full_response})
