# JangSanj Poster Generator

A small FastAPI service that overlays dynamic text — three percentages
(24-hour / 7-day / 30-day) plus English and Persian dates — onto the
**JangSanj** 1080×1080 background template, then returns a PNG image.
Designed to be called every day from an **n8n** workflow.

---

## 📁 Project layout

```
poster_service/
├── app.py                # FastAPI service (HTTP endpoints)
├── poster.py             # Core Pillow-based poster generation
├── date_utils.py         # Gregorian → Jalali date formatting with Persian digits
├── config.json           # All positions, fonts, colors — EDIT THIS to tweak layout
├── run.sh                # Convenience launcher (auto-installs deps on first run)
├── requirements.txt      # Python dependencies
├── fonts/                # Vazirmatn (Regular, Medium, Bold, Black)
│   ├── Vazirmatn-Regular.ttf
│   ├── Vazirmatn-Medium.ttf
│   ├── Vazirmatn-Bold.ttf
│   └── Vazirmatn-Black.ttf
├── templates/
│   └── Template-JangSanj.jpg   # The 1080×1080 background template
└── output/               # Generated posters (when using ?response=file)
```

---

## 🚀 Quick start

```bash
cd poster_service
pip install -r requirements.txt
./run.sh                          # starts uvicorn on 0.0.0.0:8000

# In another terminal:
curl http://localhost:8000/health
curl http://localhost:8000/sample -o sample.png
```

Open `sample.png` — you should see the JangSanj template with 28% / 35% / 47%
and today's date filled in.

---

## 🔌 API reference

### `GET /health`
```json
{
  "status": "ok",
  "today_iso": "2026-11-06",
  "today_en": "November 06, 2026",
  "today_fa": "جمعه ۱۵ آبان ۱۴۰۵"
}
```

### `GET /sample`
Returns a demo PNG (28% / 35% / 47% + today's date). Useful for sanity checks.

### `POST /generate`
**Request body** (JSON):

| Field          | Type             | Required | Notes |
|----------------|------------------|----------|-------|
| `percent_24h`  | number or string | recommended | 24-hour percentage, e.g. `28` or `28.5` or `"28%"` |
| `percent_7d`   | number or string | recommended | 7-day percentage |
| `percent_30d`  | number or string | recommended | 30-day percentage |
| `date`         | string (ISO)     | optional  | `YYYY-MM-DD`. Applied to **both** `date_en` and `date_fa` if they're not explicitly set. Defaults to today. |
| `date_en`      | string           | optional  | Override the English date string verbatim |
| `date_fa`      | string           | optional  | Override the Persian date string verbatim |
| `filename`     | string           | optional  | Used only when `?response=file` |

**Response** depends on the `response` query parameter:

| `?response=` | Behavior |
|--------------|----------|
| `binary` *(default)* | Returns PNG bytes with `Content-Type: image/png`. Best for n8n. |
| `file`              | Saves the PNG to `output/` and returns JSON: `{"ok":true, "filename":"…", "url":"/output/…"}` |

#### Example: cURL (binary response)
```bash
curl -X POST http://localhost:8000/generate \
  -H 'Content-Type: application/json' \
  -d '{"percent_24h":28,"percent_7d":35,"percent_30d":47,"date":"2026-11-01"}' \
  -o poster.png
```

#### Example: cURL (file response)
```bash
curl -X POST 'http://localhost:8000/generate?response=file' \
  -H 'Content-Type: application/json' \
  -d '{"percent_24h":18.5,"percent_7d":22,"percent_30d":31,"date":"2026-11-06","filename":"nov6.png"}'
# -> {"ok":true,"filename":"nov6.png","path":"output/nov6.png",...}
```

### `GET /output/{filename}`
Serves a previously generated PNG from `output/` (used in `?response=file` mode).

---

## 🔗 n8n integration (step by step)

The recommended pattern is a single **HTTP Request** node that POSTs the
percentages + date and receives the PNG as a binary file. n8n then writes
that file to disk, uploads it to S3/Telegram/Twitter, etc.

### Step 1 — Run the service somewhere reachable from n8n

- **Same host as n8n**: `./run.sh` and use `http://localhost:8000` as the URL.
- **Different host / Docker**: build a small Docker image
  ```dockerfile
  FROM python:3.11-slim
  WORKDIR /app
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  COPY . .
  EXPOSE 8000
  CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
  ```
  Build & run:
  ```bash
  docker build -t jangsanj-poster .
  docker run -d -p 8000:8000 --name jangsanj jangsanj-poster
  ```
  Then use `http://<docker-host>:8000` as the URL.

### Step 2 — n8n workflow

A typical daily workflow looks like this:

```
[Schedule Trigger (daily 09:00)]
        ↓
[Code or Set node — compute percent_24h, percent_7d, percent_30d]
        ↓
[HTTP Request → POST /generate]   ← returns binary PNG
        ↓
[Write to disk / Upload to Telegram / Tweet / ...]
```

### Step 3 — HTTP Request node configuration

| Field | Value |
|-------|-------|
| **Method** | `POST` |
| **URL** | `http://localhost:8000/generate` *(or your host)* |
| **Authentication** | None *(add a token in `app.py` if exposed publicly)* |
| **Send Body** | ✅ Yes |
| **Body Content Type** | `JSON` |
| **Specify Body** | `Using JSON` *(or "Using Expressions")* |
| **JSON Body** | see below |
| **Response Format** | `File` ← **critical**: tells n8n to treat the response as binary |
| **Binary Property** | `data` *(default)* |

**JSON body** (you can also build this with expressions referencing
previous nodes):

```json
{
  "percent_24h": "{{ $json.percent_24h }}",
  "percent_7d":  "{{ $json.percent_7d }}",
  "percent_30d": "{{ $json.percent_30d }}",
  "date":        "{{ $now.toISO().slice(0, 10) }}"
}
```

After this node runs, `{{ $binary.data }}` will contain the PNG. Use a
**Write Binary File** node to save it, or any node that accepts binary
input (Telegram, AWS S3, Twitter, Discord, etc.).

### Step 4 — Test it
- Add a **Schedule Trigger** firing every minute (temporarily) to iterate fast.
- After the HTTP Request node, drop a **Write Binary File** node with
  `fileName: /tmp/test_poster.png`.
- Verify the file looks right.
- Switch the Schedule Trigger back to daily 09:00 (or whatever you want).

---

## 🎨 Fonts used

The project bundles two font families (no system fonts needed at runtime):

| Use | Font | File |
|-----|------|------|
| Persian text (date_fa) | **Dana Medium** (by Font Iran) | `fonts/Dana-Medium.ttf` |
| Persian text (alternate weights) | Dana Regular / Dana Bold | `fonts/Dana-Regular.ttf`, `fonts/Dana-Bold.ttf` |
| Percentages (24h / 7d / 30d) | **Liberation Serif Bold** — free metric-compatible equivalent of Times New Roman | `fonts/LiberationSerif-Bold.ttf` |
| English date | **Liberation Serif Regular** | `fonts/LiberationSerif-Regular.ttf` |

If you have the actual **Times New Roman** TTF file (`times.ttf` from a Windows install, or `Times New Roman.ttf` from macOS), drop it into `fonts/` and update `config.json` → `fonts` → add an entry like `"times_bold": "fonts/timesbd.ttf"`, then point `percent_24h.font` (and the other percent elements) at `times_bold`.

Liberation Serif is intentionally metric-compatible with Times New Roman — same character widths, same proportions — so the layout doesn't shift if you swap fonts.

---

## ⚙️ Customizing the layout

All text positions, font sizes, and colors live in **`config.json`** — no code
changes needed. Each element looks like:

```json
"percent_24h": {
  "text_template": "{value}%",
  "font": "serif_bold",
  "size": 240,
  "color": [255, 51, 51],
  "anchor": "mm",
  "position": [540, 330],
  "persian_digits": false,
  "direction": null,
  "stroke": null
}
```

| Field | Meaning |
|-------|---------|
| `text_template` | Optional printf-style template, e.g. `"{value}%"`. `{value}` is replaced by the formatted number. |
| `font` | One of the keys in `config.json → fonts` (e.g. `serif_bold`, `dana_medium`). |
| `size` | Font size in pixels. |
| `color` | `[R, G, B]` 0–255. |
| `anchor` | PIL text anchor: `mm` (middle-middle), `lm` (left-middle), `rm` (right-middle), `la` (left-ascender), `ra` (right-ascender), etc. |
| `position` | `[x, y]` in template pixels where the anchor point sits. |
| `persian_digits` | If `true`, converts `0-9` → `۰-۹`. |
| `direction` | `"rtl"` for Persian text, `null` for LTR (English/numbers). |
| `stroke` | `null` or `{"width": 2, "fill": [0, 0, 0]}` for an outline. |

### Default layout (matches the JangSanj template)

| Element | Anchor | Position | Size | Color |
|---------|--------|----------|------|-------|
| `percent_24h`  | `mm` | `(540, 330)` | 240 | red `[255, 51, 51]` |
| `percent_7d`   | `mm` | `(730, 665)` | 105 | red `[255, 51, 51]` |
| `percent_30d`  | `mm` | `(350, 665)` | 105 | red `[255, 51, 51]` |
| `date_en`      | `lm` | `(215, 175)` | 30  | white `[255, 255, 255]` |
| `date_fa`      | `rm` | `(865, 175)` | 30  | white `[255, 255, 255]` |

The big central red box spans rows 115–580, cols 175–904.
The two small boxes span rows 604–827 (left cols 176–523, right cols 556–903).
Dates sit at the top of the big box, percentages sit in the empty space above
each label.

### Replacing the template

Just overwrite `templates/Template-JangSanj.jpg` with your own 1080×1080 image.
If the new template has the labels in different positions, update the
`position` arrays in `config.json` accordingly.

### Replacing the font

Drop new `.ttf` files into `fonts/`, then add or rename keys under
`config.json → fonts`. For Persian text, Dana or Vazirmatn work well.
For Times-style percentages, Liberation Serif is bundled; if you have the
actual Times New Roman TTF, drop it in `fonts/` and reference it.

---

## 🛠️ How Persian text is rendered correctly

PIL needs **libraqm** support to shape Arabic/Persian glyphs and apply
the BiDi algorithm in one pass. The code in `poster.py` checks for raqm
at import time:

- **With raqm** *(default on modern Pillow)*: passes `direction="rtl"` to
  `draw.text()` — HarfBuzz shapes the letters and FriBidi reorders them.
- **Without raqm** *(fallback)*: falls back to `arabic_reshaper` +
  `python-bidi`. Output looks slightly worse but is still readable.

To verify your install has raqm:
```python
python3 -c "from PIL import features; print(features.check('raqm'))"
```

---

## 🧪 Local testing without the server

```bash
python3 poster.py \
  --out /tmp/poster.png \
  --p24 28 --p7 35 --p30 47 \
  --date 2026-11-01
```

This is handy for tweaking `config.json` and seeing the result instantly,
without restarting uvicorn.

---

## ❓ Troubleshooting

**Persian letters appear disconnected / reversed**
→ Your Pillow lacks libraqm. Reinstall Pillow from a wheel that bundles it:
  `pip install --upgrade --force-reinstall Pillow`

**Percentages overlap with the template labels**
→ Edit `config.json`: reduce `size` or move `position` upward (smaller y).

**Date shows the wrong day**
→ Make sure your server timezone matches your expectation. The service uses
  `Asia/Tehran` for "today" fallback. Pass an explicit `date` field to
  override.

**Want to expose the API publicly?**
→ Add authentication. A simple shared token in an `X-API-Key` header is
  enough for a single-user n8n workflow. See FastAPI's
  [security docs](https://fastapi.tiangolo.com/tutorial/security/).

---

## 📜 License

- Code in this folder: MIT-style — do whatever you want.
- Vazirmatn font: SIL Open Font License 1.1 (see Vazirmatn project).
- Template image (`Template-JangSanj.jpg`): provided by you; license follows
  your arrangement with the JangSanj project.
