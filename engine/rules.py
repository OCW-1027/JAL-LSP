"""JAL ルール・定数 (FOP/LSP/MCT).

FOP = 区間マイル × (運賃積算率 + 座席加算) × 2 (国内線) + 搭乗ボーナスFOP
※ 数値は JAL 公式ページで随時確認のこと。変更はこのファイルだけで完結する。
"""

# 同一空港乗継の最短時間 (分) + 安全バッファ
MCT = {"HND": 30, "OKA": 30}
DEFAULT_MCT = 20
SAFETY_BUFFER = 10

LSP_PER_SEGMENT = 5
DOMESTIC_FOP_MULTIPLIER = 2

# 運賃種別: 積算率, 搭乗ボーナスFOP
FARE_CLASSES = {
    "Flex":         {"mile_rate": 1.00, "fop_bonus": 400, "label": "フレックス (100%・+400)"},
    "CardDiscount": {"mile_rate": 1.00, "fop_bonus": 400, "label": "JALカード割引 (100%・+400)"},
    "Saver":        {"mile_rate": 0.75, "fop_bonus": 200, "label": "セイバー (75%・+200)"},
    "SpecialSaver": {"mile_rate": 0.75, "fop_bonus": 200, "label": "スペシャルセイバー (75%・+200)"},
    "Shareholder":  {"mile_rate": 0.75, "fop_bonus": 200, "label": "株主割引 (75%・+200)"},
    "Promo":        {"mile_rate": 0.50, "fop_bonus": 0,   "label": "プロモーション (50%・+0)"},
}

# 座席クラス: 積算率への加算
CABIN_CLASSES = {
    "Y": {"add_rate": 0.00, "label": "普通席"},
    "J": {"add_rate": 0.10, "label": "クラスJ (+10%)"},
    "F": {"add_rate": 0.50, "label": "ファーストクラス (+50%)"},
}

# FLY ON ステイタス基準 (暦年)
STATUS_THRESHOLDS = [
    {"name": "クリスタル",       "fop": 30000,  "count": 30,  "count_fop": 10000},
    {"name": "サファイア",       "fop": 50000,  "count": 50,  "count_fop": 15000},
    {"name": "JGCプレミア",      "fop": 80000,  "count": 80,  "count_fop": 25000},
    {"name": "ダイヤモンド",     "fop": 100000, "count": 120, "count_fop": 35000},
    {"name": "ダイヤモンドMetal", "fop": 150000, "count": 180, "count_fop": 50000},
]
LSP_MILESTONES = [
    {"name": "JGC (Three Star)", "lsp": 1500},
    {"name": "Four Star", "lsp": 3000},
    {"name": "Five Star", "lsp": 6000},
]

PATTERNS = {
    "day":  {"days": 1, "label": "日帰り", "start_hour": 6, "end_hour": 22},
    "1n2d": {"days": 2, "label": "1泊2日", "start_hour": 6, "end_hour": 22},
    "2n3d": {"days": 3, "label": "2泊3日", "start_hour": 6, "end_hour": 22},
}


def get_mct(airport: str) -> int:
    return MCT.get(airport, DEFAULT_MCT)


def safe_mct(airport: str) -> int:
    return get_mct(airport) + SAFETY_BUFFER


def accrual_rate(fare_class: str, cabin: str = "Y") -> float:
    return FARE_CLASSES[fare_class]["mile_rate"] + CABIN_CLASSES[cabin]["add_rate"]


def fop_per_segment(miles: int, fare_class: str, cabin: str = "Y") -> int:
    """1セグメントの FOP."""
    return int(miles * accrual_rate(fare_class, cabin) * DOMESTIC_FOP_MULTIPLIER
               + FARE_CLASSES[fare_class]["fop_bonus"])


def flight_miles(miles: int, fare_class: str, cabin: str = "Y") -> int:
    return int(miles * accrual_rate(fare_class, cabin))
