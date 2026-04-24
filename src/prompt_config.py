"""
prompt_config.py - Load structured prompt configuration from AGENT.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

REQUIRED_MESSAGE_KEYS = {
    "no_info_message",
    "fallback_question",
    "fallback_feedback_body",
    "fallback_expected_answer",
    "output_labels",
    "quiz_labels",
}
REQUIRED_OUTPUT_LABEL_KEYS = {"question", "source", "expected_answer", "references"}
REQUIRED_QUIZ_LABEL_KEYS = {"correct", "partial", "wrong"}
REQUIRED_FORMAT_KEYS = {
    "question_display",
    "normalized_feedback",
    "expected_answer_line",
    "references_line",
}
REQUIRED_PROMPT_KEYS = {
    "reference_system",
    "reference_user",
    "quiz_question_system",
    "quiz_question_user",
    "quiz_evaluation_system",
    "quiz_evaluation_user",
}
REQUIRED_PARSING_KEYS = {"quiz_question_stop_markers"}


def _require_mapping(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping.")
    return value


def _missing_keys(mapping: dict, required: set[str]) -> set[str]:
    return required.difference(mapping)


@dataclass(frozen=True)
class PromptConfig:
    path: Path
    behavior: str
    messages: dict
    formats: dict
    prompts: dict
    parsing: dict

    @classmethod
    def load(cls, path: str | Path) -> "PromptConfig":
        resolved = Path(path).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Prompt configuration file not found: {resolved}")

        raw_text = resolved.read_text(encoding="utf-8")
        frontmatter_match = FRONTMATTER_RE.match(raw_text)
        if not frontmatter_match:
            raise ValueError(
                "AGENT.md must start with a YAML front matter block delimited by ---"
            )

        frontmatter = yaml.safe_load(frontmatter_match.group(1)) or {}
        if "prompt_config" in frontmatter:
            frontmatter = frontmatter["prompt_config"] or {}

        config = _require_mapping(frontmatter, "prompt_config")
        messages = _require_mapping(config.get("messages", {}), "prompt_config.messages")
        formats = _require_mapping(config.get("formats", {}), "prompt_config.formats")
        prompts = _require_mapping(config.get("prompts", {}), "prompt_config.prompts")
        parsing = _require_mapping(config.get("parsing", {}), "prompt_config.parsing")

        missing_messages = _missing_keys(messages, REQUIRED_MESSAGE_KEYS)
        if missing_messages:
            raise ValueError(
                "Missing prompt_config.messages keys: "
                + ", ".join(sorted(missing_messages))
            )

        output_labels = _require_mapping(
            messages.get("output_labels", {}), "prompt_config.messages.output_labels"
        )
        quiz_labels = _require_mapping(
            messages.get("quiz_labels", {}), "prompt_config.messages.quiz_labels"
        )

        missing_output_labels = _missing_keys(output_labels, REQUIRED_OUTPUT_LABEL_KEYS)
        if missing_output_labels:
            raise ValueError(
                "Missing prompt_config.messages.output_labels keys: "
                + ", ".join(sorted(missing_output_labels))
            )

        missing_quiz_labels = _missing_keys(quiz_labels, REQUIRED_QUIZ_LABEL_KEYS)
        if missing_quiz_labels:
            raise ValueError(
                "Missing prompt_config.messages.quiz_labels keys: "
                + ", ".join(sorted(missing_quiz_labels))
            )

        missing_formats = _missing_keys(formats, REQUIRED_FORMAT_KEYS)
        if missing_formats:
            raise ValueError(
                "Missing prompt_config.formats keys: "
                + ", ".join(sorted(missing_formats))
            )

        missing_prompts = _missing_keys(prompts, REQUIRED_PROMPT_KEYS)
        if missing_prompts:
            raise ValueError(
                "Missing prompt_config.prompts keys: "
                + ", ".join(sorted(missing_prompts))
            )

        missing_parsing = _missing_keys(parsing, REQUIRED_PARSING_KEYS)
        if missing_parsing:
            raise ValueError(
                "Missing prompt_config.parsing keys: "
                + ", ".join(sorted(missing_parsing))
            )

        behavior = raw_text[frontmatter_match.end() :].strip()
        if not behavior:
            raise ValueError("AGENT.md must contain behavior instructions after the YAML front matter.")

        return cls(
            path=resolved,
            behavior=behavior,
            messages=messages,
            formats=formats,
            prompts=prompts,
            parsing=parsing,
        )

    @property
    def output_labels(self) -> dict:
        return self.messages["output_labels"]

    @property
    def quiz_labels(self) -> dict:
        return self.messages["quiz_labels"]

    def _base_context(self) -> dict:
        return {
            "agent_behavior": self.behavior,
            "no_info_message": self.messages["no_info_message"],
            "fallback_question": self.messages["fallback_question"],
            "fallback_feedback_body": self.messages["fallback_feedback_body"],
            "fallback_expected_answer": self.messages["fallback_expected_answer"],
            "question_label": self.output_labels["question"],
            "source_label": self.output_labels["source"],
            "content_label": self.output_labels["content"],
            "italian_form_label": self.output_labels["italian_form"],
            "expected_answer_label": self.output_labels["expected_answer"],
            "references_label": self.output_labels["references"],
            "correct_label": self.quiz_labels["correct"],
            "partial_label": self.quiz_labels["partial"],
            "wrong_label": self.quiz_labels["wrong"],
        }

    def _render(self, template: str, **kwargs) -> str:
        values = self._base_context()
        values.update(kwargs)
        return template.format(**values).strip()

    def render_prompt(self, name: str, **kwargs) -> str:
        return self._render(self.prompts[name], **kwargs)

    def render_format(self, name: str, **kwargs) -> str:
        return self._render(self.formats[name], **kwargs)

    def render_list(self, name: str, **kwargs) -> list[str]:
        values = self.parsing.get(name)
        if not isinstance(values, list):
            raise ValueError(f"prompt_config.parsing.{name} must be a list.")
        return [self._render(value, **kwargs) for value in values]
