import json, mimetypes
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
import research

BASE = Path(__file__).parent
DATA = BASE / "data"
app = FastAPI(title="FINN")
mimetypes.add_type("application/manifest+json", ".webmanifest")

DEFAULT_TYPES = "results,M&A,management_change,fund_raise,litigation,credit_rating,pledging"

def load(name, default):
    f = DATA / name
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else default

def as_of():
    try:
        return datetime.fromisoformat(load("meta.json", {})["as_of"])
    except (KeyError, ValueError):
        return datetime.now()

def in_window(items, hours):
    # Windows count back from the last data refresh, not from this second.
    end = as_of()
    start = end - timedelta(hours=hours)
    out = []
    for i in items:
        try:
            t = datetime.fromisoformat(i["time"])
        except (TypeError, ValueError, KeyError):
            continue
        if start <= t <= end + timedelta(hours=1):
            out.append(i)
    return out

@app.get("/api/digest")
def digest(hours: int = 24):
    items = in_window(load("enriched.json", []), hours)
    items.sort(key=lambda i: i["time"], reverse=True)          # newest first ...
    items.sort(key=lambda i: i["priority"], reverse=True)      # ... within each priority
    counts = {t: sum(1 for i in items if i["tier"] == t) for t in ("high", "medium", "low")}
    return {"as_of": as_of().isoformat(), "hours": hours, "counts": counts, "items": items}

@app.get("/api/portfolio")
def portfolio():
    return {"as_of": as_of().isoformat(), "stocks": load("prices.json", [])}

@app.get("/api/meta")
def meta():
    return load("meta.json", {})

@app.get("/api/alerts")
def alerts(price: float = 3.0, vol: float = 2.0, types: str = DEFAULT_TYPES, hours: int = 72):
    wanted = {t for t in types.split(",") if t}
    recent = in_window(load("enriched.json", []), hours)
    top_filing = {}
    for i in sorted(recent, key=lambda x: x["priority"], reverse=True):
        top_filing.setdefault(i["symbol"], i)                   # most important recent filing per stock
    out = []
    for p in load("prices.json", []):
        related = top_filing.get(p["symbol"])
        if abs(p["pct_change"]) >= price:
            word = "up" if p["pct_change"] > 0 else "down"
            out.append({"kind": "price", "symbol": p["symbol"], "name": p["name"], "date": p["date"],
                        "title": f'{p["symbol"]} {word} {abs(p["pct_change"])}% on {p["date"]}',
                        "detail": f'Your threshold is ±{price}%', "related": related,
                        "pct_change": p["pct_change"], "vol_ratio": p["vol_ratio"]})
        if p["vol_ratio"] and p["vol_ratio"] >= vol:
            out.append({"kind": "volume", "symbol": p["symbol"], "name": p["name"], "date": p["date"],
                        "title": f'{p["symbol"]} traded {p["vol_ratio"]}x its 20-day average volume',
                        "detail": f'Your threshold is {vol}x', "related": related,
                        "pct_change": p["pct_change"], "vol_ratio": p["vol_ratio"]})
    for i in recent:
        if i["category"] in wanted and not i.get("is_intimation") and i["priority"] >= 40:
            out.append({"kind": "filing", "symbol": i["symbol"], "name": i["company"],
                        "date": i["time"], "title": i.get("summary") or i["subject"],
                        "detail": i["category"], "item": i})
    return {"as_of": as_of().isoformat(), "alerts": out,
            "settings": {"price": price, "vol": vol, "types": sorted(wanted), "hours": hours}}

@app.get("/api/research")
def research_list():
    out = []
    for f in sorted((DATA / "research").glob("*.json")):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        cred = (r.get("analysis") or {}).get("credibility") or {}
        out.append({"symbol": r.get("symbol", f.stem), "name": r.get("name"), "score": cred.get("score")})
    return out

@app.get("/api/research/{symbol}")
def get_research(symbol: str):
    try:
        return research.run(symbol)
    except research.NotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Research failed: {e}")

# The app page. This line must stay LAST so it does not hide the /api routes.
app.mount("/", StaticFiles(directory=BASE / "static", html=True), name="static")
