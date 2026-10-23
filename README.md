# DOW30 Intelligence — free-data MVP

## What is included
- FastAPI backend and browser dashboard.
- Best-effort market data from Yahoo Finance via `yfinance` (unofficial; can be delayed or blocked).
- Optional FRED macro series using a free API key.
- Official SEC EDGAR filings when `SEC_USER_AGENT` is configured.
- Technical diagnostic only; no fabricated quote fallback and no unvalidated forecast probabilities.
- Local SQLite forecast log endpoints.

## Run locally (Mac)
1. Install Python 3.10 or newer.
2. Unzip the project and open Terminal in the project folder.
3. Run:
   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   export SEC_USER_AGENT="DOW30 Intelligence contact your-email@example.com"
   # Optional: after creating a free key at https://fred.stlouisfed.org/docs/api/api_key.html:
   export FRED_API_KEY="your-key"
   uvicorn main:app --host 127.0.0.1 --port 8000
   ```
4. Open http://127.0.0.1:8000 in your browser. API docs: http://127.0.0.1:8000/docs

## Important
- This package has not been deployed to a public URL by generating it here. A public URL requires a hosting account and deployment.
- Static hosting alone is not enough because this app calls a Python API. Deploy the backend to a Python-capable host, and keep any FRED key in server-side environment variables, not in browser JavaScript.
- Free hosting providers may sleep, change their free tiers, or require a card/verification. Check their current terms before choosing.
- yfinance is not an official Yahoo API; availability, timestamps and terms can change.
- FRED API key is optional but useful; FRED daily series may not update intraday.
- SEC requests require a descriptive User-Agent with contact information and must respect SEC fair-access policies.
- Economic calendar, news/sentiment aggregation, backtested probabilities, scheduled morning email, authentication and persistent cloud database are not implemented yet.
