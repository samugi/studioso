"""
agent.py — Core agent: loads AGENT.md, talks to Ollama, builds prompts.
"""

import re
from pathlib import Path
from typing import Iterator

import ollama
from rich.console import Console

console = Console()

NO_INFO_MESSAGE = (
    "Non sono riuscito a trovare questa informazione nei tuoi materiali di studio. "
    "Prova a riformulare la domanda oppure verifica di aver caricato la cartella corretta."
)


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
        return f"""Tu sei un assistente allo studio per concorsi pubblici.

{self._behavior}

---

CONTESTO DEL MATERIALE DI STUDIO:
{context_str}

---

REGOLE OPERATIVE PER LA MODALITA REFERENCE:
- Scrivi sempre e solo in italiano.
- Rispondi esclusivamente usando il contesto sopra.
- Non usare conoscenze esterne, anche se conosci la risposta.
- Non inventare, non completare i vuoti con supposizioni.
- Se l'informazione non e presente nel contesto, rispondi esattamente con questa frase:
  \"{NO_INFO_MESSAGE}\"
- In questa modalita devi solo rispondere alla domanda dell'utente: non generare quiz, non proporre domande, non valutare risposte.
- Indica sempre i riferimenti documentali usati nella risposta.
"""

    def _build_quiz_question_system_prompt(self, context_chunks: list[dict]) -> str:
        context_str = self._format_context(context_chunks, full_text=True)
        return f"""Tu sei un assistente allo studio per concorsi pubblici che deve generare una sola domanda di quiz.

{self._behavior}

---

CONTESTO DEL MATERIALE DI STUDIO:
{context_str}

---

REGOLE OPERATIVE PER LA MODALITA QUIZ:
- Scrivi sempre e solo in italiano.
- Genera una sola domanda aperta, chiara e specifica, basata esclusivamente sul contesto.
- Non fornire risposta, soluzione, suggerimenti, traccia di correzione o feedback.
- Non fare commenti introduttivi o conclusivi.
- Non simulare la risposta dell'utente.
- Non mescolare domanda e spiegazione.
- La domanda deve richiedere comprensione reale del materiale.

FORMATO OBBLIGATORIO:
DOMANDA: <testo della domanda>
FONTE: <uno o piu nomi file del contesto>
"""

    def _build_quiz_evaluation_system_prompt(self, context_chunks: list[dict]) -> str:
        context_str = self._format_context(context_chunks, full_text=True)
        return f"""Tu sei un correttore rigoroso di risposte per concorsi pubblici.

{self._behavior}

---

CONTESTO DEL MATERIALE DI STUDIO:
{context_str}

---

REGOLE OPERATIVE PER LA VALUTAZIONE QUIZ:
- Scrivi sempre e solo in italiano.
- Valuta la risposta ESCLUSIVAMENTE in base al contesto sopra.
- Usa \"corretto\" solo se la risposta e sostanzialmente completa, precisa e senza errori rilevanti.
- Usa \"parzialmente corretto\" solo se la risposta contiene almeno una parte significativa corretta ma e incompleta, imprecisa o manca passaggi essenziali.
- Usa \"errato\" in tutti gli altri casi: risposta sbagliata, vaga, fuori tema, contraddittoria o troppo generica.
- Se la risposta contiene errori sostanziali, NON classificarla come corretta per incoraggiamento.
- Non usare etichette diverse da: corretto, parzialmente corretto, errato.
- Non scrivere mai frasi come \"risposta corretta, bravo\" se la classificazione non e davvero \"corretto\".

FORMATO OBBLIGATORIO:
<etichetta>: <feedback breve e costruttivo>
Risposta attesa: <risposta corretta o elementi essenziali attesi>
Riferimenti: <uno o piu nomi file del contesto>
"""

    def _default_references(self, context_chunks: list[dict]) -> str:
        filenames = []
        for chunk in context_chunks:
            filename = chunk.get("filename")
            if filename and filename not in filenames:
                filenames.append(filename)
        return ", ".join(filenames[:3]) if filenames else "materiale di studio"

    def _normalize_quiz_question(self, raw_question: str, context_chunks: list[dict]) -> str:
        question_match = re.search(r"(?im)^domanda\s*:\s*(.+)$", raw_question)
        source_match = re.search(r"(?im)^fonte\s*:\s*(.+)$", raw_question)

        question = question_match.group(1).strip() if question_match else ""
        source = source_match.group(1).strip() if source_match else ""

        if not question:
            collected = []
            for line in raw_question.splitlines():
                stripped = line.strip().strip("-* ")
                if not stripped:
                    if collected:
                        break
                    continue

                if re.match(
                    r"(?i)^(fonte|risposta|soluzione|feedback|spiegazione|valutazione|corretto|parzialmente corretto|errato)\s*[:\-]",
                    stripped,
                ):
                    break
                collected.append(stripped)

            question = " ".join(collected).strip()

        question = re.sub(r"\s+", " ", question)
        question = re.sub(r"(?i)^domanda\s*[:\-]\s*", "", question).strip()

        if not question:
            question = "Spiega i concetti principali contenuti nel brano selezionato."

        if not question.endswith("?"):
            question += "?"

        references = source or self._default_references(context_chunks)
        return f"{question}\n\n(Fonte: {references})"

    def extract_quiz_feedback_label(self, feedback: str) -> str:
        normalized = feedback.strip().lower()
        if normalized.startswith("parzialmente corretto"):
            return "parzialmente corretto"
        if normalized.startswith("corretto"):
            return "corretto"
        if normalized.startswith("errato"):
            return "errato"

        fallback_match = re.search(
            r"(?i)\b(parzialmente corretto|corretto|errato|errata|sbagliato)\b",
            normalized,
        )
        if not fallback_match:
            return "errato"

        label = fallback_match.group(1).lower()
        if label == "parzialmente corretto":
            return label
        if label in {"errato", "errata", "sbagliato"}:
            return "errato"
        return "corretto"

    def _normalize_quiz_feedback(self, raw_feedback: str, context_chunks: list[dict]) -> str:
        label = self.extract_quiz_feedback_label(raw_feedback)
        body = raw_feedback.strip()
        body = re.sub(r"(?im)^verdetto\s*:\s*", "", body, count=1).strip()
        label_pattern = r"parzialmente corretto|corretto|errato|errata|sbagliato"
        body = re.sub(
            rf"(?is)^\s*(?:{label_pattern})\s*[:\-]?\s*",
            "",
            body,
            count=1,
        ).strip()

        if not body:
            body = (
                "Consulta i riferimenti indicati e confronta la tua risposta con gli elementi "
                "essenziali presenti nel materiale di studio."
            )

        if not re.search(r"(?im)^risposta attesa\s*:", body):
            body = (
                f"{body.rstrip()}\n"
                "Risposta attesa: verifica gli elementi essenziali indicati nei riferimenti e "
                "confrontali con il testo corretto presente nel materiale di studio."
            )

        if not re.search(r"(?im)^riferimenti\s*:", body):
            body = f"{body.rstrip()}\nRiferimenti: {self._default_references(context_chunks)}"

        return f"{label}: {body}".strip()

    def answer_question(
        self, question: str, context_chunks: list[dict], history: list[dict] = None
    ) -> str:
        """Rispondi a una domanda dell'utente usando solo il materiale fornito."""
        system = self._build_reference_mode_system_prompt(context_chunks)
        return self._chat(system, question, history=history)

    def answer_question_stream(
        self, question: str, context_chunks: list[dict], history: list[dict] = None
    ) -> Iterator[str]:
        """Stream answer tokens."""
        system = self._build_reference_mode_system_prompt(context_chunks)
        yield from self._chat_stream(system, question, history=history)

    def generate_question(
        self, context_chunks: list[dict], previous_questions: list[str] = None
    ) -> str:
        """Generate a quiz question from context."""
        system = self._build_quiz_question_system_prompt(context_chunks)
        avoid = ""
        if previous_questions:
            avoid = "\n\nEvita di ripetere le domande precedenti:\n" + "\n".join(
                f"- {q}" for q in previous_questions[-5:]
            )

        raw_question = self._chat(
            system,
            f"Genera una sola domanda da quiz basata sul materiale di studio.{avoid}",
            temperature=0.3,
            num_predict=256,
        )
        return self._normalize_quiz_question(raw_question, context_chunks)

    def evaluate_answer(
        self, question: str, user_answer: str, context_chunks: list[dict]
    ) -> str:
        """Valuta la risposta dell'utente basandoti sul materiale di studio fornito."""
        system = self._build_quiz_evaluation_system_prompt(context_chunks)
        prompt = f"""Domanda del Quiz: {question}

Risposta dell'utente: {user_answer}

Valuta la risposta seguendo rigorosamente il formato obbligatorio."""
        raw_feedback = self._chat(system, prompt, temperature=0.1, num_predict=512)
        return self._normalize_quiz_feedback(raw_feedback, context_chunks)

    def evaluate_answer_stream(
        self, question: str, user_answer: str, context_chunks: list[dict]
    ) -> Iterator[str]:
        """Stream evaluation of a user's quiz answer."""
        yield self.evaluate_answer(question, user_answer, context_chunks)
