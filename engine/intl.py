"""国際線: JAL就航地の座標・地域と FOP 計算.

区間マイル (TPM) は JAL 公式表を自動取得できないため大圏距離から推定 (誤差 ±3% 程度)。
data/intl_routes.csv に  origin,destination,miles  を置けば公式値で上書きできる。
"""
from __future__ import annotations
import csv, math
from pathlib import Path

# code: (name_ja, lat, lon, region)   region: "asia" (アジア・オセアニア=換算1.5) / "other" (=1.0)
INTL_AIRPORTS = {
    "ICN": ("ソウル(仁川)", 37.4602, 126.4407, "asia"), "GMP": ("ソウル(金浦)", 37.5583, 126.7906, "asia"),
    "PUS": ("釜山", 35.1795, 128.9382, "asia"), "TAO": ("青島", 36.2661, 120.3744, "asia"),
    "PEK": ("北京(首都)", 40.0801, 116.5846, "asia"), "PKX": ("北京(大興)", 39.5098, 116.4105, "asia"),
    "PVG": ("上海(浦東)", 31.1434, 121.8052, "asia"), "SHA": ("上海(虹橋)", 31.1979, 121.3363, "asia"),
    "DLC": ("大連", 38.9657, 121.5386, "asia"), "TSN": ("天津", 39.1244, 117.3462, "asia"),
    "CAN": ("広州", 23.3924, 113.2988, "asia"), "HKG": ("香港", 22.3080, 113.9185, "asia"),
    "TPE": ("台北(桃園)", 25.0777, 121.2328, "asia"), "TSA": ("台北(松山)", 25.0694, 121.5525, "asia"),
    "KHH": ("高雄", 22.5771, 120.3500, "asia"), "MNL": ("マニラ", 14.5086, 121.0198, "asia"),
    "CEB": ("セブ", 10.3075, 123.9794, "asia"), "HAN": ("ハノイ", 21.2212, 105.8072, "asia"),
    "SGN": ("ホーチミン", 10.8188, 106.6520, "asia"), "BKK": ("バンコク", 13.6900, 100.7501, "asia"),
    "KUL": ("クアラルンプール", 2.7456, 101.7099, "asia"), "SIN": ("シンガポール", 1.3644, 103.9915, "asia"),
    "CGK": ("ジャカルタ", -6.1256, 106.6559, "asia"), "DPS": ("デンパサール", -8.7482, 115.1672, "asia"),
    "DEL": ("デリー", 28.5562, 77.1000, "asia"), "BLR": ("ベンガルール", 13.1986, 77.7066, "asia"),
    "SYD": ("シドニー", -33.9399, 151.1753, "asia"), "MEL": ("メルボルン", -37.6690, 144.8410, "asia"),
    "GUM": ("グアム", 13.4834, 144.7960, "asia"),
    "HNL": ("ホノルル", 21.3187, -157.9225, "other"), "KOA": ("コナ", 19.7388, -156.0456, "other"),
    "LAX": ("ロサンゼルス", 33.9416, -118.4085, "other"), "SFO": ("サンフランシスコ", 37.6213, -122.3790, "other"),
    "SAN": ("サンディエゴ", 32.7338, -117.1933, "other"), "SEA": ("シアトル", 47.4502, -122.3088, "other"),
    "DFW": ("ダラス", 32.8998, -97.0403, "other"), "ORD": ("シカゴ", 41.9742, -87.9073, "other"),
    "BOS": ("ボストン", 42.3656, -71.0096, "other"), "JFK": ("ニューヨーク(JFK)", 40.6413, -73.7781, "other"),
    "YVR": ("バンクーバー", 49.1947, -123.1792, "other"),
    "LHR": ("ロンドン", 51.4700, -0.4543, "other"), "CDG": ("パリ", 49.0097, 2.5479, "other"),
    "FRA": ("フランクフルト", 50.0379, 8.5622, "other"), "HEL": ("ヘルシンキ", 60.3172, 24.9633, "other"),
    "DOH": ("ドーハ", 25.2731, 51.6081, "other"),
}
GATEWAYS = {"HND": (35.5494, 139.7798), "NRT": (35.7647, 140.3864), "KIX": (34.4347, 135.2441),
            "NGO": (34.8584, 136.8054), "FUK": (33.5859, 130.4507), "CTS": (42.7752, 141.6923),
            "OKA": (26.1958, 127.6459)}

# 予約クラス → 積算率, 搭乗ボーナスFOP  (JAL国際線・代表値。要確認)
INTL_CLASSES = {
    "F/A (ファースト)":            (1.50, 400),
    "J/C/D/X/I (ビジネス)":        (1.25, 400),
    "W/R/E (プレミアムエコノミー)": (1.00, 400),
    "Y/B (エコノミー正規)":         (1.00, 400),
    "H/K/M (エコノミー割引)":       (0.70, 200),
    "L/V/S (エコノミー割引)":       (0.50, 0),
    "O/Z/G/Q/N (エコノミー最割引)": (0.30, 0),
}
FOP_RATE = {"asia": 1.5, "other": 1.0}

_OVERRIDE: dict[tuple[str, str], int] = {}
_p = Path(__file__).resolve().parent.parent / "data" / "intl_routes.csv"
if _p.exists():
    for r in csv.DictReader(open(_p, encoding="utf-8")):
        try:
            m = int(r["miles"])
            _OVERRIDE[(r["origin"], r["destination"])] = m
            _OVERRIDE[(r["destination"], r["origin"])] = m
        except (KeyError, ValueError):
            pass


def _gc(lat1, lon1, lat2, lon2) -> int:
    la1, lo1, la2, lo2 = map(math.radians, (lat1, lon1, lat2, lon2))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return int(round(6371.0 * 2 * math.asin(math.sqrt(h)) * 0.621371))


def intl_miles(gw: str, dest: str) -> tuple[int, bool]:
    """(miles, is_estimate)"""
    if (gw, dest) in _OVERRIDE:
        return _OVERRIDE[(gw, dest)], False
    la, lo = GATEWAYS[gw]
    _, dla, dlo, _ = INTL_AIRPORTS[dest]
    return _gc(la, lo, dla, dlo), True


def intl_fop(miles: int, region: str, cls: str) -> int:
    rate, bonus = INTL_CLASSES[cls]
    return int(miles * rate * FOP_RATE[region] + bonus)
