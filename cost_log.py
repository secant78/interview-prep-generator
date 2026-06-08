"""
Persistent cost log — one JSON record per API-incurring run.
Stored as .costs_log.json next to the app; survives restarts.
"""

import json
import threading
from datetime import datetime
from pathlib import Path

COSTS_LOG_PATH = Path(__file__).parent / ".costs_log.json"
_write_lock = threading.Lock()


def load_cost_log() -> list[dict]:
    if not COSTS_LOG_PATH.exists():
        return []
    try:
        data = json.loads(COSTS_LOG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def append_cost_record(record: dict) -> None:
    with _write_lock:
        log = load_cost_log()
        log.append(record)
        COSTS_LOG_PATH.write_text(json.dumps(log, indent=2), encoding="utf-8")


def build_record(
    tab: str,
    tracker,
    company: str = "",
    extra: dict | None = None,
) -> dict:
    """Serialize a CostTracker into a loggable dict."""
    rates = tracker.pricing
    calls = []
    for label, inp, out in tracker.calls:
        call_cost = (
            inp / 1_000_000 * rates["input"]
            + out / 1_000_000 * rates["output"]
        )
        calls.append(
            {
                "label": label,
                "input_tokens": inp,
                "output_tokens": out,
                "cost": round(call_cost, 6),
            }
        )
    record = {
        "timestamp": datetime.now().isoformat(),
        "tab": tab,
        "company": company,
        "model": tracker.model,
        "total_cost": round(tracker.total_cost, 6),
        "input_tokens": tracker.input_tokens,
        "output_tokens": tracker.output_tokens,
        "calls": calls,
    }
    if extra:
        record.update(extra)
    return record
