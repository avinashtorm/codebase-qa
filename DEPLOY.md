# Deploying Codebase Q&A on an Azure VM

This guide puts the app on a small Ubuntu virtual machine in Azure, paid for by the Azure for Students credit.
At the end you will have `https://<your-name>.<region>.cloudapp.azure.com` with a real HTTPS certificate.

You do not need Docker on your own computer. Everything Docker-related runs on the VM. From Windows you only use
the Azure portal in a browser, PowerShell (for `ssh`, `scp` and `git`) and this project folder.

```
Browser --HTTPS--> Caddy (ports 80/443) --> Streamlit frontend (7860) --> FastAPI backend (8000)
                   [all three run as Docker containers on the VM, defined in docker-compose.yml]
```

Only Caddy is reachable from the internet. Caddy gets and renews the HTTPS certificate from Let's Encrypt automatically.

## What it costs

This deployment runs in **India South Central** (`indiasouthcentral`): Azure for Students only allowed certain regions,
and the VM could not be created in Central India.

**The VM price below is an estimate.** For India South Central the portal's Size list shows "Unavailable" instead of a
price, and Azure's public price list has no B2als v2 entry for the region yet. The estimate uses the Central India price
as the likely value and the East US price as a pessimistic upper bound. Disk and public IP prices are the published
India South Central prices (Azure retail prices API, October 2026). **Check the real cost after a day** in
**Cost Management -> Cost analysis** (step 6 shows where).

| Item | Choice | Price | Per month if always on |
|---|---|---|---|
| VM | **B2als v2** (2 vCPU, 4 GB RAM, x86, AMD) | estimate $0.0246 / hour (Central India), at most ~$0.0376 (East US) | about $18 (up to about $27.45) |
| OS disk | 30 GiB Standard SSD (E4) | | about $2.64 |
| Public IP | Standard, static | $0.005 / hour | about $3.65 |
| Traffic | Outbound data | first 100 GB free | $0 for a demo |

- **This deployment runs 24/7 (no auto-shutdown)**, so a reviewer can open the link at any time. Total: about
  **$24.25 per month** at the likely VM price ($18 VM + $2.64 disk + $3.65 IP), at most about **$33.75 per month**.
  The $100 credit therefore lasts about **4 months** (at least about 3 months).
- Turning on auto-shutdown at night (step 5) would cut this to about $15-20 per month, but the site would be offline
  until someone starts the VM again.
- Other x86 sizes with 4 GB in Central India cost more: B2s and B2ls v2 $0.0448/h (~$32.70/month),
  D2als v6 $0.0520/h (~$37.96/month). In East US, B2als v2 is $0.0376/h (~$27.45/month).
- A stopped (deallocated) VM costs nothing for compute, but the disk and the public IP are still billed (about $6 per month).
- Deleting the resource group (step 14) stops all charges.
- Azure for Students has a spending limit. When the credit runs out, your resources are switched off. You are not charged
  and no card is needed.

Why 4 GB of RAM: the backend loads PyTorch and the embedding model, and building the Docker image needs memory too.
Sizes with 1-2 GB (B1s, B1ms, B2ats v2) run out of memory. The steps below also add a 2 GB swap file as a safety net.

---

## Step 1: Pick a region and check your credit

1. Open <https://portal.azure.com> and sign in with your student account.
2. Check your remaining credit: search the portal for **Education**, open the **Education** hub and look at the
   credit shown on its **Overview** page. (The older Sponsorships balance page shows "no active sponsorship" for
   Azure for Students, which is expected.)
3. Choose a region close to you. Student subscriptions only allow certain regions. If the portal says a size or region
   is "not available" or blocked by policy, pick another region from its list. (This deployment ended up in
   **India South Central**.)

## Step 2: Create the virtual machine

1. In the portal search bar type **Virtual machines** and open it, then click **Create -> Azure virtual machine**.
2. **Basics** tab:
   - **Subscription:** Azure for Students.
   - **Resource group:** click **Create new** and enter `codebase-qa-rg`. Everything for this project goes in it,
     so you can delete it all at once later.
   - **Virtual machine name:** `codebase-qa-vm`.
   - **Region:** the region from step 1 (here: India South Central).
   - **Availability options:** No infrastructure redundancy required.
   - **Security type:** Standard.
   - **Image:** **Ubuntu Server 24.04 LTS - x64 Gen2**.
   - **VM architecture:** x64.
   - **Size:** click **See all sizes**, search `B2als_v2`, select it. If it is not offered in your region, choose `B2s`.
     The price per month is shown next to the size.
   - **Authentication type:** SSH public key.
   - **Username:** `azureuser`.
   - **SSH public key source:** Generate new key pair. **Key pair name:** `codebase-qa-key`.
   - **Public inbound ports:** Allow selected ports, and tick **SSH (22)**, **HTTP (80)** and **HTTPS (443)**.
3. **Disks** tab:
   - **OS disk size:** Image default (30 GiB).
   - **OS disk type:** Standard SSD (locally-redundant storage).
   - Tick **Delete with VM**.
4. **Networking** tab: keep the defaults (new virtual network, new public IP).
   Tick **Delete public IP and NIC when VM is deleted**.
5. **Management** tab: leave **Auto-shutdown** off (this deployment runs 24/7; see step 5).
6. Click **Review + create**, wait for "Validation passed", then **Create**.
7. A window asks you to **Download private key and create resource**. Click it and keep the downloaded
   `codebase-qa-key.pem` file. It is your only way to log in: never share it or put it in git.
8. Wait for "Your deployment is complete" (1-2 minutes), then click **Go to resource**.

## Step 3: Check that ports 80 and 443 are open

Caddy needs port 80 to prove to Let's Encrypt that it controls your domain, and port 443 to serve HTTPS.

1. In the VM, open **Networking -> Network settings**.
2. Under **Inbound port rules** you should see rules allowing **22**, **80** and **443**.
3. If 80 or 443 is missing, click **Create port rule -> Inbound port rule**:
   - Service: **HTTP** (then repeat with **HTTPS**), Action: Allow, then click **Add**.
4. Optional but recommended: open the rule for port **22**, change **Source** to **My IP address** and save. Only your
   current internet connection can then try to log in over SSH. If your home IP changes later, update this rule.

## Step 4: Give the VM a free domain name

1. In the VM **Overview**, click the **Public IP address** value. This opens the public IP resource.
2. Go to **Settings -> Configuration**.
3. Check that **Assignment** is **Static**.
4. In **DNS name label** enter a unique lowercase name, for example `codebase-qa-avinash`, and click **Save**.
5. Your domain is now shown under the label, for example `codebase-qa-avinash.indiasouthcentral.cloudapp.azure.com`.
   Write it down; this guide calls it `YOUR_DOMAIN`.
6. Check it from PowerShell on Windows (it should print the VM's public IP):
   ```powershell
   Resolve-DnsName YOUR_DOMAIN
   ```

## Step 5: Auto-shutdown (skipped for this deployment)

This deployment keeps the VM **always on** so the demo link works whenever a reviewer opens it. The budget alerts in
step 6 are the safety net instead. Leave **Operations -> Auto-shutdown** set to Off.

If you later want to save credit (about $15-20 per month instead of about $24-34):
1. In the VM, open **Operations -> Auto-shutdown**.
2. Set **Enabled** to On, choose a **Scheduled shutdown** time and your **Time zone**, optionally add a notification
   email, and click **Save**.
3. To use the app after a shutdown, click **Start** in the VM **Overview**. Docker and `restart: unless-stopped` bring
   the containers back automatically within about a minute. Auto-shutdown never starts the VM again by itself.

## Step 6: Set a budget alert

The goal is an email when you have used **50%** and **80%** of the $100 credit in total. Prices in this guide are in
USD, but **Cost Management shows costs in your billing currency** (INR for this deployment); roughly $1 = ₹95 at the
credit's conversion (₹9,500 = $100), so the always-on estimate of $24-34 per month is about ₹2,300-3,200 per month. A monthly
budget would reset every month and never reach those amounts at about $24-34 per month, so the budget below covers
the whole year of the credit.

1. Search the portal for **Budgets** (or open **Cost Management + Billing -> Cost Management -> Budgets**).
2. Check the **Scope** shown at the top: it must be your **Azure for Students** subscription. Click **Change scope** if not.
3. Click **+ Add**.
4. **Create a budget** page:
   - **Name:** `codebase-qa-credit`
   - **Reset period:** **Annually**
   - **Creation date / Start date:** leave the default (the first day of the current month)
   - **Expiration date:** leave the default or set it about one year ahead
   - **Amount:** your credit in your **billing currency**. Budgets use the subscription's billing currency, not USD.
     This deployment's subscription is billed in **INR**, so the amount is **₹9,500** (the $100 credit in rupees). If yours
     is billed in USD, enter `100`.
5. Click **Next**. Under **Alert conditions** add two rows:
   - Type **Actual**, % of budget **50** (here ₹4,750; $50 for a USD subscription)
   - Type **Actual**, % of budget **80** (here ₹7,600; $80 for a USD subscription)
6. Under **Alert recipients (email)** enter your email address, choose your **Language**, and click **Create**.
7. The budget appears in the list with its amount and current spend. Alert emails come from
   `azure-noreply@microsoft.com`; add it to your contacts so they don't go to spam.

Budget alerts only send emails; they never stop the VM. Azure for Students itself switches resources off when the
credit runs out, without charging you.

If the portal says budgets are not supported for your subscription type, keep an eye on the remaining credit in the
**Education** hub instead.

**Check the real cost after about a day** (cost data arrives with a delay of up to 24 hours):
1. Open **Cost Management + Billing -> Cost Management -> Cost analysis**.
2. Set **Scope** to the resource group `codebase-qa-rg`.
3. Choose the **Cost by resource** view and a date range of the last 7 days.
4. The `codebase-qa-vm` row is the real VM cost. Multiply its daily cost by 30 for a monthly figure and compare it with
   the estimate at the top of this guide.

## Step 7: Connect to the VM over SSH from Windows

Windows 10/11 already include the `ssh` and `scp` commands. Use **PowerShell** (not the old cmd).

1. Create a `.ssh` folder in your user folder and move the key into it:
   ```powershell
   New-Item -ItemType Directory -Force "$HOME\.ssh"
   ```
   ```powershell
   Move-Item "$HOME\Downloads\codebase-qa-key.pem" "$HOME\.ssh\codebase-qa-key.pem"
   ```
2. Restrict the key file to your Windows user. Without this, ssh may refuse it with "UNPROTECTED PRIVATE KEY FILE":
   ```powershell
   icacls "$HOME\.ssh\codebase-qa-key.pem" /inheritance:r /grant:r "$($env:USERNAME):(R)"
   ```
3. Connect (replace `YOUR_DOMAIN`):
   ```powershell
   ssh -i "$HOME\.ssh\codebase-qa-key.pem" azureuser@YOUR_DOMAIN
   ```
   The first time, type `yes` to trust the server. The prompt changes to `azureuser@codebase-qa-vm:~$`;
   you are now typing commands on the VM. Type `exit` to leave.

**Where does each command run?** Code blocks marked `powershell` run on **your Windows PC** in a normal PowerShell
window (prompt like `PS C:\Users\...>`). Code blocks marked `bash` run **on the VM**, inside the SSH session (prompt
`azureuser@codebase-qa-vm:~$`). From step 9 on, keep two windows open: the SSH session and a local PowerShell.
Bash commands typed into Windows PowerShell fail with errors like "The token '&&' is not a valid statement separator".

## Step 8: Prepare the VM and install Docker

1. Update Ubuntu (this takes a few minutes):
   ```bash
   sudo apt-get update && sudo apt-get upgrade -y
   ```
2. Add a 2 GB swap file so the image build cannot run out of memory:
   ```bash
   sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
   ```
   ```bash
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   ```
3. Install Docker Engine and the Compose plugin with Docker's official install script:
   ```bash
   curl -fsSL https://get.docker.com | sudo sh
   ```
4. Allow your user to run Docker without `sudo`:
   ```bash
   sudo usermod -aG docker azureuser
   ```
5. Log out (`exit`) and connect again with the ssh command from step 7, so the group change takes effect.
6. Check that Docker works:
   ```bash
   docker run --rm hello-world
   ```
   ```bash
   docker compose version
   ```
   You should see "Hello from Docker!" and a Compose version (v2.x).

## Step 9: Copy the project to the VM

No GitHub needed: you package the current commit on Windows and upload it.

1. In **PowerShell on Windows**, go to the project folder:
   ```powershell
   cd "$HOME\OneDrive\Desktop\codebase-qa"
   ```
2. Package the committed code. This does not include `.env`, `.venv` or `data`, so your secrets and local
   indexes stay on your PC:
   ```powershell
   git archive --format=tar.gz -o "$HOME\codebase-qa.tar.gz" HEAD
   ```
3. Upload it to the VM's home folder:
   ```powershell
   scp -i "$HOME\.ssh\codebase-qa-key.pem" "$HOME\codebase-qa.tar.gz" azureuser@YOUR_DOMAIN:~/
   ```
4. **On the VM** (in the SSH window with the `azureuser@codebase-qa-vm:~$` prompt, not in PowerShell), unpack it:
   ```bash
   mkdir -p ~/codebase-qa && tar -xzf ~/codebase-qa.tar.gz -C ~/codebase-qa
   ```
   ```bash
   cd ~/codebase-qa && ls
   ```
   You should see `docker-compose.yml`, `Dockerfile`, `backend`, `frontend`, `deploy` and the other project files.

The project is also on GitHub, so you can instead run `git clone https://github.com/avinashtorm/codebase-qa.git ~/codebase-qa` on the VM (see step 13).

## Step 10: Create the .env file on the server

The secrets live only on the VM, in `~/codebase-qa/.env`. They are never in git or in the Docker image.

1. Open the editor:
   ```bash
   nano ~/codebase-qa/.env
   ```
2. Paste this, replacing the values (in nano, right-click pastes):
   ```
   DOMAIN=YOUR_DOMAIN
   GEMINI_API_KEY=your-gemini-api-key
   GEMINI_MODEL=gemini-3.5-flash-lite
   DEMO_PASSWORD=choose-an-owner-password
   DEMO_REPO_URL=https://github.com/fastapi/full-stack-fastapi-template
   ```
3. Save with **Ctrl+O**, then **Enter**, and exit with **Ctrl+X**.
4. Make the file readable only by you:
   ```bash
   chmod 600 ~/codebase-qa/.env
   ```

| Setting | Required | Meaning |
|---|---|---|
| `DOMAIN` | yes | The domain from step 4, without `https://` |
| `GEMINI_API_KEY` | yes | Your Google AI Studio key |
| `GEMINI_MODEL` | no | Defaults to `gemini-3.5-flash-lite` |
| `DEMO_PASSWORD` | recommended | Owner password, needed only to re-index a repository. Visitors add repositories and ask without it |
| `INDEX_PER_VISITOR_PER_DAY` | no | Repositories a visitor (per IP) can add per day (default 5) |
| `ASK_PER_VISITOR_PER_DAY` | no | Questions a visitor (per IP) can ask per day (default 30) |
| `REPO_TTL_HOURS` | no | Visitor repositories are deleted this long after their last use (default 24) |
| `MAX_VISITOR_REPOS` | no | Most visitor repositories kept at once; the oldest is removed first (default 15) |
| `ASK_DAILY_LIMIT` | no | Optional site-wide questions per day; 0 turns it off (default 0) |
| `DEMO_REPO_URL` | no | Pre-indexed on first start and never deleted, so visitors who add it (the sample button) get it instantly |
| `MAX_REPO_SIZE_MB` | no | Larger repositories are rejected (default 200) |
| `ASK_RATE_LIMIT_PER_MINUTE` | no | Questions per visitor per minute (default 10) |
| `GITHUB_TOKEN` | no | Raises GitHub's API limit for the repo size check (a token with no scopes is enough). It is never used to clone private repositories: visitors who want a private repository paste their own token in the UI, which is kept in memory for that request only |
| `OVERVIEW` | no | Build a repository overview (folder tree, README, one-line LLM summaries) when indexing (default true) |
| `OVERVIEW_MAX_CALLS` | no | Most LLM calls per repository for overview summaries (default 5; each call summarizes up to `OVERVIEW_BATCH_SIZE`=20 items). `OVERVIEW_MAX_FILES` (60), `OVERVIEW_MAX_FOLDERS` (25) and `OVERVIEW_FILE_CHARS` (1200) bound the cost further |
| `ROUTING` / `ROUTING_LLM` | no | Route questions to a help answer (about the tool), the overview, or code search; rules decide first and the LLM is asked only when they are unsure (both default true). `OVERVIEW_K` (3) overview chunks are added for overview questions |
| `FOLLOWUP_REWRITE` | no | Rewrite follow-up questions ("how long is it valid?") into standalone questions using the recent chat before searching; an LLM call is made only when the question has a reference word and there is history (default true) |
| `QUERY_EXPANSION` | no | Ask the LLM for `EXPANSION_VARIANTS` (3) search variants of each question and fuse the results; off by default because it lowered Hit@5 and citation precision in the evaluation and adds an LLM call. `EXPANSION_ORIGINAL_WEIGHT` (4) counts the original query several times in the fusion; `EXPANSION_SKIP_ABOVE` (0 = never) skips expansion when the best match is already this similar |
| `CALL_CONTEXT`, `CALL_MAX_FUNCTIONS`, `CALL_MAX_LINES` | no | Add the definitions of repository functions that the retrieved code calls to the LLM context (defaults: true, 4, 150) |
| `PARENT_CONTEXT`, `PARENT_MAX_LINES`, `PARENT_WINDOW` | no | Give the LLM the enclosing class or file section of each retrieved chunk instead of the chunk alone (defaults: false, 100, 10) |
| `SELF_CHECK`, `SELF_CHECK_ACTION` | no | After answering, a second LLM call checks every claim against the cited code; unsupported claims are removed (`remove`) or listed under the answer (`flag`). Defaults: true, remove. Turn it off to halve LLM calls per question |
| `CONFIDENCE_HIGH_SCORE`, `CONFIDENCE_LOW_MARGIN` | no | Thresholds for the confidence badge (defaults 0.70 and 0.03 above `MIN_VECTOR_SCORE`) |
| `LLM_INPUT_PRICE_PER_MILLION`, `LLM_OUTPUT_PRICE_PER_MILLION` | no | Prices used to estimate cost on the Usage stats page (defaults 0.10 and 0.40 USD per million tokens; the free tier is not billed). Per-question stats are stored in `data/stats.sqlite3` inside the `app-data` volume |
| `EMBEDDING_CACHE`, `ANSWER_CACHE` | no | Reuse embeddings of identical chunk text (`data/embeddings.sqlite3`) and whole answers to identical questions on the same commit (`data/answers.sqlite3`); answers are invalidated on re-index (defaults: true) |
| `SUGGESTED_QUESTIONS` | no | After indexing, generate 5 example questions (one LLM call) shown as buttons and in refusals (default true) |
| `HYGIENE`, `DOWNWEIGHT_FACTOR`, `DOWNWEIGHT_TESTS`, `MAX_JSON_KB`, `HYGIENE_EXTRA_SKIP`, `HYGIENE_EXTRA_DOWNWEIGHT` | no | Index hygiene (defaults: on, 0.9, true, 50). Data files (JSON in fixtures/data/locales folders, JSON over 50 KB that is not a manifest), snapshots, lockfiles and source maps are not indexed; generated code, fixtures, migrations and tests get their search score multiplied by the factor. The two extra lists take JSON arrays of patterns such as `["*/vendor_data/*"]` |

## Step 11: Start the stack

1. Build the image and start all three containers in the background:
   ```bash
   cd ~/codebase-qa && docker compose up -d --build
   ```
   The first build takes **10-20 minutes**: it installs CPU-only PyTorch and downloads both models into the image.
   Later builds reuse the cached layers and are much faster.
2. Check the status:
   ```bash
   docker compose ps
   ```
   Wait until `backend` and `frontend` show `(healthy)` and `caddy` shows `Up`.
3. Open `https://YOUR_DOMAIN` in your browser. The first visit can take up to a minute while Caddy obtains the
   certificate.
4. No password is needed to ask questions. The demo repository indexes in the background (about 3-5 minutes); the
   progress is visible in the backend logs (step 12). Once it appears in the **Repository** picker, ask a question.

## Step 12: Check logs and health

All commands run on the VM in `~/codebase-qa`.

- Follow the backend logs (JSON lines: requests, indexing jobs, errors). Press **Ctrl+C** to stop following:
  ```bash
  docker compose logs -f backend
  ```
- Caddy logs (certificate problems show up here):
  ```bash
  docker compose logs --tail 100 caddy
  ```
- Frontend logs:
  ```bash
  docker compose logs --tail 100 frontend
  ```
- Backend health from inside the VM:
  ```bash
  docker compose exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
  ```
- Memory and disk:
  ```bash
  free -h && df -h /
  ```

| Symptom | Likely cause | Fix |
|---|---|---|
| Browser can't connect at all | VM stopped, or ports 80/443 closed | Start the VM; check step 3 |
| Certificate error, Caddy logs mention "challenge" | DNS label wrong or port 80 blocked | Check `DOMAIN` in `.env` against step 4, check step 3, then `docker compose restart caddy` |
| "Cannot reach the backend" in the page | Backend still starting or crashed | `docker compose ps`, `docker compose logs backend` |
| Answers say the AI model's quota is used up and only list code locations | Gemini free-tier daily quota used up (it resets at midnight Pacific time) | Wait for the reset, or set another `GEMINI_MODEL` in `.env` and run `docker compose up -d` |
| Build stops with "Killed" | Out of memory | Make sure swap from step 8 is on (`free -h`), then build again |
| Build fails with "no space left on device" | Old images and build cache filled the 30 GB disk | `docker image prune -af && docker builder prune -af`, check `df -h /`, then build again. The running site keeps working while you do this |

## Step 13: Update to a new version

The code is on GitHub (<https://github.com/avinashtorm/codebase-qa>), so the VM can pull updates itself. All commands
run **on the VM** (the `azureuser@codebase-qa-vm:~$` window).

**One time only**, turn the uploaded folder into a git checkout (your `.env` is copied over; indexes and certificates
live in Docker volumes and are not touched):

```bash
cd ~ && git clone https://github.com/avinashtorm/codebase-qa.git codebase-qa-git && cp ~/codebase-qa/.env ~/codebase-qa-git/.env && chmod 600 ~/codebase-qa-git/.env
```
```bash
mv ~/codebase-qa ~/codebase-qa-old && mv ~/codebase-qa-git ~/codebase-qa
```

**Every update** (pull, rebuild, restart, clean up):

```bash
cd ~/codebase-qa && git pull
```
```bash
docker compose up -d --build
```
```bash
docker image prune -af && docker builder prune -af
```

The Compose project name is fixed (`codebase-qa`), so the `app-data` volume (indexes, caches, stats, feedback) and the
Caddy certificate survive. Remove old images and build cache every time: the VM disk is 30 GB and each rebuild leaves
several GB behind ("no space left on device" otherwise).

Then check:

```bash
docker compose ps && free -h && docker stats --no-stream
```

The backend should use well under 3 GB at idle: measured locally, the backend process peaks at about 0.5 GB resident
(1.4 GB committed, mostly PyTorch reservations), the UI about 0.1 GB and Caddy a few tens of MB. The reranker is
baked into the image but not loaded unless `RERANK=true`.

What happens on the first start after the v2 update: new SQLite files appear in the volume (`stats.sqlite3`,
`feedback.sqlite3`, `answers.sqlite3`, `embeddings.sqlite3`), and the pinned demo repository gets its repository
overview and suggested questions in a background job (about 6 Gemini calls, 1-2 minutes; watch
`docker compose logs -f backend`). Visitor repositories indexed with the old version keep working and get the new
features when they are added again.

**Alternative without git** (as in step 9): package and upload from Windows, then replace the code on the VM.

1. In **PowerShell on Windows**, package and upload the new commit as in step 9:
   ```powershell
   cd "$HOME\OneDrive\Desktop\codebase-qa"
   ```
   ```powershell
   git archive --format=tar.gz -o "$HOME\codebase-qa.tar.gz" HEAD
   ```
   ```powershell
   scp -i "$HOME\.ssh\codebase-qa-key.pem" "$HOME\codebase-qa.tar.gz" azureuser@YOUR_DOMAIN:~/
   ```
2. **On the VM**, replace the code but keep `.env`:
   ```bash
   cd ~/codebase-qa && find . -mindepth 1 -maxdepth 1 ! -name .env -exec rm -rf {} +
   ```
   ```bash
   tar -xzf ~/codebase-qa.tar.gz -C ~/codebase-qa
   ```
3. Rebuild and restart. Your indexes and the HTTPS certificate are kept, because they live in Docker volumes:
   ```bash
   docker compose up -d --build
   ```
4. Remove old images and build cache to free disk space. The VM disk is only 30 GB and every rebuild leaves several
   GB of cache behind; skipping this step fills the disk after a few updates ("no space left on device"):
   ```bash
   docker image prune -af && docker builder prune -af
   ```

## Step 14: Stop or remove everything

- **Pause:** VM **Overview -> Stop**. Compute billing stops; disk and IP still cost about $6 per month.
- **Remove completely:** search **Resource groups**, open `codebase-qa-rg`, click **Delete resource group**, and type
  its name to confirm. This deletes the VM, disk, IP and network, and stops all charges.

## Backups (optional)

The indexes live in the Docker volume `codebase-qa_app-data`. To save a copy on the VM:
```bash
docker run --rm -v codebase-qa_app-data:/data -v "$HOME":/backup alpine tar czf /backup/app-data.tgz -C /data .
```
You can always rebuild an index by re-indexing the repository, so backups are a convenience, not a requirement.

## GitHub Actions (optional)

If you push the project to GitHub:
- `.github/workflows/ci.yml` runs on every push: `ruff check`, the full test suite (no API key needed) and a Docker
  image build, so the Dockerfile is verified before it reaches the VM.
- `.github/workflows/eval.yml` is started by hand (**Actions -> Eval subset -> Run workflow**) and posts the metrics for
  the first 10 dev questions as the job summary. For answer-level metrics add the repository secret `GEMINI_API_KEY`
  under **Settings -> Secrets and variables -> Actions**.

## Security model

- Only `https://github.com/<owner>/<repo>` URLs are accepted. Repositories are shallow-cloned with a timeout, without
  tags, hooks, symlinks, LFS downloads or the `ext` transport, and their code is never executed.
- The repository size is checked before cloning (GitHub API) and after cloning (on disk). Visitor repositories are
  private to the visitor's link, deleted 24 hours after their last use, and capped at 15 stored (oldest removed first).
- Indexing runs as a single background job at a time; progress is available at `GET /jobs/{id}`.
- Per-visitor limits: 5 new repositories and 30 questions per day, 10 questions per minute. The visitor IP is the last
  `X-Forwarded-For` hop, added by Caddy and forwarded by Streamlit to the backend, which is not reachable from the
  internet.
- No sign-up or password for visitors. The optional `DEMO_PASSWORD` is an owner password for re-indexing only. The LLM
  response cache (`LLM_CACHE=true` in compose) makes repeated questions free; an optional site-wide daily question cap
  (`ASK_DAILY_LIMIT`) is off by default. Errors never include stack traces or server
  paths.
