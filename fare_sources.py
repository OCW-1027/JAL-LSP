"""운임 정보 소스: JAL/Google Flights 딥링크 + Amadeus API.

- JAL/Google Flights는 무료 (검색 페이지 prefill URL만 생성)
- Amadeus는 무료 한도 월 2,000콜, 체크박스 활성화 시에만 호출
"""

from __future__ import annotations
from urllib.parse import urlencode, quote
from datetime import date, datetime
from typing import Optional

from db import (get_setting, set_setting,
                increment_amadeus_usage, get_amadeus_usage,
                add_fare)


# ===== Deep Link 생성 =====
def jal_search_url(origin: str, destination: str, flight_date: date,
                   adults: int = 1) -> str:
    """JAL 국내선 예약 페이지 (메인).

    JAL 일본 사이트는 외부 prefill을 안정적으로 받지 않아,
    안정적인 메인 예약 페이지로 보냅니다. 사용자가 출발지·도착지·날짜를
    직접 선택해야 합니다 (10초 정도).
    """
    return get_setting(
        "jal_url_template",
        "https://www.jal.co.jp/jp/ja/dom/"
    )


def jal_timetable_url(origin: str, destination: str) -> str:
    """JAL 노선별 시각표 페이지."""
    return f"https://www.jal.co.jp/jp/ja/dom/route/{origin.lower()}_{destination.lower()}/"


def google_flights_url(origin: str, destination: str, flight_date: date) -> str:
    """Google Flights 검색 페이지 딥링크 (q= 형식, 가장 단순)."""
    q = f"Flights from {origin} to {destination} on {flight_date.isoformat()}"
    return f"https://www.google.com/travel/flights?{urlencode({'q': q})}"


# ===== Amadeus API =====
class AmadeusClient:
    def __init__(self, client_id: str, client_secret: str,
                 hostname: str = "production"):
        try:
            from amadeus import Client
        except ImportError:
            raise RuntimeError(
                "amadeus 패키지가 설치되지 않았습니다. "
                "`pip install amadeus`를 실행해주세요."
            )
        self.client = Client(
            client_id=client_id,
            client_secret=client_secret,
            hostname=hostname  # 'test' 또는 'production'
        )

    def cheapest_offer(self, origin: str, destination: str,
                       flight_date: date, adults: int = 1,
                       currency: str = "JPY") -> Optional[dict]:
        """가장 싼 항공권 1건 조회. 호출 1회당 카운터 1 증가."""
        try:
            resp = self.client.shopping.flight_offers_search.get(
                originLocationCode=origin,
                destinationLocationCode=destination,
                departureDate=flight_date.isoformat(),
                adults=adults,
                currencyCode=currency,
                max=5,
            )
            increment_amadeus_usage(1)
            offers = resp.data
            if not offers:
                return None
            cheapest = min(offers,
                           key=lambda o: float(o["price"]["grandTotal"]))
            return {
                "price": float(cheapest["price"]["grandTotal"]),
                "currency": cheapest["price"]["currency"],
                "carrier": cheapest["validatingAirlineCodes"][0]
                if cheapest.get("validatingAirlineCodes") else "?",
                "raw": cheapest,
            }
        except Exception as e:
            return {"error": str(e)}


def fetch_amadeus_price(origin: str, destination: str, flight_date: date,
                        client_id: str, client_secret: str,
                        save_to_cache: bool = True,
                        fare_class: str = "Saver") -> Optional[dict]:
    """Amadeus 가격 조회 + 캐시 저장.

    이 함수는 호출 시점에 1회 카운터 증가합니다. 사용 전 한도 확인 필요.
    """
    cli = AmadeusClient(client_id, client_secret, hostname="production")
    result = cli.cheapest_offer(origin, destination, flight_date)
    if not result or "error" in (result or {}):
        return result

    price_jpy = int(result["price"])
    if save_to_cache:
        add_fare(origin, destination, flight_date.isoformat(),
                 fare_class, price_jpy,
                 source="amadeus", confidence=1,
                 notes=f"carrier={result.get('carrier','?')}")
    return {**result, "price_jpy": price_jpy}


def amadeus_quota_status(monthly_limit: int = 2000) -> dict:
    """월 사용량 / 한도 / 잔여 / 경고."""
    used = get_amadeus_usage()
    remaining = monthly_limit - used
    pct = (used / monthly_limit * 100) if monthly_limit else 0
    if pct >= 100:
        level = "blocked"
    elif pct >= 80:
        level = "warn"
    else:
        level = "ok"
    return {
        "used": used, "limit": monthly_limit,
        "remaining": remaining, "pct": round(pct, 1),
        "level": level,
    }
