from pathlib import Path

from src.rag import RAGEngine


def test_rag_db_dir_changes_for_subfolders(tmp_path):
    base = tmp_path / "materials"
    sub = base / "accademia" / "diritto"
    base.mkdir(parents=True)
    sub.mkdir(parents=True)

    rag_base = RAGEngine({"study_folder": str(base)})
    rag_sub = RAGEngine({"study_folder": str(sub)})

    assert rag_base.study_folder == base.resolve()
    assert rag_sub.study_folder == sub.resolve()
    assert rag_base.db_dir != rag_sub.db_dir
    assert rag_base.db_dir.name.startswith("materials_")
    assert rag_sub.db_dir.name.startswith("diritto_")
