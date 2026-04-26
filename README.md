# Study Agent

Local study assistant for working with your own study materials.

It answers only from user-provided material, uses an English app interface by default, and supports reference, quiz, and review modes.

## Main Features

- fully local usage through Ollama
- grounded answers based on uploaded study material
- supports either a whole folder or a single file through `study_material`
- English CLI and app interface by default
- nearest local `AGENT.md` override for subject-specific behavior and language
- hybrid vector + lexical retrieval
- quiz mode with open-ended questions suited to longer written answers
- review mode for questions previously answered incorrectly or partially correctly
- prompt-driven evaluation labels and output formatting

## Requirements

- Python 3.10+
- Ollama installed and running
- recommended machine: 16 GB RAM + 6 GB VRAM

## Recommended Model

Recommended default in `config.yaml`:

```yaml
ollama_model: "qwen2.5:7b"
```

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
- `agent_config`: global fallback prompt/rules file

`study_folder` is still accepted as a legacy alias, but the canonical key is `study_material`.

## `AGENT.md` Resolution

The root `AGENT.md` is the global fallback.

When you choose a `study_material`, the app looks for the nearest `AGENT.md` in that subtree.

Examples:

- if you select `materials/foo` and `materials/foo/AGENT.md` exists, that file is used
- if you select `materials/bar/zap` and only `materials/bar/AGENT.md` exists, that file is used
- if no nearer file exists, the root `AGENT.md` is used

This allows per-subject customization of:

- interaction language
- prompt wording
- output labels
- quiz behavior
- domain-specific evaluation rules


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
- feedback labels come from the active `AGENT.md`
- quiz scoring and review persistence work with both English and Italian label sets

Feedback separates:

- content
- language form
- expected answer
- references

### 3. Review Mode

Replays questions previously answered incorrectly or partially correctly.

- separate namespace for the current material
- works with either a single file or a folder
- uses local storage in `.study_agent_review/`

## OCR And Image-Based PDFs

The system reads extractable text from PDFs.

So:

- PDFs with a valid OCR text layer are supported
- image-only PDFs without extractable text are not reliably supported

## Project Structure

```text
study-agent/
├── AGENT.md
├── config.yaml
├── main.py
├── README.md
├── materials/
│   ├── README.md
│   ├── unipd/
│   │   ├── AGENT.md
│   │   ├── Bando_2026N14_0.pdf
│   │   └── studiare/
│   └── ...
├── requirements.txt
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
