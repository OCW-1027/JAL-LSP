"""루트 최적화 엔진 (체인 검색 버전).

목표: LSP 최대화 (효율은 보조)
패턴: 당일 / 1박2일 / 2박3일

핵심 알고리즘: 일반 체인 DFS
  - 동일 base에서 출발해 동일 base로 귀환하는 모든 비행 시퀀스
  - 환승 도시 자유롭게 (예: HND→KMQ→OKA→ISG→KIX→HND)
  - MCT, 시간 윈도우, 재방문 제한 등 제약 적용

성능: time_budget_sec로 검색 시간 상한 설정.
"""

from __future__ import annotations
import time as _time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from db import (get_conn, get_best_fare)
from rules import (LSP_PER_SEGMENT, fop_per_segment, safe_mct,
                   overnight_cost, FARE_CLASSES, PATTERNS)


# 모듈 레벨 운임 조회 캐시 (한 번의 검색 동안만 유효)
_FARE_LOOKUP_CACHE: dict = {}


def _to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _weekday_idx(d: date) -> int:
    """월=1 ... 일=7."""
    return d.isoweekday()


@dataclass
class Segment:
    flight_no: str
    origin: str
    destination: str
    dep_time: str
    arr_time: str
    flight_date: date
    miles: int
    flight_min: int

    @property
    def dep_min(self) -> int:
        return _to_min(self.dep_time)

    @property
    def arr_min(self) -> int:
        return _to_min(self.arr_time)


@dataclass
class Route:
    segments: list[Segment] = field(default_factory=list)
    pattern: str = "day"
    overnight_cities: list[str] = field(default_factory=list)
    lsp: int = 0
    fop: int = 0
    miles: int = 0
    price: int = 0          # 참고용 추정치 (실제 가격 아님)
    fare_class: str = "Saver"
    score: float = 0.0
    confidence: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def num_segments(self) -> int:
        return len(self.segments)

    @property
    def num_airports(self) -> int:
        ap = set()
        for s in self.segments:
            ap.add(s.origin)
            ap.add(s.destination)
        return len(ap)

    @property
    def total_minutes(self) -> int:
        if not self.segments:
            return 0
        first = self.segments[0]
        last = self.segments[-1]
        days = (last.flight_date - first.flight_date).days
        return days * 24 * 60 + (last.arr_min - first.dep_min)


# =====================================================================
# DB 캐싱
# =====================================================================

def _flights_by_origin_cache(flight_date: date) -> dict[str, list[dict]]:
    """해당 날짜에 운항하는 모든 항공편을 출발공항별로 인덱싱."""
    wd = _weekday_idx(flight_date)
    cache: dict = {}
    with get_conn() as c:
        rows = c.execute("""
            SELECT f.flight_no, f.origin, f.destination,
                   f.dep_time, f.arr_time,
                   r.miles, r.flight_min
            FROM flights f
            LEFT JOIN routes r
              ON f.origin=r.origin AND f.destination=r.destination
            WHERE substr(f.op_days, ?, 1)='1'
              AND r.miles IS NOT NULL
            ORDER BY f.origin, f.dep_time
        """, (wd,)).fetchall()
    for r in rows:
        cache.setdefault(r["origin"], []).append(dict(r))
    return cache


def _flight_to_segment(f: dict, flight_date: date) -> Segment:
    return Segment(
        flight_no=f["flight_no"],
        origin=f["origin"],
        destination=f["destination"],
        dep_time=f["dep_time"],
        arr_time=f["arr_time"],
        flight_date=flight_date,
        miles=f["miles"],
        flight_min=f["flight_min"] or 60,
    )


# =====================================================================
# 가격 / 점수
# =====================================================================

def estimate_price(segments: list[Segment], fare_class: str
                   ) -> tuple[int, int]:
    """세그먼트별 운임 합산. (가격, 평균신뢰도). 참고용 추정치."""
    total = 0
    confidences = []
    for s in segments:
        key = (s.origin, s.destination, s.flight_date.isoformat(), fare_class)
        if key not in _FARE_LOOKUP_CACHE:
            _FARE_LOOKUP_CACHE[key] = get_best_fare(*key)
        f = _FARE_LOOKUP_CACHE[key]
        if f:
            total += f["price_jpy"]
            confidences.append(f["confidence"])
        else:
            total += s.miles * 30
            confidences.append(0)
    avg_conf = min(confidences) if confidences else 0
    return total, avg_conf


def clear_fare_cache():
    _FARE_LOOKUP_CACHE.clear()


def score_route(segments: list[Segment], fare_class: str = "Saver",
                overnight_cities: list[str] = None) -> Route:
    """LSP 우선 점수.

    score = LSP*1000 + airports*10 + miles/100
    (가격은 점수에 영향 없음 — 참고용)
    """
    overnight_cities = overnight_cities or []
    lsp = len(segments) * LSP_PER_SEGMENT
    miles = sum(s.miles for s in segments)
    fop = sum(fop_per_segment(s.miles, fare_class) for s in segments)
    flight_price, conf = estimate_price(segments, fare_class)
    hotel_price = sum(overnight_cost(c) for c in overnight_cities)
    total_price = flight_price + hotel_price

    airports = set()
    for s in segments:
        airports.add(s.origin)
        airports.add(s.destination)

    score = lsp * 1000 + len(airports) * 10 + miles / 100

    return Route(
        segments=segments,
        overnight_cities=overnight_cities,
        lsp=lsp, fop=fop, miles=miles,
        price=total_price, fare_class=fare_class,
        score=score, confidence=conf,
    )


# =====================================================================
# 핵심: 체인 DFS
# =====================================================================

def _generate_chains(start_airport: str, end_airport: Optional[str],
                     flight_date: date, flight_cache: dict,
                     min_segments: int, max_segments: int,
                     time_start_min: int = 6 * 60,
                     time_end_min: int = 22 * 60,
                     max_revisits: int = 5,
                     top_n: int = 50,
                     time_budget_sec: float = 2.0,
                     force_first_dest: Optional[str] = None,
                     allowed_airports: Optional[set[str]] = None
                     ) -> list[list[dict]]:
    """체인 검색 DFS.

    force_first_dest: 첫 비행의 도착지를 고정 (다양성 보장용).
    allowed_airports: None이면 모든 공항 허용. 지정 시 이 set 안의 공항만 사용.
                      start_airport와 end_airport는 자동으로 포함됨.
    """
    chains: list[list[dict]] = []
    seen_sigs: set = set()
    start_time = _time.time()
    path: list[dict] = []

    if min_segments == 0 and (end_airport is None or end_airport == start_airport):
        chains.append([])
        seen_sigs.add((start_airport,))

    def dfs(current_airport: str, current_time: int):
        if _time.time() - start_time > time_budget_sec:
            return
        if len(chains) >= top_n * 4:
            return

        valid_ending = (
            (end_airport is None or current_airport == end_airport)
            and len(path) >= max(1, min_segments)
        )
        if valid_ending:
            sig = tuple([path[0]["origin"]] +
                        [f["destination"] for f in path])
            if sig not in seen_sigs:
                seen_sigs.add(sig)
                chains.append(list(path))

        if len(path) >= max_segments:
            return

        mct = safe_mct(current_airport) if path else 0
        min_dep = current_time + mct

        flights_to_try = flight_cache.get(current_airport, [])
        # 루트에서 첫 도시를 강제 (다양성 보장)
        if not path and force_first_dest is not None:
            flights_to_try = [f for f in flights_to_try
                              if f["destination"] == force_first_dest]

        for f in flights_to_try:
            dep_min = _to_min(f["dep_time"])
            if dep_min < min_dep:
                continue
            arr_min = _to_min(f["arr_time"])
            if arr_min > time_end_min:
                continue

            next_airport = f["destination"]

            # 조합 공항 제한 (allowed_airports)
            if allowed_airports is not None:
                if next_airport not in allowed_airports:
                    continue

            next_visit_count = sum(1 for ff in path
                                    if ff["destination"] == next_airport)
            if next_visit_count >= max_revisits:
                continue

            path.append(f)
            dfs(next_airport, arr_min)
            path.pop()

    dfs(start_airport, time_start_min)

    chains.sort(key=lambda c: (-len(c), -sum(f["miles"] for f in c)))
    return chains[:top_n]


# =====================================================================
# 패턴별 검색
# =====================================================================

def search_day_chains(bases: list[str], flight_date: date,
                      fare_class: str = "Saver",
                      min_segments: int = 2, max_segments: int = 8,
                      top_n: int = 30,
                      time_start_min: int = 6 * 60,
                      time_end_min: int = 22 * 60,
                      time_budget_sec: float = 4.0,
                      allowed_airports: Optional[set[str]] = None
                      ) -> list[Route]:
    """당일치기 체인 검색. 첫 도시별로 따로 탐색해 다양성 보장."""
    flights = _flights_by_origin_cache(flight_date)
    all_chains = []

    # 베이스가 allowed에 없으면 자동으로 추가 (시작/종료 공항)
    effective_allowed = None
    if allowed_airports is not None:
        effective_allowed = set(allowed_airports) | set(bases)

    for base in bases:
        valid_first_dests = []
        seen_dest = set()
        for f in flights.get(base, []):
            dep_min = _to_min(f["dep_time"])
            if dep_min < time_start_min:
                continue
            arr_min = _to_min(f["arr_time"])
            if arr_min > time_end_min:
                continue
            if effective_allowed is not None and f["destination"] not in effective_allowed:
                continue
            if f["destination"] not in seen_dest:
                seen_dest.add(f["destination"])
                valid_first_dests.append(f["destination"])

        if not valid_first_dests:
            continue

        per_dest_budget = max(time_budget_sec / max(len(bases), 1)
                               / max(len(valid_first_dests), 1), 0.3)
        per_dest_top = max(top_n // max(len(valid_first_dests), 1), 3)

        for first_dest in valid_first_dests:
            chains = _generate_chains(
                base, base, flight_date, flights,
                min_segments=min_segments, max_segments=max_segments,
                time_start_min=time_start_min, time_end_min=time_end_min,
                top_n=per_dest_top, time_budget_sec=per_dest_budget,
                force_first_dest=first_dest,
                allowed_airports=effective_allowed,
            )
            all_chains.extend(chains)

    routes = []
    for chain in all_chains:
        segs = [_flight_to_segment(f, flight_date) for f in chain]
        r = score_route(segs, fare_class)
        r.pattern = "day"
        routes.append(r)

    routes.sort(key=lambda r: -r.score)
    return routes[:top_n * 3]


def search_overnight_chains(bases: list[str], start_date: date, nights: int,
                            fare_class: str = "Saver",
                            min_segments: int = 3, max_segments: int = 12,
                            top_n: int = 30,
                            time_budget_sec: float = 8.0,
                            allowed_airports: Optional[set[str]] = None
                            ) -> list[Route]:
    """1박2일 / 2박3일 체인 검색.

    1박2일: D1 base→Y, D2 Y→base
    2박3일: D1 base→Y, D2 Y→Z (또는 머무름), D3 Z→base
    """
    days = [start_date + timedelta(days=i) for i in range(nights + 1)]
    flight_caches = {d: _flights_by_origin_cache(d) for d in days}

    # 일자당 최대 세그먼트: 단순 분배가 아니라 max_segments까지 가능 (시간 한계는 자연 제약)
    # 단, 한 일자에 너무 몰리는 걸 방지하기 위해 max_segments-1 상한
    per_day_max = min(max_segments - 1, 8) if nights >= 1 else max_segments
    per_day_max = max(per_day_max, 2)
    per_search_budget = max(time_budget_sec / 8, 0.3)

    routes = []
    seen = set()
    overall_start = _time.time()

    # 베이스를 allowed에 자동 포함
    effective_allowed = None
    if allowed_airports is not None:
        effective_allowed = set(allowed_airports) | set(bases)

    for base in bases:
        if _time.time() - overall_start > time_budget_sec:
            break

        # D1: 첫 목적지별로 분산 탐색 (다양성 보장)
        valid_d1_first_dests = []
        seen_dest = set()
        for f in flight_caches[days[0]].get(base, []):
            if (_to_min(f["dep_time"]) >= 6 * 60
                    and _to_min(f["arr_time"]) <= 22 * 60):
                if effective_allowed is not None and f["destination"] not in effective_allowed:
                    continue
                if f["destination"] not in seen_dest and f["destination"] != base:
                    seen_dest.add(f["destination"])
                    valid_d1_first_dests.append(f["destination"])

        d1_chains = []
        for first_dest in valid_d1_first_dests:
            sub_chains = _generate_chains(
                base, None, days[0], flight_caches[days[0]],
                min_segments=1, max_segments=per_day_max,
                top_n=5, time_budget_sec=per_search_budget,
                force_first_dest=first_dest,
                allowed_airports=effective_allowed,
            )
            d1_chains.extend(sub_chains)

        for d1 in d1_chains:
            if _time.time() - overall_start > time_budget_sec:
                break
            if not d1:
                continue
            y = d1[-1]["destination"]
            if y == base:
                continue

            if nights == 1:
                last_chains = _generate_chains(
                    y, base, days[1], flight_caches[days[1]],
                    min_segments=1, max_segments=per_day_max,
                    top_n=10, time_budget_sec=per_search_budget,
                    allowed_airports=effective_allowed,
                )
                for dl in last_chains:
                    if not dl:
                        continue
                    full = d1 + dl
                    sig = tuple([full[0]["origin"]] +
                                [f["destination"] for f in full])
                    if sig in seen:
                        continue
                    seen.add(sig)
                    segs = ([_flight_to_segment(f, days[0]) for f in d1] +
                            [_flight_to_segment(f, days[1]) for f in dl])
                    r = score_route(segs, fare_class, overnight_cities=[y])
                    r.pattern = "1n2d"
                    routes.append(r)

            elif nights == 2:
                d2_chains = _generate_chains(
                    y, None, days[1], flight_caches[days[1]],
                    min_segments=0, max_segments=per_day_max,
                    top_n=8, time_budget_sec=per_search_budget,
                    allowed_airports=effective_allowed,
                )
                for d2 in d2_chains:
                    if _time.time() - overall_start > time_budget_sec:
                        break
                    z = d2[-1]["destination"] if d2 else y
                    last_chains = _generate_chains(
                        z, base, days[2], flight_caches[days[2]],
                        min_segments=1, max_segments=per_day_max,
                        top_n=8, time_budget_sec=per_search_budget,
                        allowed_airports=effective_allowed,
                    )
                    for dl in last_chains:
                        if not dl:
                            continue
                        full = d1 + d2 + dl
                        sig = tuple([full[0]["origin"]] +
                                    [f["destination"] for f in full])
                        if sig in seen:
                            continue
                        seen.add(sig)
                        segs = (
                            [_flight_to_segment(f, days[0]) for f in d1] +
                            [_flight_to_segment(f, days[1]) for f in d2] +
                            [_flight_to_segment(f, days[2]) for f in dl]
                        )
                        cities = [y, z if z != y else y]
                        r = score_route(segs, fare_class,
                                        overnight_cities=cities)
                        r.pattern = "2n3d"
                        routes.append(r)

    routes = [r for r in routes if r.num_segments >= min_segments]
    routes.sort(key=lambda r: -r.score)
    return routes[:top_n]


def _diversify_routes(routes: list[Route], max_per_first_dest: int = 2
                      ) -> list[Route]:
    """첫 번째 방문 도시별로 다양성 보장.

    같은 첫 도시(예: 모두 KMJ로 시작)인 결과가 max_per_first_dest개를 넘으면
    뒤로 밀어내고, 다른 첫 도시 결과를 우선 보여줌.
    """
    by_first: dict = {}
    primary = []
    overflow = []
    for r in routes:
        if not r.segments:
            continue
        first_dest = r.segments[0].destination
        if by_first.get(first_dest, 0) < max_per_first_dest:
            primary.append(r)
            by_first[first_dest] = by_first.get(first_dest, 0) + 1
        else:
            overflow.append(r)
    return primary + overflow


def search_routes(bases: list[str], start_date: date, end_date: date,
                  pattern: str, fare_class: str = "Saver",
                  min_segments: int = 2,
                  max_segments: int = 8,
                  top_n: int = 30,
                  time_budget_sec: float = 6.0,
                  diversify: bool = True,
                  max_per_first_dest: int = 2,
                  must_include: Optional[list[str]] = None,
                  allowed_airports: Optional[list[str]] = None
                  ) -> list[Route]:
    """기간 내 모든 출발일 검색.

    must_include: 루트가 반드시 거쳐야 할 공항 리스트. 모두 포함된 루트만 통과.
    allowed_airports: 비행에 사용할 수 있는 공항 풀. None이면 전체 허용.
                     베이스 공항은 자동으로 포함됨.
    diversify=True면 첫 번째 방문 도시별로 max_per_first_dest개씩만 상위에 노출
    (한 도시에 결과 쏠림 방지).
    """
    clear_fare_cache()

    allowed_set: Optional[set[str]] = None
    if allowed_airports:
        allowed_set = set(allowed_airports) | set(bases)

    must_set: Optional[set[str]] = None
    if must_include:
        must_set = set(must_include)

    all_routes = []
    cur = start_date
    while cur <= end_date:
        if pattern == "day":
            all_routes.extend(search_day_chains(
                bases, cur, fare_class,
                min_segments=min_segments, max_segments=max_segments,
                top_n=top_n * 3,
                time_budget_sec=min(time_budget_sec, 4.0),
                allowed_airports=allowed_set,
            ))
        elif pattern == "1n2d":
            if cur + timedelta(days=1) <= end_date:
                all_routes.extend(search_overnight_chains(
                    bases, cur, 1, fare_class,
                    min_segments=min_segments, max_segments=max_segments,
                    top_n=top_n * 3,
                    time_budget_sec=min(time_budget_sec, 6.0),
                    allowed_airports=allowed_set,
                ))
        elif pattern == "2n3d":
            if cur + timedelta(days=2) <= end_date:
                all_routes.extend(search_overnight_chains(
                    bases, cur, 2, fare_class,
                    min_segments=min_segments, max_segments=max_segments,
                    top_n=top_n * 3,
                    time_budget_sec=min(time_budget_sec, 8.0),
                    allowed_airports=allowed_set,
                ))
        cur += timedelta(days=1)

    # must_include 필터: 루트가 지정된 공항을 모두 포함해야 함
    if must_set:
        def has_all(r: Route) -> bool:
            visited = set()
            for s in r.segments:
                visited.add(s.origin)
                visited.add(s.destination)
            return must_set.issubset(visited)
        all_routes = [r for r in all_routes if has_all(r)]

    all_routes.sort(key=lambda r: -r.score)
    if diversify:
        all_routes = _diversify_routes(all_routes, max_per_first_dest)
    return all_routes[:top_n]


def route_to_dict(r: Route) -> dict:
    """결과 표시용 dict 변환."""
    if r.segments:
        path_parts = [r.segments[0].origin]
        for i, s in enumerate(r.segments):
            if i > 0 and s.flight_date != r.segments[i - 1].flight_date:
                path_parts.append("🌙")
            path_parts.append(s.destination)
        route_str = " → ".join(path_parts)
    else:
        route_str = ""

    return {
        "pattern": (PATTERNS[r.pattern]["label"]
                    if r.pattern in PATTERNS else r.pattern),
        "date": (r.segments[0].flight_date.isoformat()
                 if r.segments else ""),
        "segments": r.num_segments,
        "airports": r.num_airports,
        "lsp": r.lsp,
        "fop": r.fop,
        "miles": r.miles,
        "price_jpy": r.price,
        "fare_class": r.fare_class,
        "score": round(r.score, 2),
        "confidence": r.confidence,
        "route": route_str,
        "details": [
            {
                "flight_no": s.flight_no,
                "origin": s.origin,
                "destination": s.destination,
                "dep": f"{s.flight_date.isoformat()} {s.dep_time}",
                "arr": f"{s.flight_date.isoformat()} {s.arr_time}",
                "miles": s.miles,
            } for s in r.segments
        ],
    }
