"""
agent.py — Core agent: loads AGENT.md, talks to Ollama, builds prompts.
"""

import re
from pathlib import Path
from typing import Iterator

import ollama
from rich.console import Console

from src.prompt_config import PromptConfig

console = Console()


class StudyAgent:
    def __init__(self, config: dict):
        self.config = config
        self.ollama_model = config.get("ollama_model", "mistral:7b")
        self.ollama_url = config.get("ollama_url", "http://localhost:11434")
        self.show_sources = config.get("show_sources", True)
        self.source_excerpt_length = config.get("source_excerpt_length", 200)
        self.prompt_config = self._load_prompt_config(
            config.get("agent_config", "./AGENT.md")
        )
        self._client = ollama.Client(host=self.ollama_url)

    def _load_prompt_config(self, agent_config_path: str) -> PromptConfig:
        path = Path(agent_config_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        return PromptConfig.load(path)

    def check_ollama(self) -> tuple[bool, str]:
        """Check if Ollama is running and the model is available."""
        try:
            models = self._client.list()
            available = [m.model for m in models.models]

            # Normalize: strip :latest suffix for comparison
            def normalize(name):
                return name.split(":")[0]

            target = normalize(self.ollama_model)
            found = any(normalize(m) == target for m in available)
            return True, available if found else []
        except Exception as e:
            return False, str(e)

    def pull_model_stream(self) -> Iterator[str]:
        """Pull model from Ollama, yielding progress strings."""
        for chunk in self._client.pull(self.ollama_model, stream=True):
            status = getattr(chunk, "status", "") or ""
            total = getattr(chunk, "total", None)
            completed = getattr(chunk, "completed", None)
            if total and completed:
                pct = int(100 * completed / total)
                yield f"{status} ({pct}%)"
            else:
                yield status

    def _format_context(self, context_chunks: list[dict], full_text: bool = False) -> str:
        if not context_chunks:
            return "Nessun contesto rilevante trovato."

        context_parts = []
        for i, chunk in enumerate(context_chunks, 1):
            text = (chunk.get("text") or "").strip()
            if not full_text:
                text = text[: self.source_excerpt_length * 2]

            filename = chunk.get("filename", "sconosciuto")
            source = chunk.get("source")
            header = f"[Fonte {i}: {filename}]"
            if source:
                header += f" [{source}]"

            context_parts.append(f"{header}\n{text}")

        return "\n\n---\n\n".join(context_parts)

    def _chat(
        self,
        system: str,
        user_content: str,
        history: list[dict] | None = None,
        temperature: float = 0.2,
        num_predict: int = 1024,
    ) -> str:
        messages = [{"role": "system", "content": system}]
        if history:
            messages.extend(history[-6:])
        messages.append({"role": "user", "content": user_content})

        response = self._client.chat(
            model=self.ollama_model,
            messages=messages,
            options={"temperature": temperature, "num_predict": num_predict},
        )
        return response.message.content.strip()

    def _chat_stream(
        self,
        system: str,
        user_content: str,
        history: list[dict] | None = None,
        temperature: float = 0.2,
        num_predict: int = 1024,
    ) -> Iterator[str]:
        messages = [{"role": "system", "content": system}]
        if history:
            messages.extend(history[-6:])
        messages.append({"role": "user", "content": user_content})

        stream = self._client.chat(
            model=self.ollama_model,
            messages=messages,
            options={"temperature": temperature, "num_predict": num_predict},
            stream=True,
        )
        for chunk in stream:
            if chunk.message and chunk.message.content:
                yield chunk.message.content

    def _build_reference_mode_system_prompt(self, context_chunks: list[dict]) -> str:
        context_str = self._format_context(context_chunks)
        return self.prompt_config.render_prompt("reference_system", context=context_str)

    def _build_quiz_question_system_prompt(self, context_chunks: list[dict]) -> str:
        context_str = self._format_context(context_chunks, full_text=True)
        return self.prompt_config.render_prompt(
            "quiz_question_system", context=context_str
        )

    def _build_quiz_evaluation_system_prompt(self, context_chunks: list[dict]) -> str:
        context_str = self._format_context(context_chunks, full_text=True)
        return self.prompt_config.render_prompt(
            "quiz_evaluation_system", context=context_str
        )

    def _default_references(self, context_chunks: list[dict]) -> str:
        filenames = []
        for chunk in context_chunks:
            filename = chunk.get("filename")
            if filename and filename not in filenames:
                filenames.append(filename)
        return ", ".join(filenames[:3]) if filenames else self.prompt_config.messages.get(
            "default_references_fallback", "materials"
        )

    def _normalize_quiz_question(self, raw_question: str, context_chunks: list[dict]) -> str:
        question_label = re.escape(self.prompt_config.output_labels["question"])
        source_label = re.escape(self.prompt_config.output_labels["source"])
        question_match = re.search(rf"(?im)^{question_label}\s*:\s*(.+)$", raw_question)
        source_match = re.search(rf"(?im)^{source_label}\s*:\s*(.+)$", raw_question)

        question = question_match.group(1).strip() if question_match else ""
        source = source_match.group(1).strip() if source_match else ""

        if not question:
            stop_markers = [
                re.escape(marker)
                for marker in self.prompt_config.render_list("quiz_question_stop_markers")
            ]
            collected = []
            for line in raw_question.splitlines():
                stripped = line.strip().strip("-* ")
                if not stripped:
                    if collected:
                        break
                    continue

                if stop_markers and re.match(
                    rf"(?i)^(?:{'|'.join(stop_markers)})\s*[:\-]",
                    stripped,
                ):
                    break
                collected.append(stripped)

            question = " ".join(collected).strip()

        question = re.sub(r"\s+", " ", question)
        question = re.sub(rf"(?i)^{question_label}\s*[:\-]\s*", "", question).strip()

        if not question:
            question = self.prompt_config.messages["fallback_question"]

        if not question.endswith("?"):
            question += "?"

        references = source or self._default_references(context_chunks)
        return self.prompt_config.render_format(
            "question_display",
            question=question,
            references=references,
        )

    def extract_quiz_feedback_label(self, feedback: str) -> str:
        normalized = feedback.strip().lower()
        labels = self.prompt_config.quiz_labels
        if normalized.startswith(labels["partial"].lower()):
            return labels["partial"]
        if normalized.startswith(labels["correct"].lower()):
            return labels["correct"]
        if normalized.startswith(labels["wrong"].lower()):
            return labels["wrong"]

        candidates = [labels["partial"], labels["correct"], labels["wrong"]]
        fallback_match = re.search(
            rf"(?i)\b({'|'.join(re.escape(value) for value in candidates)})\b",
            normalized,
        )
        if not fallback_match:
            return labels["wrong"]

        label = fallback_match.group(1).lower()
        if label == labels["partial"].lower():
            return labels["partial"]
        if label == labels["wrong"].lower():
            return labels["wrong"]
        return labels["correct"]

    def _normalize_quiz_feedback(self, raw_feedback: str, context_chunks: list[dict]) -> str:
        label = self.extract_quiz_feedback_label(raw_feedback)
        body = raw_feedback.strip()
        body = re.sub(r"(?im)^verdetto\s*:\s*", "", body, count=1).strip()
        label_pattern = "|".join(
            re.escape(value)
            for value in (
                self.prompt_config.quiz_labels["partial"],
                self.prompt_config.quiz_labels["correct"],
                self.prompt_config.quiz_labels["wrong"],
            )
        )
        body = re.sub(
            rf"(?is)^\s*(?:{label_pattern})\s*[:\-]?\s*",
            "",
            body,
            count=1,
        ).strip()

        if not body:
            body = self.prompt_config.messages["fallback_feedback_body"]

        expected_answer_label = re.escape(self.prompt_config.output_labels["expected_answer"])
        references_label = re.escape(self.prompt_config.output_labels["references"])

        if not re.search(rf"(?im)^{expected_answer_label}\s*:", body):
            body = (
                f"{body.rstrip()}\n"
                + self.prompt_config.render_format(
                    "expected_answer_line",
                    expected_answer=self.prompt_config.messages["fallback_expected_answer"],
                )
            )

        if not re.search(rf"(?im)^{references_label}\s*:", body):
            body = (
                f"{body.rstrip()}\n"
                + self.prompt_config.render_format(
                    "references_line",
                    references=self._default_references(context_chunks),
                )
            )

        return self.prompt_config.render_format(
            "normalized_feedback",
            label=label,
            body=body,
        )

    def answer_question(
        self, question: str, context_chunks: list[dict], history: list[dict] = None
    ) -> str:
        """Rispondi a una domanda dell'utente usando solo il materiale fornito."""
        system = self._build_reference_mode_system_prompt(context_chunks)
        user_prompt = self.prompt_config.render_prompt(
            "reference_user",
            user_input=question,
        )
        return self._chat(system, user_prompt, history=history)

    def answer_question_stream(
        self, question: str, context_chunks: list[dict], history: list[dict] = None
    ) -> Iterator[str]:
        """Stream answer tokens."""
        system = self._build_reference_mode_system_prompt(context_chunks)
        user_prompt = self.prompt_config.render_prompt(
            "reference_user",
            user_input=question,
        )
        yield from self._chat_stream(system, user_prompt, history=history)

    def generate_question(
        self, context_chunks: list[dict], previous_questions: list[str] = None
    ) -> str:
        """Generate a quiz question from context."""
        system = self._build_quiz_question_system_prompt(context_chunks)
        previous_questions_block = "-"
        if previous_questions:
            previous_questions_block = "\n".join(
                f"- {q}" for q in previous_questions[-5:]
            )

        raw_question = self._chat(
            system,
            self.prompt_config.render_prompt(
                "quiz_question_user",
                previous_questions=previous_questions_block,
            ),
            temperature=0.3,
            num_predict=256,
        )
        return self._normalize_quiz_question(raw_question, context_chunks)

    def evaluate_answer(
        self, question: str, user_answer: str, context_chunks: list[dict]
    ) -> str:
        """Valuta la risposta dell'utente basandoti sul materiale di studio fornito."""
        system = self._build_quiz_evaluation_system_prompt(context_chunks)
        prompt = self.prompt_config.render_prompt(
            "quiz_evaluation_user",
            question=question,
            user_answer=user_answer,
        )
        raw_feedback = self._chat(system, prompt, temperature=0.1, num_predict=512)
        return self._normalize_quiz_feedback(raw_feedback, context_chunks)

    def evaluate_answer_stream(
        self, question: str, user_answer: str, context_chunks: list[dict]
    ) -> Iterator[str]:
        """Stream evaluation of a user's quiz answer."""
        yield self.evaluate_answer(question, user_answer, context_chunks)
