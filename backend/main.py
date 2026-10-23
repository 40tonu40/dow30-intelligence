import os, sqlite3, json, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import pandas as pd
import yfinance as yf
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DOW30_DB_PATH", str(ROOT / "dow30_intelligence.sqlite3"))
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
app = FastAPI(title="DOW30 Intelligence API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

SYMBOLS = {
    "Dow Jones": "^DJI", "Dow futures (YM)": "YM=F", "S&P 500": "^GSPC",
    "Nasdaq Composite": "^IXIC", "VIX": "^VIX", "10Y Treasury": "^TNX",
    "Oil (WTI)": "CL=F", "Gold": "GC=F"
}
def now_iso(): return datetime.now(timezone.utc).isoformat()
def num(v):
    try:
        f=float(v)
        return round(f, 4) if pd.notna(f) else None
    except Exception: return None
def history_for(symbol, period="5d", interval="15m"):
    return yf.download(symbol, period=period, interval=interval, prepost=True, progress=False, auto_adjust=False, threads=False)
def indicators(df):
    if df is None or df.empty: return {}
    close=df["Close"]
    if isinstance(close, pd.DataFrame): close=close.iloc[:,0]
    close=close.dropna()
    if close.empty: return {}
    last=float(close.iloc[-1]); prev=float(close.iloc[-2]) if len(close)>1 else None
    sma20=float(close.tail(20).mean()) if len(close)>=5 else None
    change=((last/prev)-1)*100 if prev else None
    return {"last":num(last),"previous":num(prev),"change_pct":num(change),"sma20":num(sma20),"bars":int(len(close))}
def clean_frame(df):
    if df is None or df.empty: return []
    df=df.tail(180).copy()
    out=[]
    for idx,row in df.iterrows():
        close=row.get("Close")
        if isinstance(close,pd.Series): close=close.iloc[0]
        out.append({"time":str(idx),"open":num(row.get("Open")),"high":num(row.get("High")),"low":num(row.get("Low")),"close":num(close),"volume":num(row.get("Volume"))})
    return out
def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS forecasts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, instrument TEXT NOT NULL,
        horizon TEXT NOT NULL, bias TEXT NOT NULL, rationale TEXT, source_status TEXT)""")
init_db()

@app.get("/", response_class=HTMLResponse)
def home(): return FileResponse(str(ROOT / "static" / "index.html"))
@app.get("/api/health")
def health(): return {"ok":True,"service":"DOW30 Intelligence","timestamp":now_iso(),"mode":"free-sources-best-effort"}
@app.get("/api/sources")
def sources():
    return {"sources":[
      {"name":"Yahoo Finance via yfinance","purpose":"Index/futures/ETF price history (unofficial access; may be delayed or unavailable)","free":True,"key_required":False},
      {"name":"FRED","purpose":"Selected US macro series","free":True,"key_required":True,"key_url":"https://fred.stlouisfed.org/docs/api/api_key.html"},
      {"name":"SEC EDGAR","purpose":"Official US public company filings","free":True,"key_required":False,"note":"Set SEC_USER_AGENT with app name and contact email"}
    ]}
@app.get("/api/market-snapshot")
def market_snapshot():
    result={"timestamp":now_iso(),"source":"Yahoo Finance via yfinance (unofficial)","status":"partial","markets":{},"warnings":[]}
    for name,symbol in SYMBOLS.items():
        try:
            df=history_for(symbol)
            vals=indicators(df)
            if vals.get("last") is not None:
                result["markets"][name]={"symbol":symbol,**vals,"as_of":str(df.index[-1])}
            else: result["warnings"].append(f"{name}: provider returned no usable data.")
        except Exception as e: result["warnings"].append(f"{name}: data unavailable ({type(e).__name__}).")
    result["status"]="ok" if len(result["markets"])>=4 else ("partial" if result["markets"] else "unavailable")
    return result
@app.get("/api/history")
def history(symbol: str=Query("YM=F"), period: str=Query("5d"), interval: str=Query("15m")):
    if period not in {"1d","5d","1mo","3mo","6mo","1y","2y"}: raise HTTPException(400,"Unsupported period")
    if interval not in {"5m","15m","30m","60m","1h","1d"}: raise HTTPException(400,"Unsupported interval")
    try:
        df=history_for(symbol,period,interval)
        if df.empty: return {"symbol":symbol,"status":"unavailable","bars":[],"warning":"No data returned by provider."}
        return {"symbol":symbol,"status":"ok","interval":interval,"period":period,"bars":clean_frame(df),"indicators":indicators(df),"source":"Yahoo Finance via yfinance (unofficial)"}
    except Exception as e: return {"symbol":symbol,"status":"unavailable","bars":[],"warning":f"Provider error: {type(e).__name__}"}
@app.get("/api/macro")
def macro():
    if not FRED_API_KEY:
        return {"status":"not_configured","message":"Optional free FRED API key not configured.","series":[],"setup":"Create a free key at https://fred.stlouisfed.org/docs/api/api_key.html and set FRED_API_KEY."}
    ids=["DGS2","DGS10","DTWEXBGS","DCOILWTICO"]
    rows=[]
    for sid in ids:
        try:
            r=requests.get("https://api.stlouisfed.org/fred/series/observations",params={"series_id":sid,"api_key":FRED_API_KEY,"file_type":"json","sort_order":"desc","limit":2},timeout=12)
            r.raise_for_status(); obs=r.json().get("observations",[])
            valid=[o for o in obs if o.get("value") not in (".",None)]
            rows.append({"id":sid,"date":valid[0]["date"] if valid else None,"value":num(valid[0]["value"]) if valid else None,"previous":num(valid[1]["value"]) if len(valid)>1 else None,"status":"ok" if valid else "no_data"})
        except Exception as e: rows.append({"id":sid,"status":"unavailable","error":type(e).__name__})
    return {"status":"ok","source":"FRED","series":rows,"timestamp":now_iso()}
@app.get("/api/company-filings")
def company_filings(cik: str=Query("0000320193")):
    if not SEC_USER_AGENT:
        return {"status":"not_configured","message":"SEC_USER_AGENT is not set. Set it to 'DOW30 Intelligence contact your-email@example.com'."}
    cik= str(cik).strip().lstrip("0").zfill(10)
    try:
        r=requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json",headers={"User-Agent":SEC_USER_AGENT,"Accept-Encoding":"gzip, deflate","Host":"data.sec.gov"},timeout=15)
        r.raise_for_status(); data=r.json(); rec=data.get("filings",{}).get("recent",{})
        out=[]
        for i,form in enumerate(rec.get("form",[])):
            if form in {"8-K","10-Q","10-K","6-K","20-F"}:
                accession=rec["accessionNumber"][i].replace("-","")
                out.append({"company":data.get("name"),"form":form,"date":rec["filingDate"][i],"description":rec.get("primaryDocDescription",[""]*len(rec["form"]))[i],"url":f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/{rec['primaryDocument'][i]}"})
            if len(out)>=12: break
        return {"status":"ok","cik":cik,"company":data.get("name"),"filings":out,"source":"SEC EDGAR"}
    except Exception as e: return {"status":"unavailable","error":type(e).__name__,"message":"SEC data unavailable; retry later."}
class Forecast(BaseModel):
    instrument: str="YM=F"; horizon: str="intraday"; bias: str; rationale: str=""; source_status: str="unknown"
@app.get("/api/forecast-log")
def forecast_log():
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory=sqlite3.Row
        rows=c.execute("SELECT * FROM forecasts ORDER BY id DESC LIMIT 50").fetchall()
    return {"forecasts":[dict(r) for r in rows]}
@app.post("/api/forecast-log")
def save_forecast(f: Forecast):
    with sqlite3.connect(DB_PATH) as c:
        cur=c.execute("INSERT INTO forecasts(created_at,instrument,horizon,bias,rationale,source_status) VALUES(?,?,?,?,?,?)",(now_iso(),f.instrument,f.horizon,f.bias,f.rationale,f.source_status))
        return {"saved":True,"id":cur.lastrowid}
@app.get("/api/daily-brief")
def daily_brief():
    snap=market_snapshot()
    ym=snap["markets"].get("Dow futures (YM)")
    dji=snap["markets"].get("Dow Jones")
    if not ym:
        return {"status":"unavailable","headline":"Rinkos kryptis nenustatyta","message":"Nepavyko gauti patikimų YM duomenų. Neformuojama krypties išvada.","snapshot":snap}
    change=ym.get("change_pct")
    if change is None: bias="Kryptis nepatvirtinta"
    elif change>0.15: bias="Futures teigiami, bet reikalingas patvirtinimas"
    elif change< -0.15: bias="Futures neigiami, bet reikalingas patvirtinimas"
    else: bias="Futures beveik nepakitę / mišrus vaizdas"
    return {"status":"ok","headline":bias,"message":"Tai techninis situacijos aprašymas, ne patikrinta prognozė. Tikimybių modelis dar nepatvirtintas backtestu.","ym":ym,"dji":dji,"snapshot_timestamp":snap["timestamp"],"warnings":snap["warnings"]}
