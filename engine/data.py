"""data/ の CSV をメモリに読み込む (DB不要)."""
from __future__ import annotations
import csv, json
from datetime import date
from functools import lru_cache
from pathlib import Path
from .miles import route_miles

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def load_meta() -> dict:
    p = DATA_DIR / "meta.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


@lru_cache(maxsize=1)
def _load_all() -> dict[str, dict[str, list[dict]]]:
    """{date: {origin: [flight dict, ...]}}"""
    idx: dict[str, dict[str, list[dict]]] = {}
    p = DATA_DIR / "flights_by_date.csv"
    if not p.exists():
        return idx
    with open(p, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            m, est = route_miles(r["origin"], r["destination"])
            rec = dict(flight_no=r["flight_no"], origin=r["origin"], destination=r["destination"],
                       dep_time=r["dep_time"], arr_time=r["arr_time"], miles=m, miles_est=est)
            idx.setdefault(r["date"], {}).setdefault(r["origin"], []).append(rec)
    for d in idx.values():
        for lst in d.values():
            lst.sort(key=lambda x: x["dep_time"])
    return idx


def flights_by_origin(d: date) -> dict[str, list[dict]]:
    return _load_all().get(d.isoformat(), {})


def available_dates() -> list[str]:
    return sorted(_load_all().keys())


def airports() -> list[str]:
    names = load_meta().get("airport_names", {})
    return sorted(names.keys())


def airport_label(code: str) -> str:
    names = load_meta().get("airport_names", {})
    return f"{code} - {names.get(code, code)}"


def reload():
    load_meta.cache_clear()
    _load_all.cache_clear()
