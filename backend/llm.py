import os, sys, json, time, hashlib
from pathlib import Path
from dotenv import load_dotenv

# Filings and summaries contain ₹ and other non-ASCII text; the Windows console would crash printing them.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv(Path(__file__).parent / ".env")
CHEAP = os.getenv("CHEAP_MODEL") or "gemini-3.5-flash-lite"
STRONG = os.getenv("STRONG_MODEL") or "gemini-3.8-flash"

CACHE = Path(__file__).parent / "data" / "llm_cache"
CACHE.mkdir(parents=True, exist_ok=True)
STATS = {"calls": 0, "cached": 0}

_client = None

def available():
    """True when a Gemini key is configured. Without one, callers fall back to rules only."""
    return bool(os.getenv("GEMINI_API_KEY"))

def client():
    # Created on first use, so the server and the rules-only pipeline run without a key.
    global _client
    if _client is None:
        if not available():
            raise RuntimeError("GEMINI_API_KEY missing: add it to backend/.env")
        from google import genai
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client

def ask(prompt, model=None, pdf_bytes=None, as_json=True, retries=4):
    """Ask Gemini. Same question twice = answered from disk, free."""
    model = model or CHEAP
    h = hashlib.md5()
    h.update(model.encode())
    h.update(prompt.encode("utf-8"))
    if pdf_bytes:
        h.update(pdf_bytes)
    f = CACHE / f"{h.hexdigest()}.json"
    if f.exists():
        STATS["cached"] += 1
        return json.loads(f.read_text(encoding="utf-8"))["out"]

    from google.genai import types
    contents = [prompt]
    if pdf_bytes:
        contents = [types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"), prompt]
    config = types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json" if as_json else "text/plain")

    for attempt in range(retries):
        try:
            STATS["calls"] += 1
            r = client().models.generate_content(model=model, contents=contents, config=config)
            out = json.loads(r.text) if as_json else r.text
            f.write_text(json.dumps({"out": out}, ensure_ascii=False), encoding="utf-8")
            return out
        except json.JSONDecodeError:
            print("  model returned bad JSON, retrying")
        except Exception as e:
            msg = str(e)
            if "per day" in msg.lower():         # daily free quota used up: waiting won't help, let the caller fall back
                raise
            if any(c in msg for c in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")):
                wait = 30 * (attempt + 1)
                print(f"  rate limited, waiting {wait}s")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"{model} failed after {retries} tries")
