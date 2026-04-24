from pathlib import Path

from src.rag import RAGEngine


def test_rag_db_dir_changes_for_subfolders(tmp_path):
    base = tmp_path / "materials"
    sub = base / "accademia" / "diritto"
    base.mkdir(parents=True)
    sub.mkdir(parents=True)

    rag_base = RAGEngine({"study_material": str(base)})
    rag_sub = RAGEngine({"study_material": str(sub)})

    assert rag_base.study_folder == base.resolve()
    assert rag_sub.study_folder == sub.resolve()
    assert rag_base.db_dir != rag_sub.db_dir
    assert rag_base.db_dir.name.startswith("materials_")
    assert rag_sub.db_dir.name.startswith("diritto_")


def test_rag_db_dir_changes_when_embedding_or_chunking_changes(tmp_path):
    base = tmp_path / "materials"
    base.mkdir(parents=True)

    rag_default = RAGEngine({"study_material": str(base)})
    rag_embedding = RAGEngine(
        {
            "study_material": str(base),
            "embedding_model": "all-MiniLM-L6-v2",
        }
    )
    rag_chunking = RAGEngine(
        {
            "study_material": str(base),
            "chunk_size": 900,
            "chunk_overlap": 120,
        }
    )

    assert rag_default.db_dir != rag_embedding.db_dir
    assert rag_default.db_dir != rag_chunking.db_dir


def test_build_reference_query_uses_last_user_turn_for_followups(tmp_path):
    rag = RAGEngine({"study_material": str(tmp_path)})

    query = rag.build_reference_query(
        "E questo?",
        history=[
            {"role": "user", "content": "Spiegami il silenzio assenso"},
            {"role": "assistant", "content": "..."},
        ],
    )

    assert "Spiegami il silenzio assenso" in query
    assert "E questo?" in query


def test_build_reference_query_keeps_standalone_question_as_is(tmp_path):
    rag = RAGEngine({"study_material": str(tmp_path)})

    query = rag.build_reference_query(
        "Qual e la definizione di tributo?",
        history=[{"role": "user", "content": "Domanda precedente"}],
    )

    assert query == "Qual e la definizione di tributo?"


def test_merge_chunks_preserves_order_and_deduplicates(tmp_path):
    rag = RAGEngine({"study_material": str(tmp_path)})

    merged = rag.merge_chunks(
        [
            {"id": "a", "text": "1"},
            {"id": "b", "text": "2"},
        ],
        [
            {"id": "b", "text": "2"},
            {"id": "c", "text": "3"},
        ],
        limit=3,
    )

    assert [chunk["id"] for chunk in merged] == ["a", "b", "c"]


def test_fuse_candidates_applies_minimum_threshold(tmp_path):
    rag = RAGEngine({"study_material": str(tmp_path)})

    fused = rag._fuse_candidates(
        [
            {"id": "a", "vector_score": 0.6, "lexical_score": 0.0, "relevance": 0.6},
            {"id": "b", "vector_score": 0.2, "lexical_score": 0.0, "relevance": 0.2},
        ],
        [
            {"id": "a", "vector_score": 0.0, "lexical_score": 0.5, "relevance": 0.5},
            {"id": "c", "vector_score": 0.0, "lexical_score": 0.1, "relevance": 0.1},
        ],
        top_k=5,
        min_score=0.35,
    )

    assert [chunk["id"] for chunk in fused] == ["a"]


def test_rag_supports_single_file_material(tmp_path):
    material = tmp_path / "single.md"
    material.write_text("# Titolo\n\nContenuto di prova", encoding="utf-8")

    rag = RAGEngine({"study_material": str(material)})

    assert rag.material_exists() is True
    assert rag.material_label() == "file"
    assert rag.list_source_files() == [material.resolve()]
    assert rag.db_dir.name.startswith("single_")
