"""
main.py — FastAPI entry point.
Run with: uvicorn main:app --reload --port 8000
"""

from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
import asyncio
import io
import queue as _queue
import shutil
import sys
import tempfile
import threading

from database import init_db
from parser import parse_and_import
from enricher import enrich_all
from analytics import (
    get_positions,
    get_summary,
    get_portfolio_evolution,
    get_geo_allocation,
    get_sector_allocation,
    get_etf_evolution,
    get_etf_price_history,
    get_etf_transactions,
    get_allocation_detail,
    get_period_performance,
    get_metrics,
    get_benchmark_comparison,
)

app = FastAPI(title="Portfolio Tracker", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
FRONTEND_DIR = Path(__file__).parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.on_event("startup")
def startup():
    init_db()
    print("[SERVER] Portfolio tracker ready at http://localhost:8000")


@app.get("/")
def root():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


# ─── Data import ──────────────────────────────────────────────────────────────

@app.post("/api/import")
async def import_csv(file: UploadFile = File(...)):
    """Upload a Trade Republic CSV and import transactions."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files are accepted")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    result = parse_and_import(tmp_path)
    return result


@app.post("/api/enrich")
def enrich(force: bool = False):
    enrich_all(force=force)
    return {"status": "ok"}


@app.post("/api/enrich/stream")
async def enrich_stream(force: bool = False):
    """Stream enrichment logs line by line via Server-Sent Events."""
    log_q: _queue.Queue = _queue.Queue()

    class _LogCapture(io.TextIOBase):
        def __init__(self, q: _queue.Queue, fallback):
            self._q = q
            self._fb = fallback
            self._buf = ""

        def write(self, s: str) -> int:
            self._fb.write(s)
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                if line.strip():
                    self._q.put(line.strip())
            return len(s)

        def flush(self):
            if self._buf.strip():
                self._q.put(self._buf.strip())
                self._buf = ""
            self._fb.flush()

    original_stdout = sys.stdout

    def _run():
        sys.stdout = _LogCapture(log_q, original_stdout)
        try:
            enrich_all(force=force)
        except Exception as exc:
            log_q.put(f"[ERREUR] {exc}")
        finally:
            sys.stdout = original_stdout
            log_q.put(None)  # sentinel

    threading.Thread(target=_run, daemon=True).start()

    loop = asyncio.get_event_loop()

    async def _event_gen():
        while True:
            try:
                line = await loop.run_in_executor(None, lambda: log_q.get(timeout=300))
            except _queue.Empty:
                yield "data: [TIMEOUT]\n\n"
                break
            if line is None:
                yield "data: [DONE]\n\n"
                break
            yield f"data: {line}\n\n"

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── Analytics endpoints ──────────────────────────────────────────────────────

@app.get("/api/summary")
def summary():
    return get_summary()


@app.get("/api/positions")
def positions():
    return get_positions()


@app.get("/api/evolution")
def evolution():
    return get_portfolio_evolution()


@app.get("/api/evolution/{isin}")
def etf_evolution(isin: str):
    return get_etf_evolution(isin)


@app.get("/api/price/{isin}")
def etf_price(isin: str, period: str = "1y"):
    return get_etf_price_history(isin, period)


@app.get("/api/transactions/{isin}")
def etf_transactions(isin: str):
    return get_etf_transactions(isin)


@app.get("/api/performance")
def period_performance(period: str = "ytd"):
    return get_period_performance(period)


@app.get("/api/metrics")
def metrics():
    return get_metrics()


@app.get("/api/benchmark")
def benchmark(period: str = "max"):
    return get_benchmark_comparison(period)


@app.get("/api/allocation/detail")
def allocation_detail(type: str, name: str):
    return get_allocation_detail(type, name)


@app.get("/api/geo")
def geo():
    return get_geo_allocation()


@app.get("/api/sectors")
def sectors():
    return get_sector_allocation()
