# PDAS — offline deployment

Target: **Ubuntu under WSL2** on a Windows jump server, RTX 4060 8GB, no
internet. Clients run the Electron app on their own PCs over the LAN.

Nothing here reaches the network at install time. If a step tries to, it fails
loudly rather than hanging.

---

## 0. Where the models actually run

The GPU is in the Windows box. There are three ways to reach it, and the choice
decides everything else.

### Recommended — everything inside WSL2

Ollama runs as a Linux binary in the VM and reaches the RTX 4060 through the
**Windows** NVIDIA driver. No driver is installed inside the VM, and no GPU
passthrough is configured; WSL2 exposes the card at `/dev/dxg` and Ollama's
CUDA build uses it directly.

- Requires Windows 11 (or Windows 10 21H2+), WSL2, and a current NVIDIA driver
  **on the Windows side**. Installing a driver inside Ubuntu breaks it.
- `systemd` manages both services properly — set `systemd=true` in
  `/etc/wsl.conf` if it isn't already.
- Everything in this document applies unchanged.

Verify before trusting it:

```bash
nvidia-smi                      # must list the 4060 from inside WSL2
ollama run qwen3.5:4b "hi"      # then check nvidia-smi shows the process
```

If `nvidia-smi` works but Ollama still runs on CPU, the CUDA runtime is missing
from the VM — `ollama serve` logs say which library it could not load.

### Alternative — Ollama native on Windows, backend in WSL2

Install `OllamaSetup.exe` on Windows; it uses the GPU with no WSL layer at all.
The backend then reaches it across the WSL boundary:

```powershell
setx OLLAMA_HOST "0.0.0.0:11434"     # default 127.0.0.1 is unreachable from WSL2
```

```bash
# In WSL2, point the backend at the Windows host
PDAS_OLLAMA_HOST=http://$(ip route show default | awk '{print $3}'):11434
```

Fewer moving parts for GPU access, but Ollama on Windows runs as a **desktop
app, not a service** — it needs a logged-in user, or NSSM / a scheduled task to
run headless on a server. That is usually the deciding factor against it.

### Simplest overall — everything native on Windows, no VM

Ollama for Windows plus Python for Windows. The NAT problem disappears
entirely, so no mirrored networking and no port proxy. Costs you `systemd` (use
NSSM for both services) and needs `win_amd64` wheels instead of manylinux —
`fetch_wheels.sh` must then run on Windows.

Worth considering if the Ubuntu VM exists only to host this application.

---

## 0b. What you build, and where

| Stage | Machine | Produces |
|---|---|---|
| Wheels | Connected Ubuntu, **same release + Python minor as the server** | `offline/wheels/` |
| Models | Any connected Linux | `offline/ollama/` |
| Client installer | Any connected machine | `dist/PDAS-Setup-*.exe` |
| Bundle | Same as wheels | `pdas-runtime-<date>.tar` + `pdas-app-<date>.tar.gz` |

The wheel machine matters more than any other choice here. Wheel filenames
encode the OS, architecture, and Python minor version; a mismatch fails on the
server with "no matching distribution found", which reads like a network fault
and sends people looking in the wrong place. **Run `fetch_wheels.sh` inside the
same WSL2 Ubuntu image you will deploy to, while it still has network.**

---

## 1. Build the bundle (connected machine)

```bash
git clone <repo> pdas && cd pdas

./deploy/fetch_wheels.sh          # ~80 MB, aborts if any sdist appears
./deploy/fetch_models.sh          # ~4 GB: runtime + qwen3.5:4b + bge-m3

npm install                       # client installer, optional
npm run dist -- --win
cp dist/PDAS-Setup-*.exe offline/client/

./deploy/make_bundle.sh           # -> two archives, see below
```

`make_bundle.sh` produces **two** archives, not one:

| Archive | Size | Transfer when |
|---|---|---|
| `pdas-runtime-<date>.tar` | ~5 GB | model or dependency versions change |
| `pdas-app-<date>.tar.gz` | ~1 MB | every code change |

Over removable media that split is the whole point: once the runtime is on the
box, shipping a fix costs a megabyte rather than five gigabytes.

```bash
./deploy/make_bundle.sh --app-only    # code changed, dependencies did not
```

`fetch_wheels.sh` fails deliberately if pip downloads a source distribution.
An sdist would try to compile on the offline box, where there is no compiler
and no way to fetch build dependencies. If it trips, pin a version of that
package which publishes a wheel.

---

## 2. Transfer

Move the single `.tar.gz` through your approved channel to the Windows jump
server, then into the VM:

```bash
# Inside WSL2 — first install, both archives into the SAME directory
cp /mnt/c/Users/<you>/Downloads/pdas-*-*.tar* ~/
mkdir -p ~/pdas-bundle && cd ~/pdas-bundle
tar -xf  ~/pdas-runtime-*.tar
tar -xzf ~/pdas-app-*.tar.gz
sha256sum -c RUNTIME_SHA256SUMS   # do not skip either of these
sha256sum -c APP_SHA256SUMS
```

**Keep that directory.** A later app-only update unpacks on top of it, and the
installer refuses to run without the `wheels/` and `ollama/` directories the
runtime archive put there — see *Updating* below.

**Unpack into WSL2's own filesystem, not `/mnt/c/`.** Model files are
memory-mapped, and mmap across the 9p bridge to the Windows filesystem is
drastically slower — enough to make the assistant feel broken. `/opt/pdas` is
inside ext4; `/mnt/c/anything` is not.

Multi-gigabyte transfers over removable media do corrupt files, occasionally
and silently. The checksum step is how you find out now rather than during a
confusing debug session next week.

---

## 3. Install

```bash
sudo ./install_offline.sh
```

This creates a `pdas` service account, builds a virtualenv from the bundled
wheels with `--no-index`, installs the Ollama runtime and model store, writes
`/opt/pdas/pdas.env` with a generated JWT secret, and starts both services.

Then:

```bash
# An account to sign in with
sudo -u pdas /opt/pdas/venv/bin/pdas adduser PN-40218 --name "Lt Cdr Abbasi" --role admin

# Ingest documents
sudo -u pdas /opt/pdas/venv/bin/pdas ingest /srv/documents

# Confirm
sudo -u pdas /opt/pdas/venv/bin/pdas status
curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool
```

### Confirm the GPU is actually being used

```bash
nvidia-smi          # the ollama process should hold ~3 GB
```

If the GPU is missing, Ollama silently falls back to CPU and answers arrive at
2–4 tokens/sec instead of 40+. Under WSL2 the fix is a current NVIDIA driver on
the **Windows** side — do not install a driver inside the VM.

---

## 4. Make it reachable from client PCs

WSL2 sits behind NAT. Until this step, only the VM itself can connect,
regardless of `PDAS_HOST=0.0.0.0`.

**Preferred — mirrored networking.** In `%UserProfile%\.wslconfig` on Windows:

```ini
[wsl2]
networkingMode=mirrored
memory=12GB
```

Then `wsl --shutdown` and restart. WSL now shares the host's IP directly, and
`http://<windows-host-ip>:8000` works from any LAN machine.

**Fallback — port proxy**, for Windows builds without mirrored mode:

```powershell
$wsl = (wsl hostname -I).Trim().Split()[0]
netsh interface portproxy add v4tov4 listenport=8000 listenaddress=0.0.0.0 `
      connectport=8000 connectaddress=$wsl
New-NetFirewallRule -DisplayName "PDAS 8000" -Direction Inbound `
      -LocalPort 8000 -Protocol TCP -Action Allow
```

The WSL IP changes on every restart, so run this at boot via Task Scheduler or
the proxy silently points at nothing after the next reboot.

---

## 5. Client PCs

Install `PDAS-Setup-*.exe`, launch, and on the sign-in screen use **Change**
next to the server line to set `http://<server>:8000`. It is stored per machine
and persists.

---

## Updating an installed server

Code changes ship as the app archive alone. Unpack it **into the directory the
first install used** — `install_offline.sh` checks for `app/` *and* `wheels/`
before it does anything, and an app-only archive carries only the first, so
unpacking somewhere fresh fails immediately with `Missing .../wheels`.

```bash
cd ~/pdas-bundle                  # where the runtime archive was unpacked
tar -xzf ~/pdas-app-<date>.tar.gz
sha256sum -c APP_SHA256SUMS
sudo ./install_offline.sh
sudo systemctl restart pdas
pdas status
```

Re-running the installer is safe. It overwrites `app/`, rebuilds the virtualenv
from the wheels already present, and does not touch `var/` — the database,
the FAISS index and every stored document survive. It also leaves `pdas.env`
alone, so the JWT secret is unchanged and nobody is signed out by the upgrade
itself.

### When a dependency was added

`--app-only` deliberately ships no wheels, on the assumption that dependencies
did not change. When one *did*, put its wheel into the bundle's `wheels/`
directory before installing — the installer copies from there into
`/opt/pdas/wheels`:

```bash
cp python_multipart-*.whl ~/pdas-bundle/wheels/
```

Skip it and `pip install --no-index` fails with *no matching distribution
found*, which reads like a corrupt bundle rather than one absent file.

A pure-Python wheel — `py3-none-any` in the filename — can be fetched on any
machine, including the one you are reading this on. Anything tagged `cp312` or
`manylinux` is built for a specific Python and platform and must come from
`fetch_wheels.sh` run on an image matching the server.

### New settings

`pdas.env` is written **only if absent**, so a setting added since the last
release will not appear on an upgraded box — it silently keeps the compiled-in
default. Check `backend/pdas/config.py` against `/opt/pdas/pdas.env` after an
upgrade and add what matters:

```bash
echo 'PDAS_JWT_TTL_MINUTES=480' | sudo tee -a /opt/pdas/pdas.env
```

That one is worth setting deliberately. The default is 15 minutes, chosen for a
shared terminal now that a session survives a page reload; there is no refresh,
so on this box — where the network boundary is the air gap — a working day is
the more sensible figure.

---

## Operating

```bash
systemctl status pdas ollama
journalctl -u pdas -f

sudo -u pdas /opt/pdas/venv/bin/pdas ingest /srv/new-documents
sudo -u pdas /opt/pdas/venv/bin/pdas status
```

**After changing the embedding model, reindex.** Vectors from the old model are
meaningless in the new model's space, and searching across the two returns
confident nonsense rather than an error:

```bash
sudo -u pdas /opt/pdas/venv/bin/pdas reindex
```

The backend refuses to serve an index whose recorded model does not match the
configured one, so this failure surfaces at `/api/health` rather than as
quietly wrong answers.

---

## Changing models

Edit `/opt/pdas/pdas.env`, then:

```bash
sudo -u pdas OLLAMA_MODELS=/opt/pdas/models ollama list   # what is present
sudo systemctl restart pdas
sudo -u pdas /opt/pdas/venv/bin/pdas reindex              # only if the embedder changed
```

To add a model later, pull it on a connected machine and copy **both**
`~/.ollama/models/blobs` and `~/.ollama/models/manifests` into
`/opt/pdas/models`. Copying only `blobs` leaves a server that holds the weights
and has no idea what they are called.

### VRAM budget, 8GB card (~6.5GB usable)

Measured with `ollama ps`, not estimated:

| Model | Context | Resident |
|---|---|---|
| `qwen3.5:4b` | 16384 | **3.7 GB** |
| `bge-m3` | 4096 | **0.7 GB** |
| | | **4.4 GB total** |

Roughly 2GB spare on a 6.5GB budget. Note the on-disk size is 3.4GB and the
resident size 3.7GB — the KV cache at 16k is already included above, so raising
`PDAS_NUM_CTX` eats the margin directly.

A 7B fits if the 4B ever proves too weak — **but re-run the refusal eval before
and after any model change**:

```bash
sudo -u pdas /opt/pdas/venv/bin/python /opt/pdas/app/evals/run.py
```

---

## The failure that matters

A naval architect acting on a stability criterion this system invented is worse
than the system not existing. `evals/refusal.yaml` scores three sets:
answerable, absent, and adversarial. **The gates are `absent` and
`adversarial`** — a model that answers questions the corpus does not cover is
not shippable regardless of how well it does on the rest.

Re-run it after every model change and every edit to `pdas/core/prompts.py`.

---

## Known constraints

- **DWG cannot be ingested.** No open library parses it. Convert to DXF or plot
  to PDF first.
- **No OCR.** Scanned PDFs without a text layer produce no chunks and are
  reported as failed. Adding OCR means shipping Tesseract and its language data
  as a system package, outside the wheel bundle.
- **Data at rest is plaintext.** The SQLite store, the FAISS index and the
  query log sit unencrypted in `/opt/pdas/var`. Whether that needs disk
  encryption is a call for whoever owns the accreditation.
