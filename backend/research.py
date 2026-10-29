import io, json, re, sys, time, hashlib
from datetime import datetime
from pathlib import Path

import pdfplumber
import requests
from bs4 import BeautifulSoup
from llm import ask, CHEAP, STRONG, STATS

DATA = Path(__file__).parent / "data"
OUT_DIR = DATA / "research"
PAGES = OUT_DIR / "_pages"
PAGES.mkdir(parents=True, exist_ok=True)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
SYMBOL_RE = re.compile(r"[A-Z0-9&\-]{1,20}")

class NotFound(Exception):
    pass

# ---------------- screener.in ----------------
def num(s):
    s = s.replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None

def parse_table(soup, section_id):
    table = soup.select_one(f"section#{section_id} table")
    if not table:
        return None
    periods = [th.get_text(strip=True) for th in table.select("thead th")][1:]
    rows = {}
    for tr in table.select("tbody tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        label = cells[0].get_text(" ", strip=True).replace("+", "").strip()
        rows[label] = [num(td.get_text(strip=True)) for td in cells[1:]]
    return {"periods": periods, "rows": rows}

def row(table, *names):
    if not table:
        return None
    for name in names:
        for label, vals in table["rows"].items():
            if label.lower().startswith(name.lower()):
                return vals
    return None

def get(url, **kw):
    # screener answers 429 when hit too fast; back off and retry
    for attempt in range(3):
        r = requests.get(url, timeout=30, **kw)
        if r.status_code != 429:
            return r
        time.sleep(5 * (attempt + 1))
    return r

def fetch_screener(symbol):
    for url in (f"https://www.screener.in/company/{symbol}/consolidated/",
                f"https://www.screener.in/company/{symbol}/"):
        r = get(url, headers=HEADERS)
        if r.status_code != 200:
            continue
        (PAGES / f"{symbol}.html").write_text(r.text, encoding="utf-8")   # for debugging
        soup = BeautifulSoup(r.text, "html.parser")
        sales = row(parse_table(soup, "quarters"), "Sales", "Revenue")
        if sales and any(v is not None for v in sales):
            return soup, url
    raise NotFound(f"{symbol} was not found on screener.in")

def find_transcripts(soup, n=4):
    out, seen = [], set()
    for a in soup.find_all("a"):
        href = a.get("href")
        if a.get_text(strip=True).lower() == "transcript" and href and href not in seen:
            seen.add(href)
            li = a.find_parent("li")
            first = li.find("div") if li else None
            out.append({"date": first.get_text(" ", strip=True) if first else "", "url": href})
    return out[:n]                          # screener lists the newest first

def ratios_of(soup):
    out = {}
    for li in soup.select("#top-ratios li"):
        name = li.select_one(".name")
        val = li.select_one(".value") or li.select_one(".number")
        if name and val:
            out[name.get_text(strip=True)] = " ".join(val.get_text(" ", strip=True).split())
    return out

def yoy(vals, i, back=4):
    if i - back < 0 or vals[i] is None or not vals[i - back]:
        return None
    return round((vals[i] - vals[i - back]) / abs(vals[i - back]) * 100, 1)

def build_snapshot(soup):
    q = parse_table(soup, "quarters") or {"periods": [], "rows": {}}
    sales = row(q, "Sales", "Revenue")
    opm = row(q, "OPM", "Financing Margin")
    op = row(q, "Operating Profit", "Financing Profit")
    npf = row(q, "Net Profit")
    at = lambda vals, i: vals[i] if vals and i < len(vals) else None
    quarters = []
    for i, p in enumerate(q["periods"]):
        quarters.append({"period": p,
                         "sales": at(sales, i),
                         "op_profit": at(op, i),
                         "opm": at(opm, i),
                         "net_profit": at(npf, i),
                         "sales_yoy": yoy(sales, i) if sales else None,
                         "np_yoy": yoy(npf, i) if npf else None})
    # cash conversion and debt from the annual tables
    pl, cf, bs = (parse_table(soup, s) for s in ("profit-loss", "cash-flow", "balance-sheet"))
    np_year = dict(zip(pl["periods"], row(pl, "Net Profit") or [])) if pl else {}
    cfo = dict(zip(cf["periods"], row(cf, "Cash from Operating") or [])) if cf else {}
    debt = dict(zip(bs["periods"], row(bs, "Borrowings") or [])) if bs else {}
    years = [y for y in (cf["periods"] if cf else []) if y in np_year][-5:]
    cash = []
    for y in years:
        c, n = cfo.get(y), np_year.get(y)
        cash.append({"year": y, "cfo": c, "net_profit": n, "borrowings": debt.get(y),
                     "conversion": round(c / n, 2) if c is not None and n else None})
    return {"ratios": ratios_of(soup), "quarters": quarters[-12:], "cash": cash}

# ---------------- transcripts ----------------
def transcript_text(url):
    key = hashlib.md5(url.encode()).hexdigest()
    f = PAGES / f"{key}.txt"
    if f.exists():
        return f.read_text(encoding="utf-8"), None
    r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://www.bseindia.com/"}, timeout=90)
    r.raise_for_status()
    pages = []
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            pages.append(f"[p.{i}]\n" + (page.extract_text() or ""))
    text = "\n".join(pages)
    if len(text) < 3000:                    # scanned PDF with no text layer: let Gemini read the PDF
        return "", r.content
    f.write_text(text, encoding="utf-8")
    return text, None

GUIDANCE_PROMPT = """Below is an earnings call transcript of <COMPANY> (call listed as <DATE>).
Page markers look like [p.3]. Indian fiscal year: FY27 = Apr 2026 to Mar 2027;
Q1 = Apr-Jun, Q2 = Jul-Sep, Q3 = Oct-Dec, Q4 = Jan-Mar.
Extract every forward-looking commitment or guidance given BY MANAGEMENT about measurable things:
revenue growth, margins, profit, capex, capacity, store or plant additions, order book, debt,
volumes, market share, launches with timelines.
Ignore analysts' questions unless management answers with a number or a clear direction.
Return JSON:
{"quarter_discussed": "e.g. Q1 FY26",
 "business": "2 sentences, in management's own framing, on what the company does and its main segments",
 "guidance": [{"metric": "short name", "promise": "paraphrase including the number",
               "timeframe": "e.g. FY26", "quote": "exact words, max 25 words", "page": 4}],
 "tone": "one line on management's tone"}
Use only the transcript. If there is no guidance, return an empty list.
TRANSCRIPT:
"""

LEDGER_PROMPT = """You are checking whether the management of <COMPANY> delivered what they promised.
Use ONLY the two data blocks below. Do not use any outside knowledge about the company.
Indian fiscal year: Q1 = Apr-Jun, Q2 = Jul-Sep, Q3 = Oct-Dec, Q4 = Jan-Mar; FY26 = Apr 2025 to Mar 2026.

PROMISES from earnings calls, oldest first:
<PROMISES>

ACTUAL REPORTED QUARTERLY NUMBERS (Rs crore, quarter-end month; yoy in %):
<ACTUALS>

ANNUAL CASH AND DEBT (Rs crore):
<CASH>

Tasks:
1. Merge repeated promises. For each distinct promise give a verdict: "delivered", "partly",
   "missed" or "too_early" (period not over, or not measurable from these numbers).
   The evidence must cite the actual numbers.
2. narrative_vs_numbers: 2 to 4 points where the story and the numbers agree or diverge.
3. bull and bear: 3 points each, every point backed by a number from the data.
4. credibility: a score from 0 to 10 and one sentence explaining it.
Return JSON:
{"ledger": [{"promise": "", "made_in": "Q1 FY26", "call_date": "", "timeframe": "",
             "verdict": "", "evidence": "", "quote": "", "page": 0}],
 "narrative_vs_numbers": [""], "bull": [""], "bear": [""],
 "credibility": {"score": 0, "line": ""}}"""

# ---------------- main entry ----------------
def run(symbol, refresh=False):
    symbol = symbol.upper().strip()
    if not SYMBOL_RE.fullmatch(symbol):
        raise NotFound(f"{symbol!r} is not a valid NSE symbol")
    out_file = OUT_DIR / f"{symbol}.json"
    if out_file.exists() and not refresh:
        return json.loads(out_file.read_text(encoding="utf-8"))

    calls_before = STATS["calls"]
    soup, page_url = fetch_screener(symbol)
    h1 = soup.select_one("h1")
    name = h1.get_text(strip=True) if h1 else symbol
    snapshot = build_snapshot(soup)
    transcripts = find_transcripts(soup)
    print(name, "-", len(transcripts), "transcripts found")

    calls = []
    for t in reversed(transcripts):          # oldest first
        try:
            text, pdf = transcript_text(t["url"])
            prompt = GUIDANCE_PROMPT.replace("<COMPANY>", name).replace("<DATE>", t["date"])
            if text:
                g = ask(prompt + text[:120000])
            else:
                g = ask(prompt + "(the transcript is the attached PDF)", pdf_bytes=pdf)
            g["call_date"], g["url"] = t["date"], t["url"]
            calls.append(g)
            print("  ", t["date"], "-", len(g.get("guidance", [])), "promises")
        except Exception as e:
            print("   transcript failed:", t["url"], e)

    analysis = {}
    if calls:
        promises = [{"made_in": c.get("quarter_discussed"), "call_date": c["call_date"], **g}
                    for c in calls for g in c.get("guidance", [])]
        actuals = "\n".join(
            f'{q["period"]}: sales {q["sales"]} (yoy {q["sales_yoy"]}), op profit {q["op_profit"]}, '
            f'OPM {q["opm"]}%, net profit {q["net_profit"]} (yoy {q["np_yoy"]})'
            for q in snapshot["quarters"])
        prompt = (LEDGER_PROMPT.replace("<COMPANY>", name)
                  .replace("<PROMISES>", json.dumps(promises, ensure_ascii=False, indent=1))
                  .replace("<ACTUALS>", actuals)
                  .replace("<CASH>", json.dumps(snapshot["cash"])))
        try:
            analysis = ask(prompt, model=STRONG)
        except Exception as e:
            print("   strong model unavailable, using cheap model:", e)
            analysis = ask(prompt, model=CHEAP)

    latest = calls[-1] if calls else {}
    result = {
        "symbol": symbol, "name": name, "source_page": page_url,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "business": latest.get("business"), "tone": latest.get("tone"),
        "snapshot": snapshot,
        "calls": [{"date": c["call_date"], "quarter": c.get("quarter_discussed"), "url": c["url"]}
                  for c in calls],
        "analysis": analysis,
        "ai_calls": STATS["calls"] - calls_before,
    }
    if analysis or not transcripts:          # don't cache a run where every transcript step failed
        out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result

if __name__ == "__main__":
    for s in sys.argv[1:]:
        r = run(s, refresh=True)
        a = r["analysis"]
        print(f'\n{r["name"]}: {len(a.get("ledger", []))} promises checked, '
              f'credibility {a.get("credibility", {}).get("score")}/10, {r["ai_calls"]} AI calls')
        for item in a.get("ledger", [])[:6]:
            print(f'  [{item.get("verdict")}] {item.get("promise")}')
