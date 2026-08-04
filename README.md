# PDAS — Platform Design Assistance System

Ship Design Office, Pakistan Navy. A retrieval-augmented reference assistant
over the office's design documents, running entirely offline: FastAPI backend,
local models through Ollama, Electron desktop client.

For air-gapped installation on the server, see **[README-DEPLOY.md](README-DEPLOY.md)**.
This file covers running it on a development machine.

---

## Prerequisites

- **Node 20+** and **Python 3.10+**
- **Ollama** — https://ollama.com. Needs a recent version: `qwen3.5:4b` returns
  `412: requires a newer version of Ollama` on 0.15.x.

```bash
ollama pull qwen3.5:4b      # ~2.5 GB  answering
ollama pull bge-m3          # ~1.2 GB  embeddings
```

## First run

```bash
# 1. Frontend
npm install

# 2. Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.in
.venv/bin/pip install -e .

# 3. A corpus. Either your own documents…
.venv/bin/pdas ingest /path/to/documents

#    …or the synthetic sample set, for trying it out
.venv/bin/python scripts/make_sample_docs.py
.venv/bin/pdas ingest sample-docs

# 4. An account — there are no default credentials
.venv/bin/pdas adduser PN-40218 --name "Lt Cdr Abbasi" --role admin

# 5. Check
.venv/bin/pdas status
```

## Running it

Two processes. Backend first:

```bash
cd backend
.venv/bin/pdas serve                 # http://127.0.0.1:8000
```

Then the desktop app, from the repo root:

```bash
npm run dev                          # Vite + Electron, hot reload
```

Sign in with the account from step 4. The server address is on the sign-in
screen under **Change** if the backend is not on `127.0.0.1:8000`.

### Other ways to run it

```bash
npm run preview                      # build the renderer, open in Electron
npm run dist                         # package an installer into release/
npm run dist -- --win                # Windows installer, for client PCs
```

## Configuration

Environment variables, or a `.env` file in `backend/`. All prefixed `PDAS_`:

| Variable | Default | |
|---|---|---|
| `PDAS_LLM_MODEL` | `qwen3.5:4b` | must be pulled in Ollama |
| `PDAS_EMBED_MODEL` | `bge-m3` | changing it requires `pdas reindex` |
| `PDAS_OLLAMA_HOST` | `http://127.0.0.1:11434` | |
| `PDAS_DATA_DIR` | `var` | database, index, stored documents |
| `PDAS_MAX_TOKENS` | `2560` | see "reasoning models" below |
| `PDAS_HOST` / `PDAS_PORT` | `127.0.0.1` / `8000` | |

```bash
PDAS_LLM_MODEL=qwen2.5:7b .venv/bin/pdas serve
```

## Commands

```bash
pdas ingest <paths...>    # parse, chunk, embed, index. -c to force a collection
pdas reindex              # rebuild vectors. required after changing the embedder
pdas adduser <service_no> # create an account
pdas status               # what is indexed, whether the models are reachable
pdas serve                # run the API
```

## How it works

**Ingestion** (`core/ingest.py`) parses PDFs with PyMuPDF, DOCX with
python-docx, XLSX with openpyxl and DXF drawings with ezdxf, then chunks on
document structure — never across a heading, since a passage straddling two
clauses cites neither correctly. Page numbers survive into the citation.

**Retrieval** (`core/retrieval.py`) is hybrid. Dense search over FAISS finds
passages that mean the same thing in different words; BM25 finds `A-60`,
`NES-109` and `SDO/NA/STAB-014`, the exact tokens a design office actually
searches for and which embeddings routinely miss. Reciprocal Rank Fusion
combines them without needing the two score scales to be comparable.

**Generation** (`core/prompts.py`) is grounded and instructed to decline rather
than answer from general knowledge. That behaviour is the point of the system,
so it is measured, not assumed:

```bash
.venv/bin/python evals/run.py         # --verbose to see every answer
```

Three sets — answerable, absent, adversarial. **The gates are `absent` and
`adversarial`**: a model that answers questions the corpus does not cover, or
agrees with a wrong figure put to it confidently, is not shippable however well
it scores on the rest. Re-run after every model change and every prompt edit.

## Notes

**Reasoning models return empty answers if the budget is too small.** They emit
deliberation to `message.thinking` before writing any `content`, and
`think: false` is honoured by some model and Ollama combinations and silently
ignored by others. Measured on `qwen3-vl:4b`, a trivial prompt burned 831
characters of reasoning and returned nothing at a 200-token cap. `PDAS_MAX_TOKENS`
defaults to 2560 for this reason; the API reports the case explicitly rather
than showing an empty reply.

**DWG cannot be ingested.** No open library parses it — convert to DXF or plot
to PDF first.

**No OCR.** Scanned PDFs with no text layer produce no chunks and are reported
as failed.

## Layout

```
electron/          main process, preload bridge
src/               React renderer — screens/, views/, components/, lib/
assets/            icon sources and generated PNG/icns/ico
backend/pdas/      FastAPI app, core/ retrieval and ingestion, cli.py
backend/evals/     refusal eval
deploy/            offline bundle scripts, systemd units
```
