"""시각표 CSV 임포트.

CSV 형식 (헤더 필수):
    flight_no,origin,destination,dep_time,arr_time,op_days
    JAL101,HND,ITM,06:30,07:35,1111111
    ...

- op_days: 7자리 문자열, 1=운항/0=미운항. 매일 운항이면 '1111111'
- dep_time/arr_time: HH:MM 24시간 형식
"""

from __future__ import annotations
import csv
import io
import re
from typing import Iterable

from db import get_conn


TIME_RE = re.compile(r"^\d{2}:\d{2}$")
OPDAYS_RE = re.compile(r"^[01]{7}$")


def validate_row(row: dict, valid_airports: set) -> tuple[bool, str]:
    """1행 검증. (성공여부, 에러메시지)."""
    required = ["flight_no", "origin", "destination",
                "dep_time", "arr_time", "op_days"]
    for f in required:
        if not row.get(f, "").strip():
            return False, f"'{f}' 컬럼이 비어있음"

    if row["origin"] not in valid_airports:
        return False, f"알 수 없는 출발 공항: {row['origin']}"
    if row["destination"] not in valid_airports:
        return False, f"알 수 없는 도착 공항: {row['destination']}"
    if row["origin"] == row["destination"]:
        return False, "출발지와 도착지가 같음"

    if not TIME_RE.match(row["dep_time"]):
        return False, f"잘못된 dep_time 형식: {row['dep_time']} (HH:MM)"
    if not TIME_RE.match(row["arr_time"]):
        return False, f"잘못된 arr_time 형식: {row['arr_time']} (HH:MM)"

    if not OPDAYS_RE.match(row["op_days"]):
        return False, f"잘못된 op_days 형식: {row['op_days']} (7자리 0/1)"

    return True, ""


def import_csv(content: str | bytes,
               mode: str = "merge") -> dict:
    """CSV 임포트.

    mode:
        'merge' — 같은 (편명, 출발, 도착, 출발시각) 키는 덮어쓰기, 나머지 유지
        'replace_route' — 임포트되는 노선의 기존 데이터를 모두 삭제 후 추가
        'replace_all' — 모든 기존 항공편 삭제 후 추가
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")  # BOM 처리

    # 유효 공항 목록
    with get_conn() as c:
        valid_airports = {r["code"] for r in c.execute(
            "SELECT code FROM airports").fetchall()}

    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)

    if not rows:
        return {"success": False, "imported": 0,
                "errors": ["빈 CSV 또는 헤더만 있음"]}

    valid_rows = []
    errors = []
    for i, row in enumerate(rows, start=2):  # 2행부터 (1행은 헤더)
        # 공백 제거
        row = {k: (v.strip() if isinstance(v, str) else v)
               for k, v in row.items()}
        ok, msg = validate_row(row, valid_airports)
        if ok:
            valid_rows.append(row)
        else:
            errors.append(f"행 {i}: {msg}")

    if not valid_rows:
        return {"success": False, "imported": 0, "errors": errors}

    # 임포트 실행
    affected_routes = {(r["origin"], r["destination"]) for r in valid_rows}

    with get_conn() as c:
        if mode == "replace_all":
            c.execute("DELETE FROM flights")
        elif mode == "replace_route":
            # 같은 노선의 기존 항공편 삭제
            for o, d in affected_routes:
                c.execute(
                    "DELETE FROM flights WHERE origin=? AND destination=?",
                    (o, d)
                )

        # INSERT OR REPLACE: PRIMARY KEY (flight_no, origin, destination, dep_time)
        # 기준으로 중복 시 덮어쓰기
        c.executemany("""
            INSERT OR REPLACE INTO flights
                (flight_no, origin, destination, dep_time, arr_time, op_days)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [(r["flight_no"], r["origin"], r["destination"],
               r["dep_time"], r["arr_time"], r["op_days"])
              for r in valid_rows])

    return {
        "success": True,
        "imported": len(valid_rows),
        "errors": errors,
        "routes_affected": len(affected_routes),
    }


def import_csv_file(filepath: str, mode: str = "merge") -> dict:
    """파일에서 CSV 임포트."""
    with open(filepath, "rb") as f:
        return import_csv(f.read(), mode=mode)


def routes_with_data() -> list[dict]:
    """현재 데이터가 있는 노선 목록 + 편수."""
    with get_conn() as c:
        return [dict(r) for r in c.execute("""
            SELECT origin, destination, COUNT(*) as flight_count
            FROM flights
            GROUP BY origin, destination
            ORDER BY origin, destination
        """).fetchall()]
