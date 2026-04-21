"""
main.py — Study Agent entry point.
Run with: python main.py
Or optionally: python main.py --config path/to/config.yaml
"""

import sys
import argparse
from pathlib import Path

import yaml
from rich.console import Console

console = Console()


def load_config(config_path: str = "config.yaml") -> dict:
    path = Path(config_path)
    if not path.exists():
        console.print(f"[red]Config file not found: {path.resolve()}[/red]")
        console.print("Make sure you're running from the study-agent directory.")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Resolve study_folder relative to config file location
    study_folder = Path(config.get("study_folder", "./materials"))
    if not study_folder.is_absolute():
        study_folder = path.parent / study_folder
    config["study_folder"] = str(study_folder.resolve())

    # Resolve agent_config relative to config file location
    agent_cfg = Path(config.get("agent_config", "./AGENT.md"))
    if not agent_cfg.is_absolute():
        agent_cfg = path.parent / agent_cfg
    config["agent_config"] = str(agent_cfg.resolve())

    return config


def main():
    parser = argparse.ArgumentParser(
        description="Study Agent — AI-powered study assistant grounded in your documents."
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: ./config.yaml)",
    )
    parser.add_argument(
        "--folder",
        help="Override the study_folder in config.yaml",
    )
    parser.add_argument(
        "--model",
        help="Override the ollama_model in config.yaml",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="Force reindex all documents and exit",
    )
    args = parser.parse_args()

    config = load_config(args.config)

    # CLI overrides
    if args.folder:
        folder = Path(args.folder)
        if not folder.is_absolute():
            folder = Path.cwd() / folder
        config["study_folder"] = str(folder.resolve())
    if args.model:
        config["ollama_model"] = args.model

    # Lazy imports (so startup errors are shown clearly)
    try:
        from src.agent import StudyAgent
        from src.rag import RAGEngine
        from src.ui.cli import run_menu
    except ImportError as e:
        console.print(f"[red]Import error: {e}[/red]")
        console.print("Run setup first: [bold]python setup.py[/bold]")
        sys.exit(1)

    agent = StudyAgent(config)
    rag = RAGEngine(config)

    if args.reindex:
        console.print("[dim]Force reindexing all documents...[/dim]")
        n = rag.ingest(force=True)
        console.print(f"[green]Done. {n} chunks indexed.[/green]")
        sys.exit(0)

    run_menu(agent, rag)


if __name__ == "__main__":
    main()
