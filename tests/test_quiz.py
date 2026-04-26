from unittest.mock import Mock

from src.modes.quiz import QuestionPrefetcher
from src.review_store import ReviewStore


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

    question_data = prefetcher.consume(["Prima domanda?"])

    assert question_data["text"].startswith("Domanda pronta?")
    assert len(question_data["source_chunks"]) == 5
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
    question_data = prefetcher.consume([])

    assert question_data["text"].startswith("Domanda sync?")
    assert len(question_data["source_chunks"]) == 5


def test_review_store_is_namespaced_by_study_material(tmp_path):
    first = tmp_path / "a" / "material.pdf"
    second = tmp_path / "b" / "material.pdf"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("x", encoding="utf-8")
    second.write_text("y", encoding="utf-8")

    first_store = ReviewStore(str(first))
    second_store = ReviewStore(str(second))

    assert first_store.path != second_store.path


def test_review_store_persists_only_wrong_or_partial_questions(tmp_path):
    material = tmp_path / "material.pdf"
    material.write_text("x", encoding="utf-8")
    store = ReviewStore(str(material))

    question_data = {"text": "Domanda?", "source_chunks": [{"id": "1", "text": "a"}]}
    store.add(question_data, "corretto")
    assert store.list_all() == []

    store.add(question_data, "errato")
    assert len(store.list_all()) == 1
    assert store.list_all()[0]["text"] == "Domanda?"


def test_review_store_persists_across_instances(tmp_path):
    material = tmp_path / "material.pdf"
    material.write_text("x", encoding="utf-8")

    first_store = ReviewStore(str(material))
    first_store.add({"text": "Q1", "source_chunks": []}, "errato")

    second_store = ReviewStore(str(material))

    assert [item["text"] for item in second_store.list_all()] == ["Q1"]


def test_review_store_removes_question_when_answer_becomes_correct(tmp_path):
    material = tmp_path / "material.pdf"
    material.write_text("x", encoding="utf-8")
    store = ReviewStore(str(material))

    question_data = {"text": "Domanda?", "source_chunks": []}
    store.add(question_data, "errato")
    store.add(question_data, "corretto")

    assert store.list_all() == []


def test_review_store_pop_many_removes_returned_items(tmp_path):
    material = tmp_path / "material.pdf"
    material.write_text("x", encoding="utf-8")
    store = ReviewStore(str(material))

    store.add({"text": "Q1", "source_chunks": []}, "errato")
    store.add({"text": "Q2", "source_chunks": []}, "parzialmente corretto")

    popped = store.pop_many(1)

    assert [item["text"] for item in popped] == ["Q1"]
    assert [item["text"] for item in store.list_all()] == ["Q2"]


def test_review_store_can_use_non_italian_labels(tmp_path):
    material = tmp_path / "material.pdf"
    material.write_text("x", encoding="utf-8")
    store = ReviewStore(str(material), retained_labels={"wrong", "partially correct"})

    store.add({"text": "Q1", "source_chunks": []}, "wrong")
    store.add({"text": "Q2", "source_chunks": []}, "partially correct")
    store.add({"text": "Q3", "source_chunks": []}, "correct")

    assert [item["text"] for item in store.list_all()] == ["Q1", "Q2"]
