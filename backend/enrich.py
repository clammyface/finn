import io, json, os, re
from datetime import datetime
from pathlib import Path

import requests
from pypdf import PdfReader, PdfWriter
from llm import ask, available, STATS          # importing llm also loads .env

DATA = Path(__file__).parent / "data"
PDF_CACHE = DATA / "pdf_cache"
PDF_CACHE.mkdir(parents=True, exist_ok=True)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")

def load(name, default):
    f = DATA / name
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else default

announcements = load("announcements.json", [])
prices = {p["symbol"]: p for p in load("prices.json", [])}
old = {i["id"]: i for i in load("enriched.json", [])}
KEEP = ("category", "is_intimation", "summary", "results", "people")
AI = available()

# ---------------- categories, rules, priority ----------------
BASE = {"results": 90, "M&A": 85, "management_change": 80, "fund_raise": 75,
        "litigation": 70, "pledging": 70, "capex": 65, "bonus_split": 60,
        "credit_rating": 55, "insider_trading": 55, "dividend": 50,
        "press_release": 45, "earnings_call": 35, "investor_meetings": 20,
        "agm_egm": 15, "postal_ballot": 15, "unclassified": 5}

# Subjects too vague to classify by keyword -> sent to the AI with their details
GENERIC_EXACT = {"updates", "general updates", "others", "general", "intimation", "press release"}
GENERIC_PREFIX = ("outcome of board meeting", "press release", "disclosure under regulation 30",
                  "board meeting intimation", "intimation of board meeting")

RULES = [   # checked in this order against the SUBJECT only
    ("unclassified", ["trading window", "newspaper", "loss of share", "duplicate share",
                      "certificate", "esop", "esos", "74(5)", "auditor", "brsr",
                      "business responsibility", "allotment of securities",
                      "integrated filing-governance", "statement of deviation",
                      "monitoring agency", "closure of trading", "amendment to aoa", "aoa/moa"]),
    ("earnings_call", ["transcript", "recording", "earnings call", "conference call"]),
    ("investor_meetings", ["investor meet", "analyst", "investor conference"]),
    ("results", ["financial result", "investor presentation", "integrated filing-financial"]),
    ("management_change", ["directorate", "change in director", "change in management",
                           "resignation", "appointment", "cessation", "key managerial", "retirement"]),
    ("credit_rating", ["credit rating", "rating"]),
    ("M&A", ["acquisition", "amalgamation", "merger", "demerger", "joint venture",
             "scheme of arrangement", "sale or disposal", "divestment"]),
    ("fund_raise", ["rights issue", "qualified institution", "preferential", "buyback",
                    "buy back", "commercial paper", "debenture", "fund raising", "issue of securities"]),
    ("dividend", ["dividend"]),
    ("bonus_split", ["bonus", "sub-division", "split"]),
    ("pledging", ["pledge", "encumbrance"]),
    ("insider_trading", ["insider trading", "takeover regulations", "sast"]),
    ("litigation", ["litigation", "dispute", "regulatory action", "penalty", "insolvency",
                    "action(s) initiated", "orders passed"]),
    ("capex", ["capacity", "capital expenditure", "new plant"]),
    ("press_release", ["bagging", "receiving of order", "award of order", "news verification",
                       "rumour verification", "clarification"]),
    ("postal_ballot", ["postal ballot"]),
    ("agm_egm", ["general meeting", "shareholders meeting", "agm", "egm", "e-voting"]),
]
# A keyword must start a word: "rating" must not match "operating", "egm" not "segment".
RULE_RE = [(cat, [re.compile(r"(?<![a-z])" + re.escape(w)) for w in words]) for cat, words in RULES]

def norm(subject):
    return re.sub(r"\s*-\s*", "-", " ".join((subject or "").lower().split()))

CALL_WORDS = ("transcript", "recording", "earnings call", "conference call")

def rule_category(subject, details=""):
    s = norm(subject)
    if not s or s in GENERIC_EXACT or s.startswith(GENERIC_PREFIX):
        return None
    for cat, pats in RULE_RE:
        if any(p.search(s) for p in pats):
            # NSE files call transcripts and recordings under the investor-meet subject
            if cat == "investor_meetings" and any(w in (details or "").lower() for w in CALL_WORDS):
                return "earnings_call"
            return cat
    return None

def is_intimation(it):
    t = (it["subject"] + " " + (it["details"] or "")[:300]).lower()
    return any(w in t for w in ("intimation", "to consider", "will be held", "is scheduled"))

SENIOR = re.compile(r"(?<![a-z])(chief|ceo|cfo|coo|cto|managing director|md|chairman|chairperson|"
                    r"whole-time|executive director|president)(?![a-z])")
JUNIOR = re.compile(r"(?<![a-z])(independent|non-executive|nominee|additional director|"
                    r"company secretary|senior management)(?![a-z])")

def people_weight(it):
    """CEO/CFO/MD changes outrank independent-director rotations. Uses extracted roles when known."""
    roles = " ".join(p.get("role") or "" for p in it.get("people") or [])
    t = norm(roles or it["details"][:400]).replace("director/kmp/smp", "")
    if JUNIOR.search(t) and not SENIOR.search(t.replace("non-executive", "")):
        return -25
    return 5 if SENIOR.search(t) else 0

def score(it):
    s = BASE.get(it["category"], 30)
    if it["category"] == "management_change":
        s += people_weight(it)
    if it["category"] == "litigation" and "orders passed" in it["subject"].lower():
        s -= 15                               # mostly routine tax/GST orders
    if it.get("is_intimation"):
        s -= 35                               # a notice about a future event matters less
    p = prices.get(it["symbol"])
    if p and (it.get("time") or "")[:10] == p["date"] and abs(p["pct_change"]) >= 3:
        s += 10                               # the stock moved hard the same day
    return max(0, min(100, s))

def tier(s):
    return "high" if s >= 70 else "medium" if s >= 40 else "low"

def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

# ---------------- prompts ----------------
CLASSIFY_PROMPT = """Classify each Indian stock-exchange announcement into exactly one category:
results, M&A, fund_raise, management_change, litigation, insider_trading, earnings_call,
investor_meetings, credit_rating, dividend, bonus_split, capex, press_release, postal_ballot,
agm_egm, pledging, unclassified.
results = quarterly/annual results, their board approval, results presentations or press releases.
earnings_call = notice, transcript or recording of the earnings call.
unclassified = routine paperwork (ESOP allotments, compliance certificates, newspaper ads,
ESG reports, auditor appointments).
Set is_intimation to true when the filing only announces a FUTURE meeting or event.
Return a JSON object with every id: {"<id>": {"category": "...", "is_intimation": false}}
Announcements:
"""

SUMMARY_PROMPT = """For each Indian stock-exchange announcement write ONE plain-English line
(max 20 words) telling an investor what happened. Include key numbers, amounts, dates and names.
Never start with "The company". If the text has no substance, say what kind of filing it is.
Return a JSON object with every id: {"<id>": "line"}
Announcements:
"""

RESULTS_PROMPT = """This PDF is an Indian listed company's quarterly results filing.
Find the statement of profit and loss for the QUARTER. Prefer CONSOLIDATED; use STANDALONE
only if there is no consolidated statement. It has columns for the current quarter, the
previous quarter and the same quarter last year.
Return JSON:
{"basis": "consolidated or standalone", "unit": "unit printed on the statement, e.g. Rs crore",
 "is_bank": false,
 "quarters": {"current": Q, "previous": Q, "year_ago": Q}}
where Q = {"label": "quarter end, e.g. Sep 2026", "revenue": 0, "other_income": 0,
 "finance_costs": 0, "depreciation": 0, "pbt": 0, "pat": 0}
revenue = Revenue from operations (banks: Total income). pbt = profit before tax.
pat = net profit for the period. Numbers only, no commas. Losses are negative.
Use null when a value is not shown."""

PEOPLE_PROMPT = """From this announcement, list the people whose role changes.
Return JSON: {"people": [{"name": "", "role": "",
 "change": "appointed | re-appointed | resigned | retired | other"}]}
Use only the text. Return an empty list if no names are given.
Announcement:
"""

BIO_PROMPT = """Write a short professional background of <NAME>, newly appointed as <ROLE> at <COMPANY>.
Use ONLY the search results below. If they describe a different person or say nothing useful,
return {"bio": null}.
Return JSON: {"bio": "max 2 sentences: previous roles and employers, years of experience,
education if stated", "previous": ["Company - role"], "source": "most useful URL"}
Search results:
"""

# ---------------- helpers for results ----------------
def get_pdf(url):
    f = PDF_CACHE / re.sub(r"[^A-Za-z0-9.]", "_", url[-90:])
    if f.exists():
        return f.read_bytes()
    r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://www.nseindia.com/"},
                     timeout=90)
    r.raise_for_status()
    f.write_bytes(r.content)
    return r.content

def first_pages(pdf_bytes, n=20):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    if len(reader.pages) <= n:
        return pdf_bytes
    w = PdfWriter()
    for page in reader.pages[:n]:
        w.add_page(page)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()

def pct(new, old):
    if new is None or old in (None, 0):
        return None
    return round((new - old) / abs(old) * 100, 1)

def ebitda(q):
    if any(q.get(k) is None for k in ("pbt", "finance_costs", "depreciation")):
        return None
    return round(q["pbt"] + q["finance_costs"] + q["depreciation"] - (q.get("other_income") or 0), 2)

def build_results(raw):
    qs = raw.get("quarters") or {}
    rows = {}
    for name in ("current", "previous", "year_ago"):
        q = qs.get(name) or {}
        rows[name] = {"revenue": q.get("revenue"),
                      "ebitda": None if raw.get("is_bank") else ebitda(q),
                      "pbt": q.get("pbt"), "pat": q.get("pat")}
    cur, prev, ya = rows["current"], rows["previous"], rows["year_ago"]
    keys = ("revenue", "ebitda", "pbt", "pat")
    margin = None
    if cur["ebitda"] is not None and cur["revenue"]:
        margin = round(cur["ebitda"] / cur["revenue"] * 100, 1)
    return {"basis": raw.get("basis"), "unit": raw.get("unit"),
            "label": (qs.get("current") or {}).get("label"),
            "current": cur,
            "qoq": {k: pct(cur[k], prev[k]) for k in keys},
            "yoy": {k: pct(cur[k], ya[k]) for k in keys},
            "ebitda_margin": margin}

def is_results_pdf(it):
    return (it["category"] == "results" and not it.get("is_intimation")
            and (it.get("pdf") or "").lower().endswith(".pdf"))

# ================= RUN =================
items = []
for a in announcements:
    it = dict(a)
    prev = old.get(a["id"], {})
    for k in KEEP:                              # reuse work from the last run
        if k in prev and not (prev.get("fallback") and k in ("category", "is_intimation")):
            it[k] = prev[k]
    items.append(it)
print("Announcements:", len(items), "| AI:", "on" if AI else "OFF (no GEMINI_API_KEY, rules only)")

# Step 1: rules
todo = []
for it in items:
    if it.get("category"):
        continue
    cat = rule_category(it["subject"], it["details"])
    if cat:
        it["category"], it["is_intimation"] = cat, is_intimation(it)
    else:
        todo.append(it)
# What the rules can sort, not what is already sorted: a re-run also reuses earlier AI answers.
ruled = sum(1 for it in items if rule_category(it["subject"], it["details"]))
print(f"Step 1 rules done. Sending {len(todo)} to the AI")

# Step 2: AI classification, 40 per call
def fallback(i):
    # Placeholder until the AI can see it; flagged so the next run with a key reclassifies it.
    i["category"], i["is_intimation"], i["fallback"] = "press_release", is_intimation(i), True

for batch in chunks(todo, 40):
    if not AI:
        for i in batch:
            fallback(i)
        continue
    payload = [{"id": i["id"], "subject": i["subject"], "details": (i["details"] or "")[:300]}
               for i in batch]
    try:
        res = ask(CLASSIFY_PROMPT + json.dumps(payload, ensure_ascii=False))
    except Exception as e:
        print("  classify batch failed:", e)
        for i in batch:
            fallback(i)
        continue
    for i in batch:
        r = res.get(i["id"], {}) if isinstance(res, dict) else {}
        cat = r.get("category") if isinstance(r, dict) else None
        i["category"] = cat if cat in BASE else "press_release"
        i["is_intimation"] = bool(isinstance(r, dict) and r.get("is_intimation")) or is_intimation(i)
        i.pop("fallback", None)

# Step 3: priority and tier
for it in items:
    it["priority"] = score(it)
    it["tier"] = tier(it["priority"])

# Step 4: results numbers for the latest results filing of each company
latest = {}
for it in items:                                 # items are newest first
    if is_results_pdf(it) and "result" in (it["subject"] + (it["details"] or "")).lower():
        latest.setdefault(it["symbol"], it)
for it in items:
    if is_results_pdf(it):
        latest.setdefault(it["symbol"], it)
for sym, it in latest.items():
    if it.get("results") or not AI:
        continue
    try:
        print("Step 4 results:", sym)
        raw = ask(RESULTS_PROMPT, pdf_bytes=first_pages(get_pdf(it["pdf"])))
        it["results"] = build_results(raw)
    except Exception as e:
        print("  results failed for", sym, "-", e)

# Step 5: people and bios
tav = None
if os.getenv("TAVILY_API_KEY"):
    from tavily import TavilyClient
    tav = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
for it in items:
    if not AI or it["category"] != "management_change" or it.get("is_intimation") or "people" in it:
        continue
    try:
        found = ask(PEOPLE_PROMPT + it["subject"] + "\n" + (it["details"] or "")[:1500]).get("people", [])
    except Exception as e:
        print("  people failed:", e)
        continue
    for person in found[:3]:
        if tav and person.get("name") and person.get("change") in ("appointed", "re-appointed"):
            try:
                q = f'{person["name"]} {person.get("role", "")} {it["company"]} career background'
                res = tav.search(q, max_results=5)
                snippets = [{"title": r.get("title"), "url": r.get("url"),
                             "content": (r.get("content") or "")[:500]}
                            for r in res.get("results", [])]
                prompt = (BIO_PROMPT.replace("<NAME>", person["name"])
                          .replace("<ROLE>", person.get("role", ""))
                          .replace("<COMPANY>", it["company"]))
                person.update(ask(prompt + json.dumps(snippets, ensure_ascii=False)))
            except Exception as e:
                print("  bio failed:", e)
    it["people"] = found
    print("Step 5 people:", it["symbol"], [p.get("name") for p in found])

# Re-score now that people's roles are known
for it in items:
    it["priority"] = score(it)
    it["tier"] = tier(it["priority"])

# Step 6: one-line summaries for medium and high items, 20 per call
need = [i for i in items if i["tier"] in ("high", "medium") and not i.get("summary")] if AI else []
for batch in chunks(need, 20):
    payload = [{"id": i["id"], "subject": i["subject"], "details": (i["details"] or "")[:600]}
               for i in batch]
    try:
        res = ask(SUMMARY_PROMPT + json.dumps(payload, ensure_ascii=False))
    except Exception as e:
        print("  summary batch failed:", e)
        continue
    for i in batch:
        if isinstance(res, dict) and isinstance(res.get(i["id"]), str):
            i["summary"] = res[i["id"]]

# Save
(DATA / "enriched.json").write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
counts = {t: sum(1 for i in items if i["tier"] == t) for t in ("high", "medium", "low")}
# "As of" is when the filings were fetched, so re-running enrichment later doesn't shift the time windows.
src = DATA / "announcements.json"
fetched = datetime.fromtimestamp(src.stat().st_mtime) if src.exists() else datetime.now()
meta = {"as_of": fetched.isoformat(timespec="seconds"), "counts": counts,
        "filings": len(items), "by_rules": ruled, "ai_calls": STATS["calls"],
        "cache_hits": STATS["cached"]}
(DATA / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

print("\nDone:", counts, f"| rules: {ruled}/{len(items)}",
      "| AI calls:", STATS["calls"], "| cache hits:", STATS["cached"])
for i in sorted(items, key=lambda x: -x["priority"])[:10]:
    print(f'{i["priority"]:3} {i["symbol"]:11} {i["category"]:18} {i.get("summary") or i["subject"]}')
