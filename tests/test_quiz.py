from unittest.mock import Mock

from src.modes.quiz import QuestionPrefetcher


def test_prefetcher_preloads_and_consumes_next_question():
    agent = Mock()
    rag = Mock()
    rag.get_all_chunks_sample.return_value = [
        {"text": "a", "filename": "a.txt"},
        {"text": "b", "filename": "b.txt"},
        {"text": "c", "filename": "c.txt"},
        {"text": "d", "filename": "d.txt"},
        {"text": "e", "filename": "e.txt"},
    ]
    agent.generate_question.return_value = "Domanda pronta?\n\n(Fonte: a.txt)"

    prefetcher = QuestionPrefetcher(agent, rag)
    prefetcher.start(["Prima domanda?"])

    question, chunks = prefetcher.consume(["Prima domanda?"])

    assert question.startswith("Domanda pronta?")
    assert len(chunks) == 5
    agent.generate_question.assert_called_once()


def test_prefetcher_falls_back_to_sync_generation_if_needed():
    agent = Mock()
    rag = Mock()
    rag.get_all_chunks_sample.return_value = [
        {"text": "a", "filename": "a.txt"},
        {"text": "b", "filename": "b.txt"},
        {"text": "c", "filename": "c.txt"},
        {"text": "d", "filename": "d.txt"},
        {"text": "e", "filename": "e.txt"},
    ]
    agent.generate_question.return_value = "Domanda sync?\n\n(Fonte: a.txt)"

    prefetcher = QuestionPrefetcher(agent, rag)
    question, chunks = prefetcher.consume([])

    assert question.startswith("Domanda sync?")
    assert len(chunks) == 5
