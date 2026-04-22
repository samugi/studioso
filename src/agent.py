"""
agent.py — Core agent: loads AGENT.md, talks to Ollama, builds prompts.
"""

import re
from pathlib import Path
from typing import Iterator

import ollama
from rich.console import Console

console = Console()


class StudyAgent:
    def __init__(self, config: dict):
        self.config = config
        self.ollama_model = config.get("ollama_model", "mistral:7b")
        self.ollama_url = config.get("ollama_url", "http://localhost:11434")
        self.show_sources = config.get("show_sources", True)
        self.source_excerpt_length = config.get("source_excerpt_length", 200)
        self._behavior = self._load_behavior(config.get("agent_config", "./AGENT.md"))
        self._client = ollama.Client(host=self.ollama_url)

    def _load_behavior(self, agent_config_path: str) -> str:
        path = Path(agent_config_path)
        if not path.is_absolute():
            # Resolve relative to CWD
            path = Path.cwd() / path
        if path.exists():
            return path.read_text(encoding="utf-8")
        return "Tu sei un assistente allo studio. Rispondi solo basandoti sul materiale/contesto fornito."

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

    def _build_reference_mode_system_prompt(
        self, context_chunks: list[dict], mode: str = "qa"
    ) -> str:
        # Format retrieved context
        context_parts = []
        for i, chunk in enumerate(context_chunks, 1):
            excerpt = chunk["text"][
                : self.source_excerpt_length * 2
            ]  # full text for model
            context_parts.append(f"[Source {i}: {chunk['filename']}]\n{excerpt}")
        context_str = (
            "\n\n---\n\n".join(context_parts)
            if context_parts
            else "No relevant context found."
        )

        system = f"""Tu sei un assistente allo studio che segue rigorosamente le seguenti regole:

{self._behavior}

---

CONTESTO DEL MATERIALE DI STUDIO:
{context_str}

---

REGOLE RIGOROSE:
- Basa la tua risposta ESCLUSIVAMENTE sul contesto sopra.
- Se la risposta non è presente nel contesto, dillo chiaramente. Non improvvisare.
- Cita sempre da quale documento sorgente proviene la risposta.
- Modalità: {mode.upper()}
"""
        return system

    def _build_quiz_mode_system_prompt(self, context_chunks: list[dict]) -> str:
        context_parts = []
        for i, chunk in enumerate(context_chunks, 1):
            context_parts.append(f"[Source {i}: {chunk['filename']}]\n{chunk['text']}")
        context_str = "\n\n---\n\n".join(context_parts)

        system = f"""Tu sei un assistente allo studio che genera domande di un quiz.

{self._behavior}

---

CONTESTO DEL MATERIALE DI STUDIO:
{context_str}

---

REGOLE RIGOROSE:
- Genera domande ESCLUSIVAMENTE a partire dal contesto sopra.
- NON generare domande su argomenti non presenti nel contesto.
- Fai una sola domanda alla volta.
- Varia i tipi di domanda: definizioni, applicazioni, confronti, cause-effetti, esempi.
- Indica la fonte della domanda alla fine tra parentesi, ad esempio: (Fonte: filename.pdf)
"""
        return system

    def answer_question(
        self, question: str, context_chunks: list[dict], history: list[dict] = None
    ) -> str:
        """Rispondi a una domanda dell'utente usando il materiale di studio fornito. Restituisci la domanda completa tutta in una volta."""
        system = self._build_reference_mode_system_prompt(context_chunks, mode="qa")
        messages = []
        if history:
            messages.extend(history[-6:])  # keep last 3 exchanges
        messages.append({"role": "user", "content": question})
        messages.append({"role": "system", "content": system})

        response = self._client.chat(
            model=self.ollama_model,
            messages=messages,
            options={"temperature": 0.2, "num_predict": 1024},
        )
        return response.message.content

    def answer_question_stream(
        self, question: str, context_chunks: list[dict], history: list[dict] = None
    ) -> Iterator[str]:
        """Stream answer tokens."""
        system = self._build_reference_mode_system_prompt(context_chunks, mode="qa")
        messages = []
        if history:
            messages.extend(history[-6:])
        messages.append({"role": "user", "content": question})
        messages.append({"role": "system", "content": system})

        stream = self._client.chat(
            model=self.ollama_model,
            messages=messages,
            options={"temperature": 0.2, "num_predict": 1024},
            stream=True,
        )
        for chunk in stream:
            if chunk.message and chunk.message.content:
                yield chunk.message.content

    def generate_question(
        self, context_chunks: list[dict], previous_questions: list[str] = None
    ) -> str:
        """Generate a quiz question from context."""
        system = self._build_quiz_mode_system_prompt(context_chunks)
        avoid = ""
        if previous_questions:
            avoid = "\n\nEvita di ripetere le domande precedenti:\n" + "\n".join(
                f"- {q}" for q in previous_questions[-5:]
            )

        messages = []
        messages.append({"role": "system", "content": system})
        messages.append(
            {
                "role": "user",
                "content": f"Genera UNA domanda da quiz dal materiale di studio.{avoid}",
            }
        )

        response = self._client.chat(
            model=self.ollama_model,
            messages=messages,
            options={"temperature": 0.7, "num_predict": 256},
        )
        return response.message.content.strip()

    def evaluate_answer(
        self, question: str, user_answer: str, context_chunks: list[dict]
    ) -> str:
        """Valuta la risposta dell'utente basandoti sul materiale di studio fornito."""
        system = self._build_reference_mode_system_prompt(
            context_chunks, mode="quiz-evaluation"
        )
        prompt = f"""Domanda del Quiz: {question}

Risposta dell'utente: {user_answer}

Valuta questa risposta basandoti rigorosamente sul contesto del materiale di studio fornito
e seguendo le regole del prompt system appena ricevuto."""

        messages = []
        messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        stream = self._client.chat(
            model=self.ollama_model,
            messages=messages,
            options={"temperature": 0.2, "num_predict": 512},
            stream=True,
        )
        result = ""
        for chunk in stream:
            if chunk.message and chunk.message.content:
                result += chunk.message.content
        return result

    def evaluate_answer_stream(
        self, question: str, user_answer: str, context_chunks: list[dict]
    ) -> Iterator[str]:
        """Stream evaluation of a user's quiz answer."""
        system = self._build_reference_mode_system_prompt(
            context_chunks, mode="quiz-evaluation"
        )
        prompt = f"""Domanda del Quiz: {question}

Risposta dell'utente: {user_answer}

Valuta questa risposta basandoti rigorosamente sul contesto del materiale di studio fornito
e seguendo le regole del prompt system appena ricevuto."""

        messages = []
        messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        stream = self._client.chat(
            model=self.ollama_model,
            messages=messages,
            options={"temperature": 0.2, "num_predict": 512},
            stream=True,
        )
        for chunk in stream:
            if chunk.message and chunk.message.content:
                yield chunk.message.content
