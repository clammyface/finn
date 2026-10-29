import json, time
from datetime import datetime, timedelta
from pathlib import Path
import requests

DATA = Path(__file__).parent / "data"
portfolio = json.loads((DATA / "portfolio.json").read_text(encoding="utf-8"))
DAYS = 30
URL = "https://www.nseindia.com/api/corporate-announcements"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/129.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
}

def nse_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get("https://www.nseindia.com", timeout=20)       # collect cookies
    s.get(HEADERS["Referer"], timeout=20)
    return s

def to_iso(t):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M:%S"):
        try:
            return datetime.strptime(t, fmt).isoformat()
        except (TypeError, ValueError):
            pass
    return None

to_d = datetime.now()
from_d = to_d - timedelta(days=DAYS)
s = nse_session()
items, shown_fields = {}, False

for p in portfolio:
    params = {"index": "equities", "symbol": p["symbol"],
              "from_date": from_d.strftime("%d-%m-%Y"), "to_date": to_d.strftime("%d-%m-%Y")}
    rows = None
    for attempt in range(3):
        try:
            r = s.get(URL, params=params, timeout=30)
            if r.status_code == 200:
                rows = r.json()
                break
            print("  retry", p["symbol"], r.status_code)
        except Exception as e:
            print("  retry", p["symbol"], e)
        time.sleep(5)
        s = nse_session()
    if rows is None:
        print(p["symbol"], "FAILED")
        continue
    if isinstance(rows, dict):
        rows = rows.get("data", [])
    if rows and not shown_fields:
        print("FIELDS:", list(rows[0].keys()))
        shown_fields = True

    for it in rows:
        pdf = it.get("attchmntFile") or ""
        key = str(it.get("seq_id") or (p["symbol"] + str(it.get("an_dt")) + str(it.get("desc"))))
        items[key] = {
            "id": key,
            "symbol": p["symbol"],
            "company": it.get("sm_name") or p["name"],
            "subject": it.get("desc") or "",
            "details": it.get("attchmntText") or "",
            "time": to_iso(it.get("sort_date")) or to_iso(it.get("an_dt")),
            "pdf": pdf if pdf.startswith("http") else None,
        }
    print(f'{p["symbol"]:12} {len(rows)} announcements')
    time.sleep(1)   # be polite so NSE does not block you

all_items = sorted(items.values(), key=lambda x: x["time"] or "", reverse=True)
(DATA / "announcements.json").write_text(json.dumps(all_items, indent=2), encoding="utf-8")
print("Total saved:", len(all_items))
