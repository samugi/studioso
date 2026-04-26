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
      question: "QUESTION"
      source: "SOURCE"
      content: "Content"
      italian_form: "Language form"
      expected_answer: "Expected answer"
      references: "References"
    quiz_labels:
      correct: "correct"
      partial: "partially correct"
      wrong: "wrong"
  formats:
    question_display: "{question}"
    normalized_feedback: "{label}: {body}"
    content_line: "{content_label}: {content_feedback}"
    italian_form_line: "{italian_form_label}: {italian_form_feedback}"
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
      - "SOURCE"
---
body
""",
            encoding="utf-8",
        )
        (root / "nested" / "config.yaml").write_text(
            'study_material: "./materials"\nagent_config: "./AGENT.md"\n',
            encoding="utf-8",
        )

        config = load_config(str(root / "nested" / "config.yaml"))

        assert config["study_material"] == str((root / "nested" / "materials").resolve())
        assert config["study_folder"] == str((root / "nested" / "materials").resolve())
        assert config["agent_config"] == str((root / "nested" / "AGENT.md").resolve())


def test_load_config_prefers_nearest_agent_md_for_selected_folder():
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        materials = root / "materials"
        target = materials / "bar" / "zap"
        target.mkdir(parents=True)
        (root / "AGENT.md").write_text("root", encoding="utf-8")
        (materials / "bar" / "AGENT.md").write_text("bar", encoding="utf-8")
        (root / "config.yaml").write_text(
            'study_material: "./materials/bar/zap"\nagent_config: "./AGENT.md"\n',
            encoding="utf-8",
        )

        config = load_config(str(root / "config.yaml"))

        assert config["agent_config"] == str((materials / "bar" / "AGENT.md").resolve())
        assert config["agent_config_fallback"] == str((root / "AGENT.md").resolve())


def test_load_config_falls_back_to_root_agent_md_when_no_local_override_exists():
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        target = root / "materials" / "aaa" / "bbb"
        target.mkdir(parents=True)
        (root / "AGENT.md").write_text("root", encoding="utf-8")
        (root / "config.yaml").write_text(
            'study_material: "./materials/aaa/bbb"\nagent_config: "./AGENT.md"\n',
            encoding="utf-8",
        )

        config = load_config(str(root / "config.yaml"))

        assert config["agent_config"] == str((root / "AGENT.md").resolve())


def test_load_config_prefers_parent_agent_md_for_selected_file():
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        target_dir = root / "materials" / "foo"
        target_dir.mkdir(parents=True)
        material_file = target_dir / "notes.pdf"
        material_file.write_text("x", encoding="utf-8")
        (root / "AGENT.md").write_text("root", encoding="utf-8")
        (target_dir / "AGENT.md").write_text("local", encoding="utf-8")
        (root / "config.yaml").write_text(
            'study_material: "./materials/foo/notes.pdf"\nagent_config: "./AGENT.md"\n',
            encoding="utf-8",
        )

        config = load_config(str(root / "config.yaml"))

        assert config["agent_config"] == str((target_dir / "AGENT.md").resolve())
