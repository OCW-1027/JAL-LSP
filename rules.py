"""JAL 규칙 및 상수.

- LSP: 적립 대상 운임 1탑승당 5포인트
- FOP: 구간마일 × 적립률 × 2 + 운임 보너스
- MCT: 동일공항 환승 최소시간
"""

# 동일공항 국내선 환승 최소연결시간 (분)
MCT = {"HND": 30, "OKA": 30}
DEFAULT_MCT = 20

# 보안검색 마감 (출발 N분 전)
SECURITY_DEADLINE_BEFORE = 20
GATE_DEADLINE_BEFORE = 10
BAGGAGE_CHECK_BEFORE = 30

# 안전 버퍼 (분) - 공식 MCT에 추가로 더해서 권장 환승시간 산출
SAFETY_BUFFER = 10

LSP_PER_SEGMENT = 5

# 운임 클래스: 마일 적립률, FOP 보너스
FARE_CLASSES = {
    "Flex":         {"mile_rate": 1.00, "fop_bonus": 400, "label": "Flex (변경가)"},
    "Saver":        {"mile_rate": 0.75, "fop_bonus": 200, "label": "Saver"},
    "SpecialSaver": {"mile_rate": 0.75, "fop_bonus": 200, "label": "Special Saver"},
    "Promo":        {"mile_rate": 0.50, "fop_bonus": 0,   "label": "Promotion"},
}

# 패턴별 시간창
PATTERNS = {
    "day":  {"days": 1, "label": "당일치기",     "start_hour": 6, "end_hour": 22},
    "1n2d": {"days": 2, "label": "1박 2일",     "start_hour": 6, "end_hour": 22},
    "2n3d": {"days": 3, "label": "2박 3일",     "start_hour": 6, "end_hour": 22},
}

# 외박지 평균 1박 비용 (대도시 비즈니스호텔 기준, 만엔 단위 미사용)
OVERNIGHT_COST_DEFAULT = 12000  # 엔
OVERNIGHT_COST_BY_CITY = {
    "OKA": 13000, "ISG": 18000, "MMY": 18000,
    "ITM": 14000, "KIX": 14000, "NGO": 12000,
    "FUK": 13000, "CTS": 12000, "HIJ": 11000,
    "OKJ": 10000, "KMQ": 11000, "TOY": 10000,
    "AKT": 10000, "AOJ": 10000, "MYJ": 10000,
    "TAK": 10000, "KOJ": 11000, "KMI": 10000,
    "OIT": 10000, "NGS": 11000, "MMB": 10000,
    "HKD": 12000,
}


def get_mct(airport: str) -> int:
    """동일공항 환승 최소연결시간 (분)."""
    return MCT.get(airport, DEFAULT_MCT)


def safe_mct(airport: str) -> int:
    """공식 MCT + 안전 버퍼."""
    return get_mct(airport) + SAFETY_BUFFER


def fop_per_segment(miles: int, fare_class: str) -> int:
    """1세그먼트 FOP 추정 (구간마일 × 적립률 × 2 + 보너스)."""
    fc = FARE_CLASSES[fare_class]
    return int(miles * fc["mile_rate"] * 2 + fc["fop_bonus"])


def overnight_cost(airport: str) -> int:
    return OVERNIGHT_COST_BY_CITY.get(airport, OVERNIGHT_COST_DEFAULT)
