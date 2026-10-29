import json, warnings
from pathlib import Path
import yfinance as yf

warnings.filterwarnings("ignore")      # yfinance emits pandas deprecation noise

DATA = Path(__file__).parent / "data"
portfolio = json.loads((DATA / "portfolio.json").read_text(encoding="utf-8"))
tickers = [p["symbol"] + ".NS" for p in portfolio]

df = yf.download(tickers, period="3mo", group_by="ticker", auto_adjust=False, progress=False)

out = []
for p in portfolio:
    t = p["symbol"] + ".NS"
    try:
        d = df[t].dropna()
    except KeyError:
        print("No data for", t)
        continue
    if len(d) < 22:
        print("Not enough history for", t)
        continue
    close, vol = d["Close"], d["Volume"]
    avg_vol = vol.iloc[-21:-1].mean()      # previous 20 days, not counting today
    out.append({
        "symbol": p["symbol"],
        "name": p["name"],
        "sector": p["sector"],
        "date": str(d.index[-1].date()),
        "close": round(float(close.iloc[-1]), 2),
        "pct_change": round(float((close.iloc[-1] / close.iloc[-2] - 1) * 100), 2),
        "volume": int(vol.iloc[-1]),
        "avg_vol_20": int(avg_vol),
        "vol_ratio": round(float(vol.iloc[-1] / avg_vol), 2) if avg_vol else None,
        "closes_30d": [round(float(x), 2) for x in close.iloc[-30:]],
    })

(DATA / "prices.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print(f"Saved {len(out)} stocks")
for s in out:
    print(f'{s["symbol"]:12} {s["pct_change"]:+6.2f}%   volume x{s["vol_ratio"]}')
