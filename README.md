# Study Agent 📚

A local AI study assistant that answers questions and quizzes you — **strictly from your own documents**.
No hallucinations, no internet required, everything stays on your machine.

---

## How It Works

1. You drop your study materials (PDF, DOCX, TXT, MD) into a folder.
2. The agent indexes them using local embeddings (runs entirely offline).
3. You choose a mode: ask it questions, or have it quiz you.
4. Every answer and every question is grounded in your documents — nothing is made up.

---

## Requirements

| What | Details |
|------|---------|
| Python | 3.10 or newer |
| RAM | 8–16 GB (16 GB recommended) |
| Disk | ~5–10 GB for the model |
| OS | macOS, Windows, Linux |

---

## First-Time Setup (do this once)

### Step 1 — Install Ollama
Download and install from **[ollama.com/download](https://ollama.com/download)**

- **macOS**: Download the `.dmg`, open it, drag to Applications.
- **Windows**: Download the `.exe` installer and run it.
- **Linux**: `curl -fsSL https://ollama.com/install.sh | sh`

### Step 2 — Install Python (if you don't have it)
Download from **[python.org/downloads](https://www.python.org/downloads/)**

> Windows: During installation, **check "Add Python to PATH"**.

### Step 3 — Run setup

Open a terminal in this folder and run:

```bash
python setup.py
```

This will install all dependencies and create your `materials/` folder.

---

## Starting the Agent

### Option A — Double-click launcher
- **macOS/Linux**: Double-click `start.sh`  
  *(First time: right-click → Open, to bypass Gatekeeper)*
- **Windows**: Double-click `start.bat`

### Option B — Terminal
```bash
# Make sure Ollama is running first
ollama serve

# Then in a new terminal, from the study-agent folder:
python main.py
```

---

## Adding Your Study Materials

Drop files into the `materials/` folder. Supported formats:
- **PDF** (`.pdf`)
- **Word** (`.docx`)
- **Plain text** (`.txt`)
- **Markdown** (`.md`)

Subfolders work fine — the agent scans everything recursively.

The agent auto-detects new and changed files every time you start it.

To force a full reindex (e.g., after deleting files):
```bash
python main.py --reindex
```

---

## Switching Subjects

### Option A — Swap folder contents
Replace the files in `materials/` and run `python main.py --reindex`.

### Option B — Multiple subject folders
Keep separate folders and point to them at launch:
```bash
python main.py --folder ./materials/biology
python main.py --folder ./materials/chemistry
python main.py --folder /Users/yourname/Documents/law-notes
```

Or permanently change `study_folder` in `config.yaml`.

---

## Modes

### 🔵 Q&A Mode
You ask, the agent answers — only from your documents.

- Type your question naturally.
- The agent shows which document the answer came from.
- It'll tell you honestly if the answer isn't in your materials.
- Conversation history is maintained within a session.

**Commands in Q&A mode:**
| Command | Effect |
|---------|--------|
| `/back` | Return to main menu |
| `/sources` | Toggle source citations on/off |
| `/clear` | Clear conversation history |
| `/files` | List indexed documents |

### 🟡 Quiz Mode
The agent asks, you answer, it evaluates.

- Choose how many questions.
- Each question is generated from a random part of your materials.
- After you answer, the agent evaluates: correct / partial / wrong.
- Feedback includes what you got right, what you missed, and the correct answer.
- Final score shown at the end.

**Commands in Quiz mode:**
| Command | Effect |
|---------|--------|
| `/back` | Return to main menu |
| `/skip` | Skip a question |

---

## Customizing Behavior

Edit `AGENT.md` to change how the agent behaves:
- Tone (encouraging, strict, casual…)
- Difficulty adaptation rules
- How it evaluates partial answers
- Response language (auto-detects by default)

This file works just like `CLAUDE.md` in Claude Code — it's the agent's "instruction manual".

Edit `config.yaml` to change:
- Study folder path
- AI model (see model recommendations below)
- How many document chunks to retrieve per query
- Quiz session length
- Whether to show source citations

---

## Model Recommendations (16 GB RAM)

| Model | Command | Notes |
|-------|---------|-------|
| `mistral:7b` | `ollama pull mistral:7b` | **Recommended default** — fast, accurate |
| `llama3.1:8b` | `ollama pull llama3.1:8b` | Higher quality, a bit slower |
| `llama3.2:3b` | `ollama pull llama3.2:3b` | Very fast, good for quick use |
| `phi3:mini` | `ollama pull phi3:mini` | Smallest/fastest option |

Change model in `config.yaml`:
```yaml
ollama_model: "llama3.1:8b"
```

---

## Command-Line Options

```bash
python main.py --help                          # show options
python main.py --config other-config.yaml      # use a different config
python main.py --folder ./materials/history    # override study folder
python main.py --model llama3.2:3b             # override model
python main.py --reindex                       # force reindex and exit
```

---

## Troubleshooting

**"Ollama is not running"**  
→ Run `ollama serve` in a terminal and keep it open.

**"Model not found"**  
→ The agent will auto-download it on first run. Takes a few minutes once.

**"No relevant content found"**  
→ Try rephrasing. Or check that you loaded the right folder.

**Answers seem unrelated to my documents**  
→ Run `python main.py --reindex` to force a fresh index.

**Slow responses**  
→ Switch to a smaller model in `config.yaml` (e.g., `llama3.2:3b`).

---

## Project Structure

```
study-agent/
├── AGENT.md              ← behavior config (edit to customize the agent)
├── config.yaml           ← settings (folder, model, etc.)
├── main.py               ← entry point
├── setup.py              ← one-time setup
├── start.sh              ← macOS/Linux launcher
├── start.bat             ← Windows launcher
├── requirements.txt      ← Python dependencies
├── materials/            ← put your study documents here
└── src/
    ├── agent.py          ← Ollama integration, prompts
    ├── rag.py            ← document indexing and retrieval
    ├── modes/
    │   ├── qa.py         ← Q&A mode
    │   └── quiz.py       ← Quiz mode
    └── ui/
        └── cli.py        ← terminal interface
```

---

## Privacy

Everything runs locally:
- The model runs on your machine via Ollama.
- Documents are indexed locally in a `.study_agent_db/` folder.
- No data ever leaves your machine.
- No API keys required.
