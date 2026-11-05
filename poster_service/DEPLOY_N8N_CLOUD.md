# Deploy for n8n Cloud

If you use **n8n Cloud** (workflow runs on n8n.io servers), the poster
service cannot run on your laptop or next to n8n — it must be hosted at a
**public URL** that n8n Cloud can reach over HTTPS.

This file lists 4 deployment options, ranked by ease. Pick one and follow
its steps. After deploy, you'll have a URL like
`https://jangsanj-poster.onrender.com` to put into the n8n HTTP Request node.

---

## Option A — Render.com (recommended, easiest)

Free tier is enough for a daily poster job. ~30s cold-start after 15 min idle.

1. **Push the project to GitHub** (any public or private repo works):
   ```bash
   cd poster_service
   git init
   git add .
   git commit -m "JangSanj poster service"
   git branch -M main
   git remote add origin git@github.com:<your-user>/jangsanj-poster.git
   git push -u origin main
   ```
   *(The `render.yaml` and `Dockerfile` already in this folder will be
   auto-detected by Render.)*

2. Go to **https://dashboard.render.com/blueprints** → **New Blueprint** →
   select your GitHub repo.

3. Accept the defaults (the blueprint already names the service
   `jangsanj-poster`, free plan, Frankfurt region).

4. Click **Apply**. Render builds and deploys in ~2 min.

5. When done, Render gives you a URL like:
   `https://jangsanj-poster.onrender.com`

6. Test it:
   ```bash
   curl https://jangsanj-poster.onrender.com/health
   curl https://jangsanj-poster.onrender.com/sample -o sample.png
   ```

✅ Done — skip to **"Configure the n8n Cloud HTTP Request node"** below.

---

## Option B — Railway.app (similar to Render, no cold-start on $5/mo)

1. Go to **https://railway.app** → **New Project** → **Deploy from GitHub repo**
2. Pick your repo (after pushing it as in Option A step 1)
3. Railway auto-detects the Dockerfile
4. In **Settings → Networking → Generate Domain**
5. You'll get `https://jangsanj-poster.up.railway.app`

Cost: ~$5/month (free credit covers a small service).

---

## Option C — Google Cloud Run (generous free tier, scales to zero)

1. Install the `gcloud` CLI: https://cloud.google.com/sdk/docs/install
2. Authenticate:
   ```bash
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   ```
3. Build & push (Cloud Build does both):
   ```bash
   cd poster_service
   gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/jangsanj-poster
   ```
4. Deploy:
   ```bash
   gcloud run deploy jangsanj-poster \
     --image gcr.io/YOUR_PROJECT_ID/jangsanj-poster \
     --region europe-west1 \
     --allow-unauthenticated \
     --port 8000 \
     --memory 512Mi \
     --max-instances 1
   ```
5. Cloud Run prints the URL: `https://jangsanj-poster-xxxx-de.a.run.app`

Free tier: 2 million requests/month + 360,000 vCPU-seconds — way more than
enough for daily use.

---

## Option D — Your own VPS (DigitalOcean / Hetzner / etc.)

For full control, ~$4-5/month.

1. SSH into your VPS:
   ```bash
   ssh root@<vps-ip>
   ```
2. Install Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
3. Upload the project (or `git clone` your repo):
   ```bash
   # from your laptop:
   scp -r poster_service root@<vps-ip>:/opt/
   ```
4. Build & run:
   ```bash
   cd /opt/poster_service
   docker build -t jangsanj-poster .
   docker run -d --name jangsanj-poster \
     -p 80:8000 \
     --restart unless-stopped \
     jangsanj-poster
   ```
5. Set up HTTPS with a domain via **Caddy** (one-liner) or **nginx + Let's Encrypt**.
   Example Caddyfile if your domain is `poster.yourdomain.com`:
   ```
   poster.yourdomain.com {
     reverse_proxy localhost:8000
   }
   ```

---

## Configure the n8n Cloud HTTP Request node

After deploy you have a public URL like `https://jangsanj-poster.onrender.com`.
In n8n Cloud, drop an **HTTP Request** node with:

| Setting | Value |
|---------|-------|
| **Method** | `POST` |
| **URL** | `https://jangsanj-poster.onrender.com/generate` |
| **Authentication** | None *(add an `X-API-Key` header if you added auth in `app.py`)* |
| **Send Body** | ✅ |
| **Body Content Type** | `JSON` |
| **Specify Body** | `Using Expressions` |
| **JSON Body** | see below |
| **Response Format** | `File` ← critical |
| **Binary Property** | `data` |

JSON Body (drag the previous node's outputs into the expressions):

```json
{
  "percent_24h": {{ $json.percent_24h }},
  "percent_7d":  {{ $json.percent_7d }},
  "percent_30d": {{ $json.percent_30d }},
  "date":        "{{ $now.toISO().slice(0, 10) }}"
}
```

The `Response Format = File` setting tells n8n Cloud to save the PNG bytes
into `$binary.data`. The next node (Telegram / Write Binary File / S3 /
Twitter / Discord / etc.) can then use that binary directly.

---

## Quick sanity check after deploy

Run these from your laptop (not the server):

```bash
# 1. Service is alive?
curl https://jangsanj-poster.onrender.com/health
# -> {"status":"ok","today_iso":"2026-11-06","today_en":"November 06, 2026","today_fa":"جمعه ۱۵ آبان ۱۴۰۵"}

# 2. Sample poster?
curl https://jangsanj-poster.onrender.com/sample -o sample.png
open sample.png   # macOS  |  xdg-open sample.png  # Linux

# 3. Real call (same as n8n will make):
curl -X POST https://jangsanj-poster.onrender.com/generate \
  -H 'Content-Type: application/json' \
  -d '{"percent_24h":28,"percent_7d":35,"percent_30d":47,"date":"2026-11-06"}' \
  -o nov6.png
open nov6.png
```

If both files look right, your n8n Cloud workflow will work too.

---

## Security note (recommended)

Anyone with your URL can call `/generate` and burn a few hundred ms of your
container's CPU. For a daily job it doesn't matter, but if you want to lock
it down, add a simple shared-secret check in `app.py`:

```python
from fastapi import Header, HTTPException
API_KEY = os.environ.get("API_KEY")  # set this on Render/Railway/etc.

def _check_auth(x_api_key: str = Header(None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

@app.post("/generate", dependencies=[Depends(_check_auth)])
def generate(...): ...
```

Then in n8n Cloud, add a header `X-API-Key: <your-secret>` in the HTTP
Request node under **Headers**.
