# Study Agent

Assistente di studio locale per la preparazione ai concorsi pubblici.

Lavora solo sui materiali caricati dall'utente, in italiano, con modalità reference, quiz e ripasso.

## Caratteristiche principali

- uso completamente locale tramite Ollama
- grounding sui materiali di studio caricati
- supporto a cartella intera o file singolo tramite `study_material`
- retrieval ibrido vettoriale + lessicale
- quiz con domande aperte orientate a risposte da prova scritta
- ripasso delle domande date in modo errato o parzialmente corretto
- feedback che separa chiaramente:
  - contenuto
  - forma italiana

## Requisiti

- Python 3.10+
- Ollama installato e in esecuzione
- macchina consigliata: 16 GB RAM + 6 GB VRAM

## Modello consigliato

Default consigliato in `config.yaml`:

```yaml
ollama_model: "qwen2.5:7b"
```

Subito sotto, la shortlist finale stimata dei 5 modelli migliori da provare, dal meno complesso al piu complesso, e:

- `qwen2.5:3b`
- `gemma3:4b`
- `qwen3:4b`
- `qwen3.5:4b`
- `qwen3:8b`

Altri modelli suggeriti sono commentati direttamente in `config.yaml`.

## Avvio rapido

1. Avvia Ollama:

```bash
ollama serve
```

2. Avvia il progetto:

```bash
python main.py
```

3. Oppure punta a un materiale specifico:

```bash
python main.py --material ./materials/diritto
python main.py --material ./materials/diritto/manuale.pdf
```

## Configurazione

La configurazione principale è in `config.yaml`.

Chiavi importanti:

- `study_material`: file o cartella di studio
- `ollama_model`: modello LLM
- `embedding_model`: modello embeddings
- `retrieval_top_k`: numero di chunk finali
- `retrieval_candidate_k`: candidati pre-fusione
- `retrieval_min_relevance`: soglia minima di rilevanza
- `chunk_size`, `chunk_overlap`: chunking del testo
- `agent_config`: file prompt/rules (`AGENT.md`)

`study_folder` è ancora accettato come alias legacy, ma la chiave canonica è `study_material`.

## Modalità

### 1. Modalita Reference

L'utente fa domande sui materiali caricati.

- retrieval history-aware per follow-up brevi o ambigui
- risposta grounded sui chunk recuperati
- se l'informazione non è supportata dai materiali, l'agente si astiene

### 2. Modalita Quiz

L'agente propone domande aperte da concorso.

- contesto piccolo e grounded
- preload della prossima domanda mentre l'utente legge il feedback
- `/skip` sostituisce la domanda con una nuova
- feedback con classificazione:
  - `corretto`
  - `parzialmente corretto`
  - `errato`

Il feedback separa sempre:

- `Contenuto`
- `Forma italiana`
- `Risposta attesa`
- `Riferimenti`

### 3. Modalita Ripasso

Ripropone domande già sbagliate o parzialmente corrette.

- namespace separato per il materiale corrente
- funziona sia con file singolo sia con cartella
- usa uno storage locale in `.study_agent_review/`

## OCR e PDF con immagini

Il sistema legge il testo estraibile dal PDF.

Quindi:

- PDF con layer OCR valido: sì, funziona
- PDF solo immagini senza testo estraibile: no, o molto male

## Struttura progetto

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

## Test

Esecuzione test:

```bash
./.venv/bin/python -m pytest tests
```

## Note

- Il DB vettoriale attuale è ChromaDB.
- Gli indici sono isolati per materiale, embedding e parametri di chunking.
- Se cambi embedding model o chunking, viene usato un namespace di indice diverso.
