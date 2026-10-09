# Deploying Codebase Q&A

Two supported routes:

| Route | What runs | HTTPS | Persistence | Cost |
|---|---|---|---|---|
| A. Hugging Face Docker Space | One container: FastAPI on `127.0.0.1:8000` + Streamlit on `7860` (`deploy/start.sh`) | Provided by Hugging Face | Ephemeral unless you add persistent storage | Free CPU tier works |
| B. Linux VM with Docker Compose | `backend`, `frontend`, `caddy` containers | Automatic (Caddy + Let's Encrypt) | Named volume `app-data` | Your VM |

In both routes the browser only talks to Streamlit. Streamlit calls the backend over HTTP inside the container
or the compose network, and the backend is never exposed publicly.

## Configuration

| Name | Kind | Required | Default | Purpose |
|---|---|---|---|---|
| `GEMINI_API_KEY` | secret | yes | - | Google AI Studio key used for answer generation |
| `GEMINI_MODEL` | variable | no | `gemini-3.5-flash-lite` | Gemini model name |
| `DEMO_PASSWORD` | secret | recommended for public demos | empty (no password) | Required in the UI before anything can be indexed or asked |
| `DEMO_REPO_URL` | variable | no | empty | Repository indexed automatically at startup if it is not indexed yet |
| `MAX_REPOS` | variable | no | `5` | Maximum number of indexed repositories |
| `MAX_REPO_SIZE_MB` | variable | no | `200` | Repositories larger than this are rejected (GitHub API size and on-disk check) |
| `ASK_RATE_LIMIT_PER_MINUTE` | variable | no | `10` | Per-visitor limit on questions |
| `INDEX_RATE_LIMIT_PER_HOUR` | variable | no | `10` | Per-visitor limit on index requests |
| `GITHUB_TOKEN` | secret | no | empty | Raises the GitHub API rate limit for the repo size check (no scopes needed) |
| `DATA_DIR` | variable | no | `/app/data` in the image | Where clones, Chroma, BM25 and the registry live |
| `DOMAIN` | variable | route B only | - | Public hostname for Caddy, e.g. `qa.example.com` |

Never commit `.env`; it is gitignored and excluded from the Docker build context.

## Route A: Hugging Face Docker Space

1. Create a Hugging Face account and a **write** access token: <https://huggingface.co/settings/tokens>
   (New token, type "Write").
2. Create the Space: <https://huggingface.co/new-space>
   - Owner: your account. Space name: for example `codebase-qa`.
   - SDK: **Docker**, template **Blank**.
   - Hardware: **CPU basic (free)** is enough. Visibility: Public or Private.
3. In the Space, open **Settings -> Variables and secrets** and add:
   - Secret `GEMINI_API_KEY` = your Gemini key.
   - Secret `DEMO_PASSWORD` = a password you will share with reviewers (recommended).
   - Variable `GEMINI_MODEL` = `gemini-3.5-flash-lite`.
   - Variable `DEMO_REPO_URL` = `https://github.com/fastapi/full-stack-fastapi-template`.
4. Push this repository to the Space (from the project root):
   ```bash
   git remote add space https://huggingface.co/spaces/<your-username>/codebase-qa
   git push space main
   ```
   When asked for credentials use your Hugging Face username and the write token as the password.
   If the Space was created with an initial commit, use `git push --force space main` the first time.
5. Watch **Logs -> Build**. The build installs CPU PyTorch and downloads both models into the image
   (expect 10-20 minutes). The README front matter (`sdk: docker`, `app_port: 7860`) tells Spaces which port to serve.
6. When the Space is **Running**, the demo repository is indexed in the background (about 3-5 minutes on the free CPU).
   The sidebar shows the job progress; you can ask questions once the repository appears in the picker.

Notes
- Free Spaces have ephemeral disk: after a restart the demo repo is indexed again automatically. To keep indexes,
  enable persistent storage in the Space settings and set the variable `DATA_DIR=/data`.
- Free Spaces sleep after inactivity; the first request after sleeping takes a minute to start the container.
- If the build fails, the build log names the failing Dockerfile step. If the app fails at runtime, `start.sh` stops the
  container when either process exits, so the Space shows "Runtime error" with the cause in **Logs -> Container**.

## Route B: Linux VM with Docker Compose

Prerequisites: a Linux VM (2 vCPU / 4 GB RAM minimum, 8 GB recommended), a DNS `A` record pointing your domain at
the VM's public IP, and inbound ports 80 and 443 open.

1. Install Docker Engine and the compose plugin: <https://docs.docker.com/engine/install/>
2. Clone the repository on the VM:
   ```bash
   git clone https://github.com/<you>/codebase-qa.git
   ```
   ```bash
   cd codebase-qa
   ```
3. Create `.env` next to `docker-compose.yml`:
   ```
   DOMAIN=qa.example.com
   GEMINI_API_KEY=...
   GEMINI_MODEL=gemini-3.5-flash-lite
   DEMO_PASSWORD=...
   DEMO_REPO_URL=https://github.com/fastapi/full-stack-fastapi-template
   ```
4. Build and start:
   ```bash
   docker compose up -d --build
   ```
5. Check status and logs (backend logs are JSON lines):
   ```bash
   docker compose ps
   ```
   ```bash
   docker compose logs -f backend
   ```
   Caddy obtains a Let's Encrypt certificate on the first request to `https://$DOMAIN`.
6. Update to a new version:
   ```bash
   git pull && docker compose up -d --build
   ```

What the stack does
- `backend`: FastAPI, data in the named volume `app-data`, health check on `/health`, `restart: unless-stopped`.
- `frontend`: Streamlit, waits for a healthy backend, health check on `/_stcore/health`.
- `caddy`: terminates TLS for `$DOMAIN` and proxies to the frontend (WebSockets included); certificates persist in
  `caddy-data`.
- Back up the index with `docker run --rm -v codebase-qa_app-data:/data -v "$PWD":/backup alpine tar czf /backup/app-data.tgz -C /data .`

## GitHub Actions

- `.github/workflows/ci.yml` runs on every push and pull request: `ruff check`, the full pytest suite (no network
  model calls, no API key needed) and a Docker image build.
- `.github/workflows/eval.yml` is manual (**Actions -> Eval subset -> Run workflow**). It indexes the test repository,
  evaluates the first 10 dev questions (never the held-out ones) and writes the metrics table to the job summary.
  For answer-level metrics add the repository secret `GEMINI_API_KEY` (**Settings -> Secrets and variables -> Actions**)
  and optionally the variable `GEMINI_MODEL`. Untick "answers" to run retrieval-only without a key.

## Security model

- Only `https://github.com/<owner>/<repo>` URLs are accepted; repositories are shallow-cloned with a timeout,
  without tags, hooks, symlinks, LFS smudging or the `ext` transport, and are never executed.
- Size limit checked before cloning (GitHub API) and after cloning (on disk); the number of repositories is capped.
- Indexing runs as a single-worker background job (`GET /jobs/{id}` for progress).
- Per-visitor rate limits on `/ask` and `POST /repos`. The visitor IP is the last `X-Forwarded-For` hop added by the
  trusted proxy (Hugging Face or Caddy), forwarded by Streamlit to the private backend.
- Optional demo password on every endpoint except `/health`; errors never include stack traces or server paths.
