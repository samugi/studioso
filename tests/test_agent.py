from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from src.agent import StudyAgent


class FakeChatResponse:
    def __init__(self, content: str):
        self.message = SimpleNamespace(content=content)


class FakeClient:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        content = self.responses.pop(0) if self.responses else ""
        if kwargs.get("stream"):
            return [FakeChatResponse(content)]
        return FakeChatResponse(content)

    def list(self):
        return SimpleNamespace(models=[])

    def pull(self, *_args, **_kwargs):
        return []


def make_agent(fake_client: FakeClient) -> StudyAgent:
    config = {
        "agent_config": str(Path("AGENT.md").resolve()),
        "ollama_model": "fake-model",
        "ollama_url": "http://fake",
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
    assert "CONTESTO DEL MATERIALE DI STUDIO" in sent_messages[0]["content"]
    assert sent_messages[1] == history[0]
    assert sent_messages[-1]["role"] == "user"
    assert "domanda utente" in sent_messages[-1]["content"]


def test_generate_question_uses_prompt_config_and_normalizes_output():
    client = FakeClient(["DOMANDA: Che cos'e un tributo\nFONTE: diritto.pdf"])
    agent = make_agent(client)

    result = agent.generate_question([
        {"text": "contesto", "filename": "diritto.pdf", "source": "diritto.pdf"}
    ])

    assert result.startswith("Che cos'e un tributo?")
    assert "(FONTE: diritto.pdf)" in result


def test_generate_question_strips_accidental_feedback_lines():
    client = FakeClient(["Che cos'e il tributo\nfeedback: bravo\nFONTE: diritto.pdf"])
    agent = make_agent(client)

    result = agent.generate_question([
        {"text": "contesto", "filename": "diritto.pdf", "source": "diritto.pdf"}
    ])

    assert "feedback" not in result.lower()
    assert result.startswith("Che cos'e il tributo?")


def test_evaluate_answer_keeps_wrong_label_when_user_is_confident():
    client = FakeClient([
        "errato: la risposta non coincide con il materiale\nRisposta attesa: risposta vera\nRiferimenti: diritto.pdf"
    ])
    agent = make_agent(client)

    result = agent.evaluate_answer(
        "Domanda?",
        "Sono sicurissimo che sia cosi.",
        [{"text": "contesto", "filename": "diritto.pdf", "source": "diritto.pdf"}],
    )

    assert result.startswith("errato:")


def test_extract_quiz_feedback_label_defaults_to_wrong_when_missing():
    client = FakeClient([])
    agent = make_agent(client)

    assert agent.extract_quiz_feedback_label("testo senza etichetta") == "errato"


def test_normalize_quiz_feedback_adds_missing_sections():
    client = FakeClient([])
    agent = make_agent(client)

    result = agent._normalize_quiz_feedback(
        "corretto: buona risposta",
        [{"text": "contesto", "filename": "diritto.pdf", "source": "diritto.pdf"}],
    )

    assert result.startswith("corretto:")
    assert "Risposta attesa:" in result
    assert "Riferimenti: diritto.pdf" in result


def test_normalize_uses_configurable_labels():
    client = FakeClient([])
    agent = make_agent(client)

    question = agent._normalize_quiz_question(
        "DOMANDA: Qual e il principio?\nFONTE: fonte.pdf",
        [{"text": "contesto", "filename": "fonte.pdf", "source": "fonte.pdf"}],
    )
    feedback = agent._normalize_quiz_feedback(
        "corretto: bene",
        [{"text": "contesto", "filename": "fonte.pdf", "source": "fonte.pdf"}],
    )

    assert "(FONTE: fonte.pdf)" in question
    assert feedback.startswith("corretto:")
    assert "Risposta attesa:" in feedback


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
