# Study Agent

Local study assistant for working with your own study materials.

It answers only from user-provided material, works in Italian, and supports reference, quiz, and review modes.

## Main Features

- fully local usage through Ollama
- grounded answers based on uploaded study material
- supports either a whole folder or a single file through `study_material`
- hybrid vector + lexical retrieval
- quiz mode with open-ended questions suited to longer written answers
- review mode for questions previously answered incorrectly or partially correctly
- feedback that clearly separates:
  - content
  - Italian language form

## Requirements

- Python 3.10+
- Ollama installed and running
- recommended machine: 16 GB RAM + 6 GB VRAM

## Recommended Model

Recommended default in `config.yaml`:

```yaml
ollama_model: "qwen2.5:7b"
```

Below that, the current estimated top 5 models to try, from less complex to more complex, are:

- `qwen2.5:3b`
- `gemma3:4b`
- `qwen3:4b`
- `qwen3.5:4b`
- `qwen3:8b`

Other suggested models are commented directly in `config.yaml`.

## Quick Start

1. Start Ollama:

```bash
ollama serve
```

2. Run the project:

```bash
python main.py
```

3. Or point it to a specific study source:

```bash
python main.py --material ./materials/history
python main.py --material ./materials/history/notes.pdf
```

## Configuration

Main configuration lives in `config.yaml`.

Important keys:

- `study_material`: study file or folder
- `ollama_model`: LLM model
- `embedding_model`: embedding model
- `retrieval_top_k`: number of final chunks returned
- `retrieval_candidate_k`: candidates gathered before hybrid fusion
- `retrieval_min_relevance`: minimum relevance threshold
- `chunk_size`, `chunk_overlap`: text chunking settings
- `agent_config`: prompt/rules file (`AGENT.md`)

`study_folder` is still accepted as a legacy alias, but the canonical key is `study_material`.

## Modes

### 1. Reference Mode

The user asks questions about the loaded study material.

- history-aware retrieval for short or ambiguous follow-up questions
- grounded answers based on retrieved chunks
- if the information is not supported by the material, the agent abstains

### 2. Quiz Mode

The agent generates open-ended study questions.

- small, grounded context
- preloads the next question while the user reads feedback
- `/skip` replaces the current question with a new one
- feedback uses one of these classifications:
  - `corretto`
  - `parzialmente corretto`
  - `errato`

Feedback always separates:

- `Contenuto`
- `Forma italiana`
- `Risposta attesa`
- `Riferimenti`

### 3. Review Mode

Replays questions previously answered incorrectly or partially correctly.

- separate namespace for the current material
- works with either a single file or a folder
- uses local storage in `.study_agent_review/`

## OCR and Image-Based PDFs

The system reads extractable text from PDFs.

So:

- PDFs with a valid OCR text layer: yes, supported
- image-only PDFs without extractable text: no, or very poorly

## Project Structure

```text
study-agent/
├── AGENT.md
├── config.yaml
├── main.py
├── requirements.txt
├── materials/
└── src/
    ├── agent.py
    ├── prompt_config.py
    ├── rag.py
    ├── review_store.py
    ├── modes/
    │   ├── qa.py
    │   └── quiz.py
    └── ui/
        └── cli.py
```

## Tests

Run tests with:

```bash
./.venv/bin/python -m pytest tests
```

## Notes

- The current vector database is ChromaDB.
- Indexes are namespaced by material, embedding model, and chunking settings.
- If you change the embedding model or chunking configuration, a different index namespace is used.
