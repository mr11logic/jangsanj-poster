"""FastAPI service that generates JangSanj posters on demand.

Endpoints
---------
GET  /health            -> {"status":"ok", "today_en": "...", "today_fa": "..."}
GET  /sample            -> quick demo poster with today's date + sample percents
POST /generate          -> accepts JSON, returns PNG (image/png)

POST /generate request body
---------------------------
{
  "percent_24h": 28,           # number or string like "28" or "28.5"
  "percent_7d": 35,
  "percent_30d": 47,
  "date":  "2026-11-01",       # OPTIONAL ISO date (YYYY-MM-DD) — applies to
                               # both date_en and date_fa if they're absent.
  "date_en": "November 01, 2026",   # OPTIONAL override (any string)
  "date_fa": "یکشنبه ۱۰ آبان ۱۴۰۵",  # OPTIONAL override
  "filename": "jangsanj_2026-11-01.png"  # OPTIONAL (only used by /generate?as=file)
}

POST /generate response
-----------------------
By default: image/png binary (200 OK) — perfect for the n8n HTTP Request node
with "Response Format = File".

If you append `?as=file` to the URL, you get a JSON envelope with a download
URL instead — handy if you want to keep the file cached server-side for
debugging.

Run
---
    uvicorn app:app --host 0.0.0.0 --port 8000

Or via the included run.sh:
    ./run.sh
"""
from __future__ import annotations

import os
import json
import datetime as dt
from pathlib import Path
from typing import Any, Dict, Optional, Union

from fastapi import FastAPI, HTTPException, Query, Request, Body
from fastapi.responses import Response, JSONResponse, FileResponse
from pydantic import BaseModel, Field

from poster import generate_poster, generate_poster_to_file
from date_utils import format_english_date, format_persian_date

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------
class PosterRequest(BaseModel):
    percent_24h: Optional[Union[float, int, str]] = Field(
        default=None,
        description="24-hour percentage, e.g. 28 or 12.5 or '28%'",
    )
    percent_7d: Optional[Union[float, int, str]] = Field(
        default=None,
        description="7-day percentage",
    )
    percent_30d: Optional[Union[float, int, str]] = Field(
        default=None,
        description="30-day percentage",
    )
    date: Optional[str] = Field(
        default=None,
        description="ISO date YYYY-MM-DD. Applied to both date_en and "
                    "date_fa if those are not explicitly set. Defaults to today.",
    )
    date_en: Optional[str] = Field(
        default=None,
        description="Override the English date string verbatim.",
    )
    date_fa: Optional[str] = Field(
        default=None,
        description="Override the Persian date string verbatim.",
    )
    filename: Optional[str] = Field(
        default=None,
        description="Filename to use when ?as=file is requested.",
    )


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="JangSanj Poster Generator",
    version="1.0.0",
    description="Overlay dynamic text (24h/7d/30d percentages + dates) on the "
                "JangSanj template and return a 1080x1080 PNG.",
)


@app.get("/health")
def health():
    """Lightweight liveness probe — also shows today's formatted dates."""
    today_iso = dt.date.today().isoformat()
    return {
        "status": "ok",
        "today_iso": today_iso,
        "today_en": format_english_date(),
        "today_fa": format_persian_date(),
    }


@app.get("/sample")
def sample(response: str = Query("binary",
                                  description="'binary' (default) returns PNG bytes; "
                                              "'file' saves to disk and returns JSON")):
    """Quick demo: 28% / 35% / 47% with today's date. Useful for sanity check."""
    values = {
        "percent_24h": 28,
        "percent_7d": 35,
        "percent_30d": 47,
    }
    data = generate_poster(values, CONFIG_PATH)
    if response.lower() in ("file", "json", "true", "1", "yes"):
        out = OUTPUT_DIR / "sample.png"
        with open(out, "wb") as f:
            f.write(data)
        return FileResponse(out, media_type="image/png",
                            filename="sample.png")
    return Response(content=data, media_type="image/png")


@app.post("/generate")
def generate(req: PosterRequest,
             response: str = Query("binary",
                                   description="'binary' (default) streams PNG; "
                                               "'file' saves to disk and returns JSON")):
    """Generate a poster PNG from the supplied values."""
    # Build the values dict for the poster generator
    values: Dict[str, Any] = {}
    if req.percent_24h is not None:
        values["percent_24h"] = req.percent_24h
    if req.percent_7d is not None:
        values["percent_7d"] = req.percent_7d
    if req.percent_30d is not None:
        values["percent_30d"] = req.percent_30d
    if req.date is not None:
        values["date"] = req.date
    if req.date_en is not None:
        values["date_en"] = req.date_en
    if req.date_fa is not None:
        values["date_fa"] = req.date_fa

    try:
        data = generate_poster(values, CONFIG_PATH)
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"Poster generation failed: {e}")

    if response.lower() in ("file", "json", "true", "1", "yes"):
        # Save to disk and return a JSON envelope
        fname = req.filename or _default_filename(values)
        safe = _safe_filename(fname)
        out_path = OUTPUT_DIR / safe
        with open(out_path, "wb") as f:
            f.write(data)
        return JSONResponse({
            "ok": True,
            "filename": safe,
            "path": str(out_path.relative_to(BASE_DIR)),
            "size_bytes": out_path.stat().st_size,
            "url": f"/output/{safe}",
        })

    # Default: stream PNG bytes back. n8n HTTP Request node with
    # "Response Format = File" will save this directly as a binary.
    return Response(content=data, media_type="image/png")


@app.get("/output/{name}")
def serve_output(name: str):
    """Serve a previously generated file (used when ?as=file is requested)."""
    safe = _safe_filename(name)
    p = OUTPUT_DIR / safe
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(p, media_type="image/png", filename=safe)


# ---------------------------------------------------------------------------
# Placid-compatible endpoint — returns JSON with a `polling_url` field.
# Use this when your n8n Telegram SendPhoto node uses `file: {{ $json.polling_url }}`
# (i.e. it expects a URL string instead of binary data).
#
# Accepts both flat body and Placid-style nested body:
#   Flat:    {"percent_24h":28, "percent_7d":35, "percent_30d":47, "date":"2026-11-06"}
#   Placid:  {"template_uuid":"...", "layers":{"percent_24h":{"text":"28%"}, ...}}
# ---------------------------------------------------------------------------
def _extract_values(body: Dict[str, Any]) -> Dict[str, Any]:
    """Pull percent_24h / percent_7d / percent_30d / date_* out of either a
    flat body or a Placid-style nested `layers` body."""
    # Placid-style: top-level "layers" with per-layer "text"
    layers = body.get("layers")
    if isinstance(layers, dict):
        def _layer_text(key: str) -> Optional[str]:
            v = layers.get(key)
            if isinstance(v, dict):
                return v.get("text")
            if isinstance(v, str):
                return v
            return None
        out = {}
        for k in ("percent_24h", "percent_7d", "percent_30d",
                  "date_en", "date_fa"):
            t = _layer_text(k)
            if t is not None:
                out[k] = t
        # Placid templates often pass percent values like "28%" — our
        # _format_percent already strips the trailing %, so just pass through.
        return out
    # Flat body: just copy the keys we care about
    out = {}
    for k in ("percent_24h", "percent_7d", "percent_30d",
              "date", "date_en", "date_fa"):
        if k in body and body[k] is not None:
            out[k] = body[k]
    return out


def _base_url(request: Request) -> str:
    """Construct the public base URL of this service from request headers.

    Respects `X-Forwarded-Proto` and `X-Forwarded-Host` set by Render's /
    Cloud Run's / nginx's reverse proxy. Falls back to `BASE_URL` env var
    if set (useful when behind a custom domain), then to the raw Host header.
    """
    env_base = os.environ.get("BASE_URL")
    if env_base:
        return env_base.rstrip("/")
    scheme = request.headers.get("x-forwarded-proto") or \
        ("https" if request.url.is_secure else "http")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") \
        or "localhost"
    return f"{scheme}://{host}"


@app.post("/generate-url")
def generate_url(request: Request, body: Dict[str, Any] = Body(...)):
    """Generate a poster, save it to disk, return JSON with `polling_url`.

    Drop-in replacement for Placid's POST https://api.placid.app/api/rest/images.
    Returns the same shape that the n8n Telegram SendPhoto node already
    expects when configured with `file: {{ $json.polling_url }}`.
    """
    values = _extract_values(body)
    if not values:
        raise HTTPException(status_code=400,
                            detail="No percent_* / date_* fields found in body.")

    try:
        data = generate_poster(values, CONFIG_PATH)
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"Poster generation failed: {e}")

    fname = _safe_filename(values.get("filename") or _default_filename(values))
    out_path = OUTPUT_DIR / fname
    with open(out_path, "wb") as f:
        f.write(data)

    base = _base_url(request)
    polling_url = f"{base}/output/{fname}"

    return JSONResponse({
        "ok": True,
        "filename": fname,
        "path": str(out_path.relative_to(BASE_DIR)),
        "size_bytes": out_path.stat().st_size,
        "url": f"/output/{fname}",
        # Placid-compatible field — Telegram SendPhoto's `file` field can use
        # this URL directly:
        "polling_url": polling_url,
        "image_url": polling_url,  # alias for clarity
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _default_filename(values: Dict[str, Any]) -> str:
    """Pick a sensible filename based on date or today."""
    d_raw = values.get("date") or values.get("date_en")
    if isinstance(d_raw, str) and len(d_raw) >= 10 and "-" in d_raw[:5]:
        # ISO-like date — use first 10 chars
        d_part = d_raw[:10]
    else:
        d_part = dt.date.today().isoformat()
    return f"jangsanj_{d_part}.png"


def _safe_filename(name: str) -> str:
    """Strip path components and enforce .png extension."""
    n = os.path.basename(name)
    if not n.endswith(".png"):
        n = n + ".png" if "." not in n else n.rsplit(".", 1)[0] + ".png"
    # Allow alphanumerics, dash, underscore, dot
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    n = "".join(c if c in allowed else "_" for c in n)
    if not n:
        n = "poster.png"
    return n


# ---------------------------------------------------------------------------
# Run with: python3 app.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting JangSanj poster service on http://{host}:{port}")
    print(f"  Try: curl http://{host}:{port}/health")
    print(f"  Try: curl http://{host}:{port}/sample -o sample.png")
    print(f"  Try: curl -X POST http://{host}:{port}/generate \\")
    print(f"        -H 'Content-Type: application/json' \\")
    print(f"        -d '{{\"percent_24h\":28,\"percent_7d\":35,\"percent_30d\":47}}' \\")
    print(f"        -o poster.png")
    uvicorn.run(app, host=host, port=port)
