# PDAS — offline server deployment runbook

Follow in order. Each step has a check; do not proceed past a failed one.

Background and rationale are in [README-DEPLOY.md](README-DEPLOY.md). This file
is the checklist to work through standing at the machine.

---

## What you carry in

| File | Size | From |
|---|---|---|
| `ubuntu-24.04-pdas.tar` | ~2 GB | `wsl --export` on a connected machine |
| `pdas-runtime-<date>.tar.part.aa` … `.af` | 5.6 GB | `make_bundle.sh --split 1G` |
| `pdas-runtime-<date>.tar.parts.sha256` | 726 B | same |
| `pdas-app-<date>.tar.gz` | 44 KB | `make_bundle.sh --app-only` |
| `PDAS-Setup-1.0.0.exe` | 79 MB | GitHub Actions, or `npm run dist -- --win` |
| `wsl.2.x.x.x64.msi` | ~120 MB | Only if WSL is not already installed |

Everything else — Python, Ollama, the models, every dependency — is inside
these. Nothing is downloaded on the server.

---

## 1. Windows prerequisites

```powershell
wsl --version
```

If that errors, install `wsl.2.x.x.x64.msi`, then reboot.

```powershell
systeminfo | findstr /C:"Hyper-V"
```

Virtualization must be enabled in BIOS/UEFI (Intel VT-x or AMD-V). Task Manager
→ Performance → CPU shows "Virtualization: Enabled". Without it WSL fails with
`HCS_E_HYPERV_NOT_INSTALLED`.

**NVIDIA driver goes on Windows, not inside the VM.** Installing one in Ubuntu
breaks GPU access rather than enabling it.

```powershell
nvidia-smi
```

Must list the RTX 4060.

---

## 2. Import the Linux environment

```powershell
mkdir C:\WSL -Force
wsl --import PDAS C:\WSL\PDAS <path>\ubuntu-24.04-pdas.tar
wsl -d PDAS
```

**Check** — inside the VM:

```bash
lsb_release -ds          # Ubuntu 24.04
python3.12 --version     # Python 3.12.x
which zstd               # /usr/bin/zstd
systemctl is-system-running   # running or degraded, NOT "Failed to connect"
nvidia-smi               # the 4060, seen from inside WSL
```

`nvidia-smi` failing here means the GPU is unreachable and Ollama will run on
CPU at ~3–8 tok/s. Fix the Windows driver before continuing.

If `systemctl` fails, add to `/etc/wsl.conf`:

```ini
[boot]
systemd=true
```

then `wsl --shutdown` from PowerShell and reopen.

---

## 3. Copy the bundle into the VM

```bash
mkdir -p ~/pdas
cp /mnt/c/<transfer-path>/pdas-* ~/pdas/
cd ~/pdas && ls
```

**Into the Linux filesystem, not `/mnt/c`.** Model files are memory-mapped, and
mmap across the Windows bridge is slow enough to look like a broken install.

Needs ~18 GB free: parts, the reassembled tar, and the extracted contents.

---

## 4. Verify, reassemble, extract

```bash
sha256sum -c pdas-runtime-*.tar.parts.sha256
```

Every part must say `OK`. A mismatch means a corrupt transfer — re-copy that
part, do not continue.

```bash
cat pdas-runtime-*.tar.part.* > runtime.tar
tar -xf runtime.tar
tar -xzf pdas-app-*.tar.gz
sha256sum -c RUNTIME_SHA256SUMS
sha256sum -c APP_SHA256SUMS
```

`ls` should now show `app`, `wheels`, `ollama`, `client`, `install_offline.sh`
and both `.service` files.

---

## 5. Install

```bash
sudo ./install_offline.sh
```

Three to five minutes; copying 4.3 GB of model blobs is most of it. The script
verifies checksums again, installs any vendored `.deb`s, builds the venv from
local wheels with `--no-index`, installs the Ollama runtime and model store,
generates a JWT secret, and enables both services.

**Check:**

```bash
systemctl status pdas ollama --no-pager
curl -s http://127.0.0.1:8000/api/health
```

`"status":"degraded"` with only `No documents ingested` is correct at this
point.

---

## 6. Confirm the GPU is actually in use

```bash
sudo -u pdas nvidia-smi
journalctl -u ollama | grep -i "inference compute"
```

Want `library=cuda` and a non-zero `total_vram`. If it says `library=cpu` and
`total_vram="0 B"`, Ollama is on CPU — answers will take minutes instead of
seconds, with no error to tell you why.

If plain `nvidia-smi` works but `sudo -u pdas nvidia-smi` does not, the service
account cannot reach the device. Fix:

```bash
sudo usermod -aG video,render pdas
sudo systemctl restart ollama
```

---

## 7. Create an account and ingest

```bash
sudo -u pdas pdas adduser PN-00000 --name "Full Name" --role admin
```

Copy the documents somewhere the service account can read:

```bash
sudo mkdir -p /opt/pdas/documents
sudo cp -r /mnt/c/<docs-path>/* /opt/pdas/documents/
sudo chown -R pdas:pdas /opt/pdas/documents
sudo -u pdas pdas ingest /opt/pdas/documents
```

**Read the output.** It reports per-document failures rather than aborting.
Scanned PDFs with no text layer and `.dwg` files will fail — convert those to
DXF or plot to PDF first.

```bash
sudo -u pdas pdas status
curl -s http://127.0.0.1:8000/api/health
```

Now expect `"status":"ok"`.

---

## 8. Score the model before anyone uses it

```bash
sudo -u pdas /opt/pdas/venv/bin/python /opt/pdas/app/evals/run.py
```

The gates are `absent` and `adversarial`. **A model that answers questions the
corpus does not cover, or agrees with a wrong figure put to it confidently, is
not fit for use here** however well it scores on the rest.

The eval ships with synthetic questions. Once real documents are indexed,
rewrite `evals/refusal.yaml` against them — an eval on documents you are not
serving proves nothing.

---

## 9. Make the server reachable from client PCs

WSL2 is NAT'd. Until this step only the VM itself can connect, whatever
`PDAS_HOST` says.

`%UserProfile%\.wslconfig` on Windows:

```ini
[wsl2]
networkingMode=mirrored
memory=12GB
```

```powershell
wsl --shutdown
```

Reopen, then from another machine on the LAN:

```
curl http://<server-ip>:8000/api/health
```

**Fallback** for Windows builds without mirrored mode:

```powershell
$wsl = (wsl -d PDAS hostname -I).Trim().Split()[0]
netsh interface portproxy add v4tov4 listenport=8000 listenaddress=0.0.0.0 `
      connectport=8000 connectaddress=$wsl
New-NetFirewallRule -DisplayName "PDAS 8000" -Direction Inbound `
      -LocalPort 8000 -Protocol TCP -Action Allow
```

The WSL IP changes on every restart, so run this at boot via Task Scheduler or
the proxy silently points at nothing after the next reboot.

---

## 10. Client PCs

Install `PDAS-Setup-1.0.0.exe`. It is unsigned, so SmartScreen warns on first
run — **More info → Run anyway**, or code-sign it before distribution.

Launch, and on the sign-in screen use **Change** to set
`http://<server-ip>:8000`. Stored per machine; set once.

Sign in with the account from step 7.

---

## Operating

```bash
systemctl status pdas ollama
journalctl -u pdas -f

sudo -u pdas pdas ingest /opt/pdas/documents   # add more
sudo -u pdas pdas status
```

**After changing the embedding model, reindex** — vectors from the old model
are meaningless in the new model's space:

```bash
sudo -u pdas pdas reindex
```

The backend refuses to serve an index whose recorded model does not match the
configured one, so this surfaces at `/api/health` rather than as quietly wrong
answers.

### Updating the application

Code changes need only the 44 KB app archive:

```bash
# on the build machine
./deploy/make_bundle.sh --app-only

# on the server, in the same directory as the first install
tar -xzf pdas-app-<date>.tar.gz
sudo ./install_offline.sh
```

The 5.6 GB runtime only moves again if models, dependencies or vendored
packages change.

---

## If it goes wrong

| Symptom | Cause |
|---|---|
| `No matching distribution found for numpy` | Python version ≠ wheel tag. Check `python3 --version` against the `cp3XX` in the wheel filenames. |
| `PermissionError: 'var'` running the CLI | Use `pdas`, not `/opt/pdas/venv/bin/pdas` — the wrapper loads `pdas.env`. |
| Service crash-loops on an import | A library probing `$HOME` under the sandbox. `journalctl -u pdas -n 30`. |
| `address already in use` | Something else on 8000. Change `PDAS_PORT` in `/opt/pdas/pdas.env`. |
| Answers take minutes | Ollama on CPU. See step 6. |
| Client cannot connect | Step 9 not done, or the WSL IP changed. |
| `sha256sum: could not be read` | Wrong directory, or the manifest holds build-machine paths. |

---

## Known constraints

- **DWG cannot be ingested.** Convert to DXF or plot to PDF.
- **No OCR.** Scanned PDFs without a text layer produce no chunks.
- **Data at rest is plaintext.** The SQLite store, FAISS index and query log
  sit unencrypted in `/opt/pdas/var`. Whether that needs disk encryption is a
  decision for whoever owns the accreditation.
- **The eval is the gate, not a formality.** Re-run it after every model or
  prompt change.
