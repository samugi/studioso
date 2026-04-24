from pathlib import Path
from tempfile import TemporaryDirectory

from main import load_config


def test_load_config_resolves_paths_relative_to_config_file():
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "nested").mkdir()
        (root / "nested" / "materials").mkdir()
        (root / "nested" / "AGENT.md").write_text(
            """---
prompt_config:
  messages:
    no_info_message: "x"
    fallback_question: "y"
    fallback_feedback_body: "z"
    fallback_expected_answer: "t"
    default_references_fallback: "m"
    output_labels:
      question: "DOMANDA"
      source: "FONTE"
      expected_answer: "Risposta attesa"
      references: "Riferimenti"
    quiz_labels:
      correct: "corretto"
      partial: "parzialmente corretto"
      wrong: "errato"
  formats:
    question_display: "{question}"
    normalized_feedback: "{label}: {body}"
    expected_answer_line: "{expected_answer_label}: {expected_answer}"
    references_line: "{references_label}: {references}"
  prompts:
    reference_system: "{context}"
    reference_user: "{user_input}"
    quiz_question_system: "{context}"
    quiz_question_user: "{previous_questions}"
    quiz_evaluation_system: "{context}"
    quiz_evaluation_user: "{question} {user_answer}"
  parsing:
    quiz_question_stop_markers:
      - "FONTE"
---
body
""",
            encoding="utf-8",
        )
        (root / "nested" / "config.yaml").write_text(
            'study_folder: "./materials"\nagent_config: "./AGENT.md"\n',
            encoding="utf-8",
        )

        config = load_config(str(root / "nested" / "config.yaml"))

        assert config["study_folder"] == str((root / "nested" / "materials").resolve())
        assert config["agent_config"] == str((root / "nested" / "AGENT.md").resolve())
