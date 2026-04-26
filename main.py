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


def _resolve_path(config_base: Path, value: str, default: str) -> str:
    resolved = Path(value or default)
    if not resolved.is_absolute():
        resolved = config_base / resolved
    return str(resolved.resolve())


def _resolve_agent_config_for_material(study_material: str, fallback_agent_config: str) -> str:
    fallback_path = Path(fallback_agent_config).resolve()
    material_path = Path(study_material).resolve()
    search_root = fallback_path.parent
    current = material_path if material_path.is_dir() else material_path.parent

    try:
        current.relative_to(search_root)
    except ValueError:
        return str(fallback_path)

    while True:
        candidate = current / "AGENT.md"
        if candidate.exists():
            return str(candidate.resolve())
        if current == search_root:
            break
        current = current.parent

    return str(fallback_path)


def load_config(config_path: str = "config.yaml") -> dict:
    path = Path(config_path)
    if not path.exists():
        console.print(f"[red]Config file not found: {path.resolve()}[/red]")
        console.print("Make sure you're running from the study-agent directory.")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    study_material = config.get("study_material") or config.get("study_folder")
    config["study_material"] = _resolve_path(path.parent, study_material, "./materials")
    config["study_folder"] = config["study_material"]

    config["agent_config_fallback"] = _resolve_path(
        path.parent,
        config.get("agent_config", "./AGENT.md"),
        "./AGENT.md",
    )
    config["agent_config"] = _resolve_agent_config_for_material(
        config["study_material"],
        config["agent_config_fallback"],
    )

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
        "--material",
        help="Override the study_material in config.yaml",
    )
    parser.add_argument(
        "--folder",
        help="Deprecated alias for --material",
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
    material_override = args.material or args.folder
    if material_override:
        material = Path(material_override)
        if not material.is_absolute():
            material = Path.cwd() / material
        config["study_material"] = str(material.resolve())
        config["study_folder"] = config["study_material"]
        config["agent_config"] = _resolve_agent_config_for_material(
            config["study_material"],
            config.get("agent_config_fallback", config.get("agent_config", "./AGENT.md")),
        )
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
