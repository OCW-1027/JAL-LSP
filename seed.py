"""시드 데이터: 공항·노선·항공편 기본 데이터.

⚠️  스케줄은 대표값으로 자동 생성된 것으로, 실제 JAL 월간 시각표와는
    차이가 있을 수 있습니다. 발권 전 반드시 JAL 공식에서 재확인하세요.
    매월 갱신을 원하시면 `routes` 데이터의 daily_freq만 조정하면 됩니다.
"""

from db import init_db, get_conn

# --- 공항 마스터 ---
# is_base: 8개 베이스 출발공항
# tier: 1=고빈도/주요 (HND발 단거리 등), 2=중간, 3=저빈도
AIRPORTS = [
    # 베이스 8개
    ("HND", "도쿄(하네다)",     "東京(羽田)",       "Kanto",    1, 1),
    ("NRT", "도쿄(나리타)",     "東京(成田)",       "Kanto",    1, 1),
    ("ITM", "오사카(이타미)",   "大阪(伊丹)",       "Kansai",   1, 1),
    ("KIX", "오사카(간사이)",   "大阪(関西)",       "Kansai",   1, 1),
    ("NGO", "나고야(중부)",     "名古屋(中部)",     "Chubu",    1, 1),
    ("FUK", "후쿠오카",         "福岡",             "Kyushu",   1, 1),
    ("CTS", "삿포로(신치토세)", "札幌(新千歳)",     "Hokkaido", 1, 1),
    ("OKA", "오키나와(나하)",   "沖縄(那覇)",       "Okinawa",  1, 1),
    # Tier 1 (HND발 고빈도 단거리)
    ("HIJ", "히로시마",         "広島",             "Chugoku",  0, 1),
    ("KMQ", "고마쓰",           "小松",             "Hokuriku", 0, 1),
    ("OKJ", "오카야마",         "岡山",             "Chugoku",  0, 1),
    # Tier 2 (HND발 또는 거점공항 발 중간빈도)
    ("MYJ", "마쓰야마",         "松山",             "Shikoku",  0, 2),
    ("TAK", "다카마쓰",         "高松",             "Shikoku",  0, 2),
    ("AKT", "아키타",           "秋田",             "Tohoku",   0, 2),
    ("AOJ", "아오모리",         "青森",             "Tohoku",   0, 2),
    ("TOY", "도야마",           "富山",             "Hokuriku", 0, 2),
    ("KOJ", "가고시마",         "鹿児島",           "Kyushu",   0, 2),
    ("KMI", "미야자키",         "宮崎",             "Kyushu",   0, 2),
    ("OIT", "오이타",           "大分",             "Kyushu",   0, 2),
    ("NGS", "나가사키",         "長崎",             "Kyushu",   0, 2),
    ("KCZ", "고치",             "高知",             "Shikoku",  0, 2),
    ("HKD", "하코다테",         "函館",             "Hokkaido", 0, 2),
    ("FSZ", "시즈오카",         "静岡",             "Chubu",    0, 2),
    ("KMJ", "구마모토",         "熊本",             "Kyushu",   0, 2),
    # Tier 3 (저빈도, 공항다양성용)
    ("ISG", "이시가키",         "石垣",             "Okinawa",  0, 3),
    ("MMY", "미야코",           "宮古",             "Okinawa",  0, 3),
    ("MMB", "메만베쓰",         "女満別",           "Hokkaido", 0, 3),
    ("KIJ", "니가타",           "新潟",             "Hokuriku", 0, 3),
    ("OBO", "오비히로",         "帯広",             "Hokkaido", 0, 3),
    ("KUH", "구시로",           "釧路",             "Hokkaido", 0, 3),
    ("IZO", "이즈모",           "出雲",             "Chugoku",  0, 3),
    ("YGJ", "요나고",           "米子",             "Chugoku",  0, 3),
]

# --- 노선 (origin, destination, miles, flight_min, daily_freq) ---
# miles: 구간마일 (JAL 국내선 기준 추정)
# daily_freq: 1방향 1일 평균 편수 (대략값, 시즌·요일에 따라 변동)
# 양방향 자동 생성됨
ROUTES_ONE_WAY = [
    # ===== HND발 단거리 (Tier 1) =====
    ("HND", "ITM", 280,  65, 17),
    ("HND", "KIX", 280,  75,  3),
    ("HND", "NGO", 193,  60,  2),   # 신칸센 경쟁으로 적음
    ("HND", "HIJ", 414,  85,  7),
    ("HND", "KMQ", 211,  65,  6),
    ("HND", "OKJ", 356,  80,  5),
    # ===== HND발 중장거리 주요 =====
    ("HND", "FUK", 567,  95, 17),
    ("HND", "CTS", 510,  95, 17),
    ("HND", "OKA", 984, 165, 13),
    # ===== HND발 지방 (Tier 2) =====
    ("HND", "MYJ", 438,  85,  6),
    ("HND", "TAK", 320,  75,  5),
    ("HND", "AKT", 279,  70,  4),
    ("HND", "AOJ", 358,  75,  6),
    ("HND", "TOY", 192,  60,  4),
    ("HND", "KOJ", 601, 100,  8),
    ("HND", "KMI", 561,  95,  6),
    ("HND", "KMJ", 568,  95,  8),
    ("HND", "OIT", 499,  90,  6),
    ("HND", "NGS", 610, 105,  6),
    ("HND", "KCZ", 397,  80,  5),
    ("HND", "HKD", 415,  80,  4),
    ("HND", "FSZ", 100,  55,  2),
    ("HND", "OBO", 526, 100,  4),
    ("HND", "IZO", 405,  85,  5),
    # ===== HND발 Tier 3 (1-2왕복) =====
    ("HND", "ISG",1224, 200,  1),
    ("HND", "MMY",1130, 195,  1),
    # ===== ITM발 =====
    ("ITM", "OKA", 739, 130,  3),
    ("ITM", "AOJ", 624, 100,  2),
    ("ITM", "AKT", 567,  95,  2),
    ("ITM", "HKD", 695, 110,  2),
    ("ITM", "CTS", 666, 110,  5),
    ("ITM", "FUK", 287,  70,  4),
    ("ITM", "ISG", 985, 165,  1),
    ("ITM", "MYJ", 159,  55,  2),
    ("ITM", "TAK", 137,  50,  3),
    ("ITM", "KOJ", 329,  80,  7),
    ("ITM", "OIT", 286,  70,  3),
    ("ITM", "KMI", 292,  75,  5),
    ("ITM", "KMJ", 290,  75,  4),
    ("ITM", "NGS", 330,  80,  4),
    # ===== KIX발 =====
    ("KIX", "OKA", 740, 130,  3),
    ("KIX", "ISG",1018, 170,  1),
    ("KIX", "CTS", 666, 110,  2),
    # ===== NGO발 =====
    ("NGO", "OKA", 809, 145,  4),
    ("NGO", "CTS", 533,  95,  3),
    ("NGO", "FUK", 366,  85,  3),
    ("NGO", "AKT", 380,  85,  2),
    ("NGO", "ISG",1057, 175,  1),
    # ===== FUK발 =====
    ("FUK", "OKA", 530,  95,  4),
    ("FUK", "CTS", 882, 145,  2),
    ("FUK", "OBO", 950, 150,  1),
    # ===== CTS발 =====
    ("CTS", "OKA",1399, 215,  2),
    ("CTS", "FUK", 882, 145,  2),
    # ===== OKA발 =====
    ("OKA", "ISG", 247,  60,  6),
    ("OKA", "MMY", 177,  55,  8),
    # ===== NRT발 =====
    ("NRT", "ITM", 280,  75,  3),
    ("NRT", "OKA", 984, 170,  3),
    ("NRT", "CTS", 510,  95,  2),
    ("NRT", "FUK", 567, 100,  2),
    # ===== HND발 추가 =====
    ("HND", "MMB", 537, 100,  2),
    ("HND", "OBO", 543, 100,  2),
    ("HND", "KUH", 558, 100,  2),
    ("HND", "IZO", 414,  85,  2),
    ("HND", "YGJ", 405,  85,  2),
    ("HND", "KIJ", 175,  60,  2),
]


def make_routes_bidirectional(routes_one_way):
    """양방향으로 확장."""
    result = []
    for o, d, mi, mn, fr in routes_one_way:
        result.append((o, d, mi, mn, fr))
        result.append((d, o, mi, mn, fr))
    # 중복 제거 (혹시)
    seen = set()
    out = []
    for r in result:
        k = (r[0], r[1])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def generate_flights_for_route(origin, destination, flight_min, daily_freq):
    """노선당 daily_freq개의 항공편을 06:00~21:00 사이에 균등 분포로 생성."""
    flights = []
    if daily_freq <= 0:
        return flights

    # 운항 시간대: 06:00-21:00 = 900분
    window_start = 6 * 60
    window_end = 21 * 60
    window_size = window_end - window_start

    if daily_freq == 1:
        slots = [window_start + window_size // 2]
    else:
        step = window_size // (daily_freq - 1) if daily_freq > 1 else window_size
        slots = [window_start + i * step for i in range(daily_freq)]

    # 편명: 출발지가 HND면 JL1xx 시리즈처럼 합성 번호
    base_no = abs(hash(origin + destination)) % 900 + 100
    for i, dep_min in enumerate(slots):
        arr_min = dep_min + flight_min
        if arr_min >= 24 * 60:
            continue
        flight_no = f"JL{base_no + i:03d}"
        dep_str = f"{dep_min//60:02d}:{dep_min%60:02d}"
        arr_str = f"{arr_min//60:02d}:{arr_min%60:02d}"
        flights.append((flight_no, origin, destination, dep_str, arr_str, "1111111"))
    return flights


def seed():
    """공항·노선만 시드. 항공편(flights)은 CSV 임포트로 따로 넣어야 함."""
    init_db()
    routes = make_routes_bidirectional(ROUTES_ONE_WAY)

    with get_conn() as c:
        # 기존 데이터 클리어
        c.execute("DELETE FROM airports")
        c.execute("DELETE FROM routes")
        # ⚠️ flights 테이블은 비우지 않음 — CSV 임포트 데이터 보존

        # 공항
        c.executemany(
            "INSERT INTO airports(code,name_ko,name_jp,region,is_base,tier) "
            "VALUES(?,?,?,?,?,?)",
            AIRPORTS
        )

        # 노선
        c.executemany(
            "INSERT INTO routes(origin,destination,miles,flight_min,daily_freq) "
            "VALUES(?,?,?,?,?)",
            routes
        )

    # 시드 운임
    seed_fares()

    # 항공편 수 확인
    with get_conn() as c:
        flight_count = c.execute("SELECT COUNT(*) FROM flights").fetchone()[0]

    print(f"공항 {len(AIRPORTS)}개, 노선 {len(routes)}개 시드 완료.")
    print(f"항공편: 현재 {flight_count}건. CSV 임포트로 추가 가능 (data/ 폴더 또는 UI).")


# 시드 운임 — 노선·운임클래스별 대표 최저가 (참고치, 시즌·잔여석에 따라 변동)
SEED_FARES = {
    # (origin,dest): {fare_class: jpy}
    ("HND", "ITM"): {"Promo": 11000, "Saver": 14000, "Flex": 27000},
    ("HND", "KMQ"): {"Promo": 12000, "Saver": 15000, "Flex": 28000},
    ("HND", "NGO"): {"Promo": 11000, "Saver": 13000, "Flex": 24000},
    ("HND", "HIJ"): {"Promo": 13000, "Saver": 17000, "Flex": 32000},
    ("HND", "OKJ"): {"Promo": 12000, "Saver": 15000, "Flex": 29000},
    ("HND", "KIX"): {"Promo": 11000, "Saver": 14000, "Flex": 27000},
    ("HND", "FUK"): {"Promo": 14000, "Saver": 18000, "Flex": 36000},
    ("HND", "CTS"): {"Promo": 13000, "Saver": 17000, "Flex": 35000},
    ("HND", "OKA"): {"Promo": 16000, "Saver": 22000, "Flex": 45000},
    ("HND", "AKT"): {"Promo": 12000, "Saver": 15000, "Flex": 30000},
    ("HND", "AOJ"): {"Promo": 12000, "Saver": 15000, "Flex": 32000},
    ("HND", "TOY"): {"Promo": 11000, "Saver": 13000, "Flex": 25000},
    ("OKA", "ISG"): {"Promo": 8000,  "Saver": 11000, "Flex": 22000},
    ("OKA", "MMY"): {"Promo": 7000,  "Saver": 10000, "Flex": 20000},
    ("ITM", "OKA"): {"Promo": 14000, "Saver": 19000, "Flex": 38000},
    ("KIX", "OKA"): {"Promo": 14000, "Saver": 19000, "Flex": 38000},
    ("NGO", "OKA"): {"Promo": 14000, "Saver": 19000, "Flex": 38000},
    ("KMQ", "OKA"): {"Promo": 17000, "Saver": 22000, "Flex": 42000},
}


def seed_fares():
    """시드 운임을 confidence=0으로 등록 (양방향)."""
    from datetime import datetime
    rows = []
    now = datetime.now().isoformat(timespec="seconds")
    for (o, d), classes in SEED_FARES.items():
        for fc, jpy in classes.items():
            rows.append((o, d, "SEED", fc, jpy, "seed", 0, now,
                         "공식 공개 최저가 참고치"))
            rows.append((d, o, "SEED", fc, jpy, "seed", 0, now,
                         "공식 공개 최저가 참고치"))
    with get_conn() as c:
        # 기존 seed 데이터 클리어
        c.execute("DELETE FROM fare_cache WHERE source='seed'")
        c.executemany("""
            INSERT INTO fare_cache(origin,destination,flight_date,fare_class,
                                   price_jpy,source,confidence,observed_at,notes)
            VALUES(?,?,?,?,?,?,?,?,?)
        """, rows)
    print(f"시드 운임 {len(rows)}건 등록 완료.")


if __name__ == "__main__":
    seed()
