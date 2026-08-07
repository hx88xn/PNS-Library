# Running PDAS with Docker Compose

Four services: `ollama` (models), `ollama-pull` (one-shot model fetch),
`backend` (FastAPI), `frontend` (nginx serving the built React client and
proxying `/api` to the backend).

| Port | `.env` key | Service | Who uses it |
|---|---|---|---|
| **7069** | `PDAS_FRONTEND_PORT` | frontend | Everyone. |
| **7070** | `PDAS_BACKEND_PORT` | backend | The Electron desktop client, and the browser only when `PDAS_API_URL` points here. |

`11434` is deliberately not published. An open Ollama port is an
unauthenticated endpoint that will run any prompt it is handed.

## First run

```bash
# 1. Settings. .env is gitignored and does not arrive with a `git pull`;
#    .env.example is the copy that does, and it documents every key.
cp .env.example .env

# 2. A signing secret. There is no default: the fallback in config.py is a
#    literal string in a public repository, and anyone holding it can forge a
#    session against a RESTRICTED corpus.
sed -i "s|^PDAS_JWT_SECRET=$|PDAS_JWT_SECRET=$(openssl rand -hex 32)|" .env

# 3. Build and start. On a GPU box add the override — see below.
docker compose up -d --build

# 4. Watch the models download (~4 GB, once; stored in a volume).
docker compose logs -f ollama-pull

# 5. Create an account. This is the only way to issue credentials.
docker compose exec backend pdas adduser PN-40218 --name "Lt Cdr Ahmed" --role admin
```

Then open `http://<server>:7069`, or the frontend hostname below.

## Hostnames

Nothing in this stack terminates TLS. Point a reverse proxy on the host at the
two published ports:

| Hostname | → | Serves |
|---|---|---|
| `pn.srv650330.hstgr.cloud` | `127.0.0.1:7069` | the application |
| `pn-be.srv650330.hstgr.cloud` | `127.0.0.1:7070` | the API |

`PDAS_API_URL` in `.env` decides which of those the browser actually calls,
and there are only two configurations that work:

**Same origin — leave `PDAS_API_URL` empty.** Requests go to the page's own
host and nginx proxies `/api` onward. One certificate, no CORS, and the
backend never needs to be reachable from the internet: drop the
`PDAS_BACKEND_PORT` mapping entirely and `pn-be` becomes unnecessary. This is
the configuration with the fewest ways to fail.

**Split hosts — `PDAS_API_URL=https://pn-be.srv650330.hstgr.cloud`.** Then
**`pn-be` must serve HTTPS too.** A browser on an `https:` page refuses to
call `http:`, and it fails silently — the interface reports "Cannot reach the
server" with the real reason visible only in the developer console. Set
`PDAS_CORS_ORIGINS` to the frontend's origin at the same time, or any page on
the internet can drive this API.

`PDAS_API_URL` is compiled into the JavaScript bundle, so changing it needs a
rebuild, not a restart:

```bash
docker compose up -d --build frontend
```

## GPU

The base file runs Ollama on CPU, where a 4B model answers in minutes rather
than seconds. On a host with an NVIDIA card and the
[Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html):

```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi   # verify first
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

Both models resident need ~4.4 GB of VRAM (`qwen3.5:4b` ~3.7 GB at a 16k
context, `bge-m3` ~0.7 GB). `README-DEPLOY.md` has the full table.

## Loading documents

Through the interface, or from the server for a bulk first load:

```bash
docker compose cp ./manuals backend:/tmp/manuals
docker compose exec backend pdas ingest /tmp/manuals
docker compose exec backend pdas status      # what is indexed, and are the models present
```

## State

Everything that matters is in the `pdas-data` volume: the SQLite database
(password hashes included), the FAISS index, and a copy of every ingested
document. **Back it up.** Losing it means re-ingesting the corpus.

```bash
docker run --rm -v pdas_pdas-data:/data -v "$PWD":/out alpine \
  tar czf /out/pdas-data-$(date +%Y%m%d).tar.gz -C /data .
```

`ollama-models` holds the downloaded weights and is re-fetchable, so it does
not need backing up — unless the box is air-gapped, in which case it does.

## Health

`http://<server>:7069/api/health` needs no authentication and names what is
wrong in words: an unreachable Ollama, a model that was never pulled, an index
that needs rebuilding.

## Notes

- **The `ollama-pull` container exits, and that is correct.** It is a one-shot.
  `docker compose ps -a` shows it as `Exited (0)`.
- **No route to ollama.com?** `ollama-pull` fails and the rest of the stack
  still starts — the backend does not wait on it. Load the weights into the
  `ollama-models` volume by hand (`deploy/fetch_models.sh` produces them) and
  restart.
- **TLS.** Nothing here terminates HTTPS. Put a reverse proxy in front of 7069
  if the network is not trusted; because the client is same-origin, no rebuild
  is needed to move it behind one.
- **Sessions do not survive a page reload.** The token is held in memory on
  purpose (`src/lib/api.js`) — on a shared terminal a session should not
  outlive the window.
