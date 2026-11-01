# FINN – an inbox zero for investors

Live app: https://finn-f9nc.onrender.com (the first load can take about a minute while the free server wakes up)

FINN has a point of view: an investor doesn't need more information. They need to know **what to decide today**, and **whether the people running their companies keep their word**. So FINN does two things:

- **Push, as triage.** Every NSE filing across a 20-stock portfolio is sorted into **Needs you**, **Worth a glance** or **Filed away**.
  - Each item can be marked **Done**, and the headline counts down to *Inbox zero*.
  - Results filings show Revenue, EBITDA, PBT and PAT, QoQ and YoY.
  - Management changes say who the new person is.
  - Price and volume alerts fire on thresholds you set, each paired with the filing that probably explains the move.
- **Pull, as accountability.** For **any** NSE ticker, the **Promise Ledger**:
  - reads the last six earnings-call transcripts (about 18 months, so some promises are already due)
  - pulls out every measurable promise
  - marks each one *delivered / partly / missed / too early* against the reported numbers, with the quote and a page link
  - gives management a credibility score

## What's in the app

| Tab | What it does |
|---|---|
| **Today** | A brief line computed from the data (no AI), a movers strip with credibility badges, the three tiers, and Done/undo. Window: 24h / 3d / 7d / 30d. |
| **Alerts** | Price and volume moves beyond *your* thresholds, each with the likely filing behind it, plus filings of the types you follow. |
| **Ledger** | Type any NSE symbol. You get a credibility score, a verdict bar you can filter, promise cards with quotes and page links, 12 quarters of sales and margin, cash conversion, story vs numbers, and bull and bear cases. |
| **Watch** | Sliders and filing types that decide what counts as "unusual", plus a live view of how much AI the last refresh used. |

## How it works

```
laptop: prices.py (yfinance) + announcements.py (NSE API) -> enrich.py (rules -> Gemini) -> data/*.json
        git push ──> Render: FastAPI (main.py) serves /api/* and the static mobile page
                     research.py runs live for any ticker: screener.in numbers + transcript PDFs -> Gemini
```

NSE blocks cloud IPs, so filings are fetched on a laptop and published with a git push (`backend/refresh.bat`). Research runs live on the server. Each company's result is cached as JSON, so asking twice costs nothing.

## AI cost discipline

- **Rules first.** Keyword rules, matched at word starts, classify most filings with no AI call: 173 of 284 on the last run.
- **Cheap model for bulk work, in batches.** Classification runs 40 filings per call and summaries 20 per call. Transcripts are read 8 pages per call: given a whole 25-page call at once, the cheap model found 0–2 promises; 8 pages at a time, it finds 6 or more.
- **Strong model only for the ledger verdict**, one call per company.
- **Python does all the arithmetic.** EBITDA, QoQ, YoY and cash conversion are computed in code. The model only reads.
- **Everything is cached on disk.** Each AI answer is keyed by a hash of the prompt and input. On the last full run: 44 AI calls, 2 cache hits; a re-run makes 0 calls (see `data/meta.json`, also shown in the Watch tab).
- **Small inputs.** Only the first 20 pages of a results PDF are sent, and transcripts go as extracted text, not PDFs.
- **Graceful degradation.** With no API key, the whole push side still runs on rules alone.

## Grounding

The ledger sees only the transcripts and the reported numbers from screener.in. It is told not to use outside knowledge. Every promise carries the speaker's exact words and a page number you can click.

Python, not the model, sets that page number: it finds each quote in the transcript text and reads the page marker above it. The models were off by a page on about half the quotes, and once named the wrong call. A quote that can't be found word for word is labelled as such in the app instead of getting a page link.

## Run it locally

```
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
# add GEMINI_API_KEY and TAVILY_API_KEY to backend\.env
python prices.py; python announcements.py; python enrich.py
python research.py DIXON HAVELLS PERSISTENT
uvicorn main:app --reload        # http://127.0.0.1:8000
```

Deploy: on Render, choose New → Blueprint and pick this repo (`render.yaml`), then enter the two API keys.
