from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from src.agent import QuizQuestionParseError, StudyAgent


class FakeChatResponse:
    def __init__(self, content: str, thinking: str | None = None, done_reason: str | None = None):
        self.message = SimpleNamespace(content=content, thinking=thinking)
        self.done_reason = done_reason


class FakeClient:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        payload = self.responses.pop(0) if self.responses else ""
        if isinstance(payload, dict):
            content = payload.get("content", "")
            thinking = payload.get("thinking")
            done_reason = payload.get("done_reason")
        else:
            content = payload
            thinking = None
            done_reason = None
        if kwargs.get("stream"):
            return [FakeChatResponse(content, thinking=thinking, done_reason=done_reason)]
        return FakeChatResponse(content, thinking=thinking, done_reason=done_reason)

    def list(self):
        return SimpleNamespace(models=[])

    def pull(self, *_args, **_kwargs):
        return []


def make_agent(fake_client: FakeClient, model: str = "fake-model", think="auto") -> StudyAgent:
    config = {
        "agent_config": str(Path("AGENT.md").resolve()),
        "ollama_model": model,
        "ollama_url": "http://fake",
        "ollama_think": think,
        "show_sources": True,
        "source_excerpt_length": 200,
    }
    with patch("src.agent.ollama.Client", return_value=fake_client):
        return StudyAgent(config)


def test_answer_question_sends_system_first_and_user_last():
    client = FakeClient(["Risposta"])
    agent = make_agent(client)

    history = [{"role": "assistant", "content": "storia"}]
    context = [{"text": "contenuto", "filename": "a.txt", "source": "s1"}]

    agent.answer_question("domanda utente", context, history=history)

    sent_messages = client.calls[0]["messages"]
    assert sent_messages[0]["role"] == "system"
    assert "STUDY MATERIAL CONTEXT" in sent_messages[0]["content"]
    assert sent_messages[1] == history[0]
    assert sent_messages[-1]["role"] == "user"
    assert "domanda utente" in sent_messages[-1]["content"]


def test_generate_question_uses_prompt_config_and_normalizes_output():
    client = FakeClient(["QUESTION: What is a tax?\nSOURCE: law.pdf"])
    agent = make_agent(client)

    result = agent.generate_question([
        {"text": "context", "filename": "law.pdf", "source": "law.pdf"}
    ])

    assert result.startswith("What is a tax?")
    assert "(SOURCE: law.pdf)" in result


def test_generate_question_strips_accidental_feedback_lines():
    client = FakeClient(["What is a tax\nfeedback: good\nSOURCE: law.pdf"])
    agent = make_agent(client)

    result = agent.generate_question([
        {"text": "context", "filename": "law.pdf", "source": "law.pdf"}
    ])

    assert "feedback" not in result.lower()
    assert result.startswith("What is a tax?")


def test_generate_question_ignores_prompt_leak_lines():
    client = FakeClient([
        "QUESTION: What are the EQF levels?\nSOURCE: eqf.pdf\n<system-reminder>\nmode change"
    ])
    agent = make_agent(client)

    result = agent.generate_question([
        {"text": "context", "filename": "eqf.pdf", "source": "eqf.pdf"}
    ])

    assert result.startswith("What are the EQF levels?")
    assert "system-reminder" not in result


def test_generate_question_raises_clear_error_when_output_is_empty():
    client = FakeClient(["", ""])
    agent = make_agent(client)

    try:
        agent.generate_question([
            {"text": "context", "filename": "ehea_internationalisation_and_mobility.txt", "source": "ehea_internationalisation_and_mobility.txt"}
        ])
        assert False, "Expected QuizQuestionParseError"
    except QuizQuestionParseError as exc:
        message = str(exc)

    assert "Could not parse a quiz question" in message
    assert "QUESTION:" in message
    assert "<empty output>" in message
    assert "Repair attempt output" in message


def test_generate_question_raises_clear_error_with_raw_model_output():
    client = FakeClient(["Explain the main concepts presented in the selected material", "Explain the main concepts presented in the selected material"])
    agent = make_agent(client)

    try:
        agent.generate_question([
            {"text": "context", "filename": "law.pdf", "source": "law.pdf"}
        ])
        assert False, "Expected QuizQuestionParseError"
    except QuizQuestionParseError as exc:
        message = str(exc)

    assert "prompt leakage or a placeholder" in message
    assert "selected material" in message


def test_generate_question_repairs_plain_text_output():
    client = FakeClient([
        "What are the EQF levels",
        "QUESTION: What are the EQF levels?\nSOURCE: eqf.pdf",
    ])
    agent = make_agent(client)

    result = agent.generate_question([
        {"text": "context", "filename": "eqf.pdf", "source": "eqf.pdf"}
    ])

    assert result.startswith("What are the EQF levels?")
    assert "(SOURCE: eqf.pdf)" in result
    assert len(client.calls) == 1


def test_generate_question_repairs_prompt_leakage_output():
    client = FakeClient([
        "Explain the main concepts presented in the selected material",
        "QUESTION: Explain the EQF levels and their practical implications for higher education recognition.\nSOURCE: eqf.pdf",
    ])
    agent = make_agent(client)

    result = agent.generate_question([
        {"text": "context", "filename": "eqf.pdf", "source": "eqf.pdf"}
    ])

    assert "selected material" not in result.lower()
    assert result.startswith("Explain the EQF levels")


def test_chat_retries_when_thinking_model_returns_only_thinking_first():
    client = FakeClient([
        {"content": "", "thinking": "Reasoning...", "done_reason": "length"},
        "QUESTION: What are the EQF levels?\nSOURCE: eqf.pdf",
    ])
    agent = make_agent(client, model="qwen3.5:4b", think="auto")

    result = agent.generate_question([
        {"text": "context", "filename": "eqf.pdf", "source": "eqf.pdf"}
    ])

    assert result.startswith("What are the EQF levels?")
    assert len(client.calls) == 2
    assert client.calls[0]["think"] is True
    assert client.calls[1]["options"]["num_predict"] > client.calls[0]["options"]["num_predict"]


def test_chat_keeps_thinking_disabled_for_non_thinking_models():
    client = FakeClient(["QUESTION: What is Bologna Process?\nSOURCE: process.pdf"])
    agent = make_agent(client, model="qwen2.5:7b", think="auto")

    result = agent.generate_question([
        {"text": "context", "filename": "process.pdf", "source": "process.pdf"}
    ])

    assert result.startswith("What is Bologna Process?")
    assert client.calls[0]["think"] is False


def test_evaluate_answer_keeps_wrong_label_when_user_is_confident():
    client = FakeClient([
        "wrong: the answer does not match the material\nExpected answer: the correct answer\nReferences: law.pdf"
    ])
    agent = make_agent(client)

    result = agent.evaluate_answer(
        "Domanda?",
        "Sono sicurissimo che sia cosi.",
        [{"text": "context", "filename": "law.pdf", "source": "law.pdf"}],
    )

    assert result.startswith("wrong:")


def test_extract_quiz_feedback_label_defaults_to_wrong_when_missing():
    client = FakeClient([])
    agent = make_agent(client)

    assert agent.extract_quiz_feedback_label("text without label") == "wrong"


def test_normalize_quiz_feedback_adds_missing_sections():
    client = FakeClient([])
    agent = make_agent(client)

    result = agent._normalize_quiz_feedback(
        "correct: good answer",
        [{"text": "context", "filename": "law.pdf", "source": "law.pdf"}],
    )

    assert result.startswith("correct:")
    assert "Content:" in result
    assert "Language form:" in result
    assert "Expected answer:" in result
    assert "References: law.pdf" in result


def test_normalize_uses_configurable_labels():
    client = FakeClient([])
    agent = make_agent(client)

    question = agent._normalize_quiz_question(
        "QUESTION: What is the principle?\nSOURCE: source.pdf",
        [{"text": "context", "filename": "source.pdf", "source": "source.pdf"}],
    )
    feedback = agent._normalize_quiz_feedback(
        "correct: good",
        [{"text": "context", "filename": "source.pdf", "source": "source.pdf"}],
    )

    assert "(SOURCE: source.pdf)" in question
    assert feedback.startswith("correct:")
    assert "Content:" in feedback
    assert "Language form:" in feedback
    assert "Expected answer:" in feedback


def test_answer_question_stream_uses_same_prompt_order():
    client = FakeClient(["stream"])
    agent = make_agent(client)

    chunks = list(
        agent.answer_question_stream(
            "domanda",
            [{"text": "contesto", "filename": "a.txt", "source": "s1"}],
        )
    )

    assert "stream" in "".join(chunks)
    assert client.calls[0]["messages"][0]["role"] == "system"
    assert client.calls[0]["messages"][-1]["role"] == "user"


def test_load_prompt_config_from_relative_path_in_temp_dir():
    with TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        copied = base / "AGENT.md"
        copied.write_text(Path("AGENT.md").read_text(encoding="utf-8"), encoding="utf-8")

        config = {
            "agent_config": str(copied),
            "ollama_model": "fake-model",
            "ollama_url": "http://fake",
        }
        with patch("src.agent.ollama.Client", return_value=FakeClient([])):
            agent = StudyAgent(config)

        assert agent.prompt_config.path == copied.resolve()


def test_normalize_quiz_feedback_uses_configurable_fallback_form_feedback():
    with TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        custom = base / "AGENT.md"
        content = Path("AGENT.md").read_text(encoding="utf-8")
        custom.write_text(
            content.replace(
                'default_references_fallback: "materiale di studio"',
                'default_references_fallback: "materiale di studio"\n    fallback_form_feedback: "If the writing can be improved, rewrite the answer more clearly in English."',
            ),
            encoding="utf-8",
        )

        config = {
            "agent_config": str(custom),
            "ollama_model": "fake-model",
            "ollama_url": "http://fake",
        }
        with patch("src.agent.ollama.Client", return_value=FakeClient([])):
            agent = StudyAgent(config)

        result = agent._normalize_quiz_feedback(
            "corretto: buona risposta",
            [{"text": "contesto", "filename": "fonte.pdf", "source": "fonte.pdf"}],
        )

        assert "If the writing can be improved" in result
