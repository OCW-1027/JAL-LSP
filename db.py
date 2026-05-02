"""SQLite 액세스 레이어."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = os.environ.get("JAL_DB_PATH",
                        str(Path(__file__).resolve().parent / "jal_lsp.db"))
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def init_db():
    """DB가 없으면 schema.sql로 초기화."""
    conn = sqlite3.connect(DB_PATH)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_setting(key: str, default=None):
    with get_conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value):
    with get_conn() as c:
        c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                  (key, str(value)))


# --- Amadeus 사용량 ---
def increment_amadeus_usage(n: int = 1):
    month = datetime.now().strftime("%Y-%m")
    with get_conn() as c:
        c.execute("INSERT OR IGNORE INTO amadeus_usage(month,call_count) VALUES(?,0)",
                  (month,))
        c.execute("UPDATE amadeus_usage SET call_count=call_count+? WHERE month=?",
                  (n, month))


def get_amadeus_usage(month: str | None = None) -> int:
    if month is None:
        month = datetime.now().strftime("%Y-%m")
    with get_conn() as c:
        row = c.execute("SELECT call_count FROM amadeus_usage WHERE month=?",
                        (month,)).fetchone()
        return row["call_count"] if row else 0


# --- Fare Cache ---
def add_fare(origin, destination, flight_date, fare_class, price_jpy,
             source="manual", confidence=2, notes=""):
    with get_conn() as c:
        c.execute("""
            INSERT INTO fare_cache(origin,destination,flight_date,fare_class,
                                   price_jpy,source,confidence,observed_at,notes)
            VALUES(?,?,?,?,?,?,?,?,?)
        """, (origin, destination, flight_date, fare_class, price_jpy,
              source, confidence, datetime.now().isoformat(timespec="seconds"),
              notes))


def get_best_fare(origin, destination, flight_date, fare_class):
    """캐시에서 가장 신뢰도 높은 운임을 반환. 없으면 None."""
    with get_conn() as c:
        # 1) 정확히 같은 날짜+클래스
        row = c.execute("""
            SELECT price_jpy, confidence, source FROM fare_cache
            WHERE origin=? AND destination=? AND flight_date=? AND fare_class=?
            ORDER BY confidence DESC, observed_at DESC LIMIT 1
        """, (origin, destination, flight_date, fare_class)).fetchone()
        if row:
            return dict(row)
        # 2) 동일 노선+클래스 평균 (같은 요일 우선)
        row = c.execute("""
            SELECT AVG(price_jpy) as price_jpy, MAX(confidence) as confidence,
                   'cache_avg' as source
            FROM fare_cache
            WHERE origin=? AND destination=? AND fare_class=?
        """, (origin, destination, fare_class)).fetchone()
        if row and row["price_jpy"]:
            return {"price_jpy": int(row["price_jpy"]),
                    "confidence": row["confidence"] or 0,
                    "source": "cache_avg"}
        return None


# --- Bookings ---
def add_booking(flight_no, origin, destination, flight_date, fare_class,
                price_jpy, pnr="", notes=""):
    with get_conn() as c:
        c.execute("""
            INSERT INTO bookings(flight_no,origin,destination,flight_date,
                                 fare_class,price_jpy,booked_at,pnr,notes)
            VALUES(?,?,?,?,?,?,?,?,?)
        """, (flight_no, origin, destination, flight_date, fare_class,
              price_jpy, datetime.now().isoformat(timespec="seconds"),
              pnr, notes))
    # 캐시에도 신뢰도 3으로 동시 등록
    add_fare(origin, destination, flight_date, fare_class, price_jpy,
             source="booking", confidence=3, notes=f"PNR:{pnr}")


# --- Schedule queries ---
def get_outbound_flights(origin, weekday_idx_1to7):
    """origin에서 출발, 해당 요일에 운항하는 모든 항공편."""
    with get_conn() as c:
        return [dict(r) for r in c.execute("""
            SELECT f.*, r.miles, r.flight_min
            FROM flights f
            LEFT JOIN routes r
              ON f.origin=r.origin AND f.destination=r.destination
            WHERE f.origin=? AND substr(f.op_days,?,1)='1'
            ORDER BY f.dep_time
        """, (origin, weekday_idx_1to7)).fetchall()]


def get_flights_between(origin, destination, weekday_idx_1to7):
    with get_conn() as c:
        return [dict(r) for r in c.execute("""
            SELECT f.*, r.miles, r.flight_min
            FROM flights f
            LEFT JOIN routes r
              ON f.origin=r.origin AND f.destination=r.destination
            WHERE f.origin=? AND f.destination=? AND substr(f.op_days,?,1)='1'
            ORDER BY f.dep_time
        """, (origin, destination, weekday_idx_1to7)).fetchall()]


def get_route(origin, destination):
    with get_conn() as c:
        row = c.execute("SELECT * FROM routes WHERE origin=? AND destination=?",
                        (origin, destination)).fetchone()
        return dict(row) if row else None


def get_all_airports():
    with get_conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM airports ORDER BY tier, code").fetchall()]


def get_base_airports():
    with get_conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM airports WHERE is_base=1 ORDER BY code").fetchall()]
