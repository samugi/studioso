"""
rag.py — Document ingestion, chunking, embedding, and retrieval.
Supports: PDF, DOCX, TXT, MD
"""

import os
import hashlib
import re
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

console = Console()

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


# ─── Text Extraction ──────────────────────────────────────────────────────────

def extract_text_from_pdf(path: Path) -> str:
    import fitz  # pymupdf
    doc = fitz.open(str(path))
    pages = []
    for page in doc:
        pages.append(page.get_text())
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
        elif ext == ".docx":
            return extract_text_from_docx(path)
        elif ext in (".txt", ".md"):
            return extract_text_from_txt(path)
    except Exception as e:
        console.print(f"  [yellow]⚠ Could not read {path.name}: {e}[/yellow]")
    return None


# ─── Chunking ─────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks, preferring paragraph/sentence boundaries."""
    text = re.sub(r'\n{3,}', '\n\n', text.strip())
    
    # Try to split on paragraphs first
    paragraphs = re.split(r'\n\n+', text)
    
    chunks = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current) + len(para) + 2 <= chunk_size:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
                # keep overlap
                overlap_text = current[-overlap:] if len(current) > overlap else current
                current = overlap_text + "\n\n" + para
            else:
                # paragraph itself is too big — split by sentences
                sentences = re.split(r'(?<=[.!?])\s+', para)
                for sentence in sentences:
                    if len(current) + len(sentence) + 1 <= chunk_size:
                        current = (current + " " + sentence).strip()
                    else:
                        if current:
                            chunks.append(current)
                            overlap_text = current[-overlap:] if len(current) > overlap else current
                            current = overlap_text + " " + sentence
                        else:
                            # Single sentence bigger than chunk_size — just add it
                            chunks.append(sentence)
                            current = ""

    if current.strip():
        chunks.append(current.strip())

    return [c for c in chunks if len(c.strip()) > 30]


# ─── RAG Engine ───────────────────────────────────────────────────────────────

class RAGEngine:
    def __init__(self, config: dict):
        self.config = config
        self.study_folder = Path(config["study_folder"]).resolve()
        self.embedding_model_name = config.get("embedding_model", "all-MiniLM-L6-v2")
        self.chunk_size = config.get("chunk_size", 800)
        self.chunk_overlap = config.get("chunk_overlap", 100)
        self.top_k = config.get("retrieval_top_k", 5)

        # ChromaDB is isolated per selected study folder or subfolder.
        folder_key = hashlib.md5(str(self.study_folder).encode("utf-8")).hexdigest()[:12]
        db_dir = self.study_folder.parent / ".study_agent_db" / f"{self.study_folder.name}_{folder_key}"
        db_dir.mkdir(parents=True, exist_ok=True)
        self.db_dir = db_dir

        self._embedder: Optional[SentenceTransformer] = None
        self._chroma_client: Optional[chromadb.Client] = None
        self._collection = None

    def _get_embedder(self) -> SentenceTransformer:
        if self._embedder is None:
            console.print(f"[dim]Loading embedding model ({self.embedding_model_name})...[/dim]")
            self._embedder = SentenceTransformer(self.embedding_model_name)
        return self._embedder

    def _get_collection(self):
        if self._collection is None:
            self._chroma_client = chromadb.PersistentClient(
                path=str(self.db_dir),
                settings=Settings(anonymized_telemetry=False)
            )
            self._collection = self._chroma_client.get_or_create_collection(
                name="study_materials",
                metadata={"hnsw:space": "cosine"}
            )
        return self._collection

    def _file_hash(self, path: Path) -> str:
        h = hashlib.md5()
        h.update(str(path.stat().st_mtime).encode())
        h.update(str(path.stat().st_size).encode())
        h.update(str(path).encode())
        return h.hexdigest()

    def _indexed_hashes(self) -> set[str]:
        collection = self._get_collection()
        try:
            results = collection.get(include=["metadatas"])
            return {m.get("file_hash", "") for m in results["metadatas"] if m}
        except Exception:
            return set()

    def ingest(self, force: bool = False) -> int:
        """Scan study folder, ingest new/changed documents. Returns count of new chunks."""
        if not self.study_folder.exists():
            console.print(f"[red]Study folder not found: {self.study_folder}[/red]")
            return 0

        files = [
            f for f in self.study_folder.rglob("*")
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
        ]

        if not files:
            console.print(f"[yellow]No supported files found in {self.study_folder}[/yellow]")
            return 0

        existing_hashes = self._indexed_hashes() if not force else set()
        collection = self._get_collection()
        embedder = self._get_embedder()

        new_chunks_total = 0
        files_processed = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            task = progress.add_task("Indexing documents...", total=len(files))

            for file_path in files:
                file_hash = self._file_hash(file_path)
                progress.update(task, description=f"[dim]{file_path.name}[/dim]")

                if file_hash in existing_hashes and not force:
                    progress.advance(task)
                    continue

                # Remove old chunks from this file
                try:
                    old = collection.get(where={"source": str(file_path)})
                    if old["ids"]:
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

                # Embed and store
                embeddings = embedder.encode(chunks, show_progress_bar=False).tolist()
                ids = [f"{file_hash}_{i}" for i in range(len(chunks))]
                metadatas = [
                    {
                        "source": str(file_path),
                        "filename": file_path.name,
                        "chunk_index": i,
                        "file_hash": file_hash,
                    }
                    for i in range(len(chunks))
                ]

                # Batch insert
                batch_size = 100
                for i in range(0, len(chunks), batch_size):
                    collection.add(
                        documents=chunks[i:i+batch_size],
                        embeddings=embeddings[i:i+batch_size],
                        ids=ids[i:i+batch_size],
                        metadatas=metadatas[i:i+batch_size],
                    )

                new_chunks_total += len(chunks)
                files_processed += 1
                progress.advance(task)

        return new_chunks_total

    def retrieve(self, query: str) -> list[dict]:
        """Retrieve top-k relevant chunks for a query."""
        collection = self._get_collection()
        embedder = self._get_embedder()

        if collection.count() == 0:
            return []

        query_embedding = embedder.encode([query]).tolist()
        results = collection.query(
            query_embeddings=query_embedding,
            n_results=min(self.top_k, collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        chunks = []
        if results["documents"] and results["documents"][0]:
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                chunks.append({
                    "text": doc,
                    "filename": meta.get("filename", "unknown"),
                    "source": meta.get("source", ""),
                    "relevance": round(1 - dist, 3),  # cosine similarity
                })

        return chunks

    def get_all_chunks_sample(self, n: int = 20) -> list[dict]:
        """Get a random sample of chunks (used for quiz question generation)."""
        collection = self._get_collection()
        if collection.count() == 0:
            return []
        results = collection.get(
            limit=n,
            include=["documents", "metadatas"],
        )
        chunks = []
        for doc, meta in zip(results["documents"], results["metadatas"]):
            chunks.append({
                "text": doc,
                "filename": meta.get("filename", "unknown"),
            })
        return chunks

    def collection_count(self) -> int:
        try:
            return self._get_collection().count()
        except Exception:
            return 0

    def indexed_files(self) -> list[str]:
        try:
            results = self._get_collection().get(include=["metadatas"])
            names = {m.get("filename", "?") for m in results["metadatas"] if m}
            return sorted(names)
        except Exception:
            return []
