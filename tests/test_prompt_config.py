from pathlib import Path

from src.prompt_config import PromptConfig


def test_prompt_config_loads_frontmatter_and_behavior():
    config = PromptConfig.load(Path("AGENT.md"))

    assert config.quiz_labels["correct"] == "corretto"
    assert config.output_labels["question"] == "DOMANDA"
    assert "Ruolo" in config.behavior


def test_prompt_config_renders_templates():
    config = PromptConfig.load(Path("AGENT.md"))

    rendered = config.render_prompt("reference_user", user_input="Che cos'e il tributo?")

    assert "Che cos'e il tributo?" in rendered
    assert rendered.startswith("Domanda dell'utente")
