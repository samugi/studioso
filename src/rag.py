"""
rag.py - Document ingestion, chunking, embedding, and grounded retrieval.
Supports: PDF, DOCX, TXT, MD
"""

from __future__ import annotations

import hashlib
import random
import re
from collections import Counter
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from sentence_transformers import SentenceTransformer

console = Console()

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
TOKEN_RE = re.compile(r"\w+", re.UNICODE)
FOLLOW_UP_PREFIXES = (
    "e ",
    "ed ",
    "e questo",
    "e questa",
    "e quello",
    "e quella",
    "questo",
    "questa",
    "quello",
    "quella",
    "come",
    "perche",
    "perché",
    "quindi",
    "invece",
    "allora",
)


def extract_text_from_pdf(path: Path) -> str:
    import fitz

    doc = fitz.open(str(path))
    pages = [page.get_text() for page in doc]
    doc.close()
    return "\n\n".join(pages)


def extract_text_from_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def extract_text_from_txt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def extract_text(path: Path) -> Optional[str]:
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            return extract_text_from_pdf(path)
        if ext == ".docx":
            return extract_text_from_docx(path)
        if ext in {".txt", ".md"}:
            return extract_text_from_txt(path)
    except Exception as exc:
        console.print(f"  [yellow]⚠ Could not read {path.name}: {exc}[/yellow]")
    return None


def chunk_text(text: str, chunk_size: int = 600, overlap: int = 100) -> list[str]:
    """Split text into grounded chunks, preferring paragraph and sentence boundaries."""
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\n+", text) if paragraph.strip()]

    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= chunk_size:
            current = (current + "\n\n" + paragraph).strip()
            continue

        if current:
            chunks.append(current)
            overlap_text = current[-overlap:] if len(current) > overlap else current
            current = (overlap_text + "\n\n" + paragraph).strip()
            if len(current) <= chunk_size:
                continue

        current = ""
        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(current) + len(sentence) + 1 <= chunk_size:
                current = (current + " " + sentence).strip()
                continue
            if current:
                chunks.append(current)
            overlap_text = current[-overlap:] if current and len(current) > overlap else current
            current = (overlap_text + " " + sentence).strip()
            if len(current) > chunk_size:
                chunks.append(current)
                current = ""

    if current.strip():
        chunks.append(current.strip())

    return [chunk for chunk in chunks if len(chunk.strip()) > 30]


def tokenize(text: str) -> list[str]:
    return [token for token in TOKEN_RE.findall(text.lower()) if len(token) > 1]


class RAGEngine:
    def __init__(self, config: dict):
        self.config = config
        self.study_material = Path(
            config.get("study_material") or config.get("study_folder")
        ).resolve()
        self.study_folder = self.study_material
        self.embedding_model_name = config.get(
            "embedding_model", "intfloat/multilingual-e5-base"
        )
        self.chunk_size = config.get("chunk_size", 600)
        self.chunk_overlap = config.get("chunk_overlap", 100)
        self.top_k = config.get("retrieval_top_k", 6)
        self.candidate_k = config.get("retrieval_candidate_k", max(self.top_k * 3, 18))
        self.min_relevance = config.get("retrieval_min_relevance", 0.35)
        self.vector_weight = config.get("retrieval_vector_weight", 0.75)
        self.lexical_weight = config.get("retrieval_lexical_weight", 0.25)
        self.follow_up_max_chars = config.get("reference_followup_max_chars", 80)

        db_key = self._db_config_key()
        db_parent = self.study_material.parent
        db_name = self.study_material.stem if self.study_material.is_file() else self.study_material.name
        self.db_dir = db_parent / ".study_agent_db" / f"{db_name}_{db_key}"
        self.db_dir.mkdir(parents=True, exist_ok=True)

        self._embedder: Optional[SentenceTransformer] = None
        self._chroma_client: Optional[chromadb.Client] = None
        self._collection = None
        self._chunk_cache: list[dict] | None = None

    def _db_config_key(self) -> str:
        digest = hashlib.md5()
        digest.update(str(self.study_folder).encode("utf-8"))
        digest.update(self.embedding_model_name.encode("utf-8"))
        digest.update(str(self.chunk_size).encode("utf-8"))
        digest.update(str(self.chunk_overlap).encode("utf-8"))
        return digest.hexdigest()[:12]

    def _invalidate_cache(self):
        self._chunk_cache = None

    def _get_embedder(self) -> SentenceTransformer:
        if self._embedder is None:
            console.print(f"[dim]Loading embedding model ({self.embedding_model_name})...[/dim]")
            self._embedder = SentenceTransformer(self.embedding_model_name)
        return self._embedder

    def _get_collection(self):
        if self._collection is None:
            self._chroma_client = chromadb.PersistentClient(
                path=str(self.db_dir),
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = self._chroma_client.get_or_create_collection(
                name="study_materials",
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def _file_hash(self, path: Path) -> str:
        digest = hashlib.md5()
        digest.update(str(path.stat().st_mtime).encode())
        digest.update(str(path.stat().st_size).encode())
        digest.update(str(path).encode())
        return digest.hexdigest()

    def _indexed_hashes(self) -> set[str]:
        try:
            results = self._get_collection().get(include=["metadatas"])
            return {metadata.get("file_hash", "") for metadata in results["metadatas"] if metadata}
        except Exception:
            return set()

    def _relative_source(self, path: Path) -> str:
        try:
            if self.study_material.is_file():
                return path.name
            return str(path.resolve().relative_to(self.study_material))
        except ValueError:
            return path.name

    def material_exists(self) -> bool:
        return self.study_material.exists()

    def material_label(self) -> str:
        return "file" if self.study_material.is_file() else "cartella"

    def list_source_files(self) -> list[Path]:
        if not self.study_material.exists():
            return []
        if self.study_material.is_file():
            return [self.study_material] if self.study_material.suffix.lower() in SUPPORTED_EXTENSIONS else []
        return [
            path
            for path in self.study_material.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ]

    def _make_chunk_record(
        self,
        chunk_id: str,
        text: str,
        metadata: dict,
        *,
        vector_score: float = 0.0,
        lexical_score: float = 0.0,
        relevance: float | None = None,
    ) -> dict:
        if relevance is None:
            relevance = self.vector_weight * vector_score + self.lexical_weight * lexical_score

        return {
            "id": chunk_id,
            "text": text,
            "filename": metadata.get("filename", "unknown"),
            "source": metadata.get("source", ""),
            "relative_source": metadata.get("relative_source", metadata.get("filename", "unknown")),
            "chunk_index": metadata.get("chunk_index", -1),
            "vector_score": round(vector_score, 3),
            "lexical_score": round(lexical_score, 3),
            "relevance": round(max(0.0, min(1.0, relevance)), 3),
        }

    def _get_all_chunk_records(self) -> list[dict]:
        if self._chunk_cache is not None:
            return self._chunk_cache

        collection = self._get_collection()
        if collection.count() == 0:
            self._chunk_cache = []
            return self._chunk_cache

        results = collection.get(include=["documents", "metadatas"])
        ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])

        cache: list[dict] = []
        for chunk_id, document, metadata in zip(ids, documents, metadatas):
            if not metadata:
                continue
            cache.append(
                {
                    "id": chunk_id,
                    "text": document,
                    "metadata": metadata,
                    "tokens": Counter(tokenize(document)),
                    "text_lower": document.lower(),
                }
            )

        self._chunk_cache = cache
        return cache

    def _lexical_score(self, query: str, query_tokens: Counter[str], record: dict) -> float:
        if not query_tokens:
            return 0.0

        common = sum(
            min(query_tokens[token], record["tokens"].get(token, 0))
            for token in query_tokens
            if token in record["tokens"]
        )
        coverage = common / max(sum(query_tokens.values()), 1)
        phrase_bonus = 0.2 if len(query) > 12 and query.lower() in record["text_lower"] else 0.0
        return min(1.0, coverage + phrase_bonus)

    def _vector_candidates(self, query: str, n_results: int) -> list[dict]:
        collection = self._get_collection()
        if collection.count() == 0:
            return []

        query_embedding = self._get_embedder().encode([query]).tolist()
        results = collection.query(
            query_embeddings=query_embedding,
            n_results=min(n_results, collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        candidates: list[dict] = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for chunk_id, document, metadata, distance in zip(ids, docs, metas, distances):
            vector_score = max(0.0, 1 - float(distance))
            candidates.append(
                self._make_chunk_record(
                    chunk_id,
                    document,
                    metadata,
                    vector_score=vector_score,
                    lexical_score=0.0,
                    relevance=vector_score,
                )
            )
        return candidates

    def _lexical_candidates(self, query: str, n_results: int) -> list[dict]:
        query_tokens = Counter(tokenize(query))
        if not query_tokens:
            return []

        scored: list[tuple[float, dict]] = []
        for record in self._get_all_chunk_records():
            score = self._lexical_score(query, query_tokens, record)
            if score <= 0:
                continue
            scored.append((score, record))

        scored.sort(key=lambda item: item[0], reverse=True)
        candidates = []
        for score, record in scored[:n_results]:
            candidates.append(
                self._make_chunk_record(
                    record["id"],
                    record["text"],
                    record["metadata"],
                    vector_score=0.0,
                    lexical_score=score,
                    relevance=score,
                )
            )
        return candidates

    def _fuse_candidates(
        self,
        vector_candidates: list[dict],
        lexical_candidates: list[dict],
        *,
        top_k: int,
        min_score: float,
    ) -> list[dict]:
        merged: dict[str, dict] = {}

        for candidate in vector_candidates + lexical_candidates:
            merged.setdefault(candidate["id"], candidate.copy())
            merged[candidate["id"]]["vector_score"] = max(
                merged[candidate["id"]].get("vector_score", 0.0),
                candidate.get("vector_score", 0.0),
            )
            merged[candidate["id"]]["lexical_score"] = max(
                merged[candidate["id"]].get("lexical_score", 0.0),
                candidate.get("lexical_score", 0.0),
            )

        fused = []
        for candidate in merged.values():
            relevance = (
                self.vector_weight * candidate.get("vector_score", 0.0)
                + self.lexical_weight * candidate.get("lexical_score", 0.0)
            )
            if candidate.get("vector_score") and candidate.get("lexical_score"):
                relevance += 0.05
            candidate["relevance"] = round(max(0.0, min(1.0, relevance)), 3)
            fused.append(candidate)

        fused.sort(
            key=lambda item: (
                item["relevance"],
                item.get("vector_score", 0.0),
                item.get("lexical_score", 0.0),
            ),
            reverse=True,
        )
        return [candidate for candidate in fused if candidate["relevance"] >= min_score][:top_k]

    def build_reference_query(self, user_input: str, history: list[dict] | None = None) -> str:
        if not history:
            return user_input

        normalized = user_input.strip().lower()
        if not normalized:
            return user_input

        previous_user_inputs = [
            message["content"]
            for message in history
            if message.get("role") == "user" and message.get("content")
        ]
        if not previous_user_inputs:
            return user_input

        query_tokens = tokenize(normalized)
        is_short_ambiguous = len(normalized) <= self.follow_up_max_chars and len(query_tokens) <= 3
        is_follow_up = is_short_ambiguous or normalized.startswith(FOLLOW_UP_PREFIXES)
        if not is_follow_up:
            return user_input

        return (
            f"Contesto della conversazione recente: {previous_user_inputs[-1]}\n"
            f"Domanda attuale: {user_input}"
        )

    def ingest(self, force: bool = False) -> int:
        if not self.material_exists():
            console.print(f"[red]Study material not found: {self.study_material}[/red]")
            return 0

        files = self.list_source_files()
        if not files:
            console.print(f"[yellow]No supported files found in {self.study_material}[/yellow]")
            return 0

        existing_hashes = set() if force else self._indexed_hashes()
        collection = self._get_collection()
        embedder = self._get_embedder()

        new_chunks_total = 0
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            task = progress.add_task("Indexing documents...", total=len(files))
            for file_path in files:
                progress.update(task, description=f"[dim]{file_path.name}[/dim]")
                file_hash = self._file_hash(file_path)
                if file_hash in existing_hashes and not force:
                    progress.advance(task)
                    continue

                try:
                    old = collection.get(where={"source": str(file_path.resolve())})
                    if old.get("ids"):
                        collection.delete(ids=old["ids"])
                except Exception:
                    pass

                text = extract_text(file_path)
                if not text or len(text.strip()) < 50:
                    progress.advance(task)
                    continue

                chunks = chunk_text(text, self.chunk_size, self.chunk_overlap)
                if not chunks:
                    progress.advance(task)
                    continue

                embeddings = embedder.encode(chunks, show_progress_bar=False).tolist()
                ids = [f"{file_hash}_{index}" for index in range(len(chunks))]
                relative_source = self._relative_source(file_path)
                metadatas = [
                    {
                        "source": str(file_path.resolve()),
                        "relative_source": relative_source,
                        "filename": file_path.name,
                        "chunk_index": index,
                        "file_hash": file_hash,
                        "chunk_id": ids[index],
                    }
                    for index in range(len(chunks))
                ]

                batch_size = 100
                for start in range(0, len(chunks), batch_size):
                    end = start + batch_size
                    collection.add(
                        documents=chunks[start:end],
                        embeddings=embeddings[start:end],
                        ids=ids[start:end],
                        metadatas=metadatas[start:end],
                    )

                new_chunks_total += len(chunks)
                progress.advance(task)

        self._invalidate_cache()
        return new_chunks_total

    def retrieve(
        self,
        query: str,
        *,
        history: list[dict] | None = None,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> list[dict]:
        collection = self._get_collection()
        if collection.count() == 0:
            return []

        top_k = top_k or self.top_k
        min_score = self.min_relevance if min_score is None else min_score
        search_query = self.build_reference_query(query, history)

        vector_candidates = self._vector_candidates(search_query, self.candidate_k)
        lexical_candidates = self._lexical_candidates(search_query, self.candidate_k)
        return self._fuse_candidates(
            vector_candidates,
            lexical_candidates,
            top_k=top_k,
            min_score=min_score,
        )

    def merge_chunks(
        self,
        primary_chunks: list[dict],
        secondary_chunks: list[dict],
        *,
        limit: int | None = None,
    ) -> list[dict]:
        merged: list[dict] = []
        seen: set[str] = set()

        for chunk in primary_chunks + secondary_chunks:
            chunk_key = chunk.get("id") or f"{chunk.get('source')}::{chunk.get('chunk_index')}"
            if chunk_key in seen:
                continue
            merged.append(chunk)
            seen.add(chunk_key)
            if limit is not None and len(merged) >= limit:
                break
        return merged

    def get_all_chunks_sample(self, n: int = 20) -> list[dict]:
        records = self._get_all_chunk_records()
        if not records:
            return []
        sample_size = min(n, len(records))
        selected = random.sample(records, sample_size)
        return [
            self._make_chunk_record(record["id"], record["text"], record["metadata"])
            for record in selected
        ]

    def collection_count(self) -> int:
        try:
            return self._get_collection().count()
        except Exception:
            return 0

    def indexed_files(self) -> list[str]:
        try:
            results = self._get_collection().get(include=["metadatas"])
            names = {metadata.get("relative_source", metadata.get("filename", "?")) for metadata in results["metadatas"] if metadata}
            return sorted(names)
        except Exception:
            return []
