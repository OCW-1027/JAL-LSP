"""駅探(ekitan) JAL国内線時刻表 → data/flights_by_date.csv

使い方:
  python etl/fetch_ekitan.py --days 60 --workers 4

JAL公式サイトには一切アクセスしない。ekitan.com の静的ページのみを
リクエスト間隔をあけて取得する。
"""
from __future__ import annotations
import argparse, csv, json, re, sys, time, random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
import urllib.request

BASE = "https://ekitan.com/timetable/airplane/domestic/departure/jal/{aid}?dt={ymd}"
UA = "Mozilla/5.0 (compatible; JAL-LSP-Optimizer/2.0; personal use)"

# 駅探 空港ID → IATA (2026-09 時点)
AIRPORT_IDS = {
    1: "WKJ", 2: "MBE", 3: "MMB", 4: "CTS", 5: "AKJ", 6: "SHB", 7: "OKD", 8: "KUH",
    9: "OBO", 10: "HKD", 59: "RIS", 60: "OIR",
    11: "AOJ", 12: "MSJ", 14: "AXT", 15: "HNA", 17: "GAJ", 18: "SDJ", 19: "KIJ", 26: "MMJ",
    21: "NRT", 22: "HND", 24: "KMQ", 58: "FSZ", 27: "NKM", 28: "NGO",
    29: "ITM", 30: "KIX", 56: "UKB", 31: "SHM", 32: "TJH",
    33: "OKJ", 37: "IZO", 64: "OKI", 38: "HIJ", 40: "UBJ", 41: "TAK", 42: "MYJ",
    43: "TKS", 44: "KCZ",
    45: "FUK", 46: "KMI", 57: "KKJ", 49: "NGS", 65: "TSJ", 66: "IKI", 67: "FUJ",
    50: "OIT", 51: "KMJ", 68: "AXJ", 52: "KOJ", 69: "TNE", 70: "KUM", 71: "KKX",
    72: "ASJ", 73: "TKN", 74: "OKE", 75: "RNJ",
    53: "OKA", 76: "KTD", 77: "MMD", 79: "UEO", 80: "MMY", 93: "SHI", 81: "TRA",
    82: "ISG", 83: "OGN",
}
CODE_FIX = {"SPK": "CTS", "OSA": "ITM", "TYO": "HND"}

REC = re.compile(r'<tr class="search-result-data-rec[^"]*">(.*?)</tr>', re.S)
ROW = re.compile(
    r'dep-time">(\d{2}:\d{2})<span class="dep-arr-airpot">([^<]+)</span>.*?'
    r'arr-time">(\d{2}:\d{2})<span class="dep-arr-airpot">([^<]+)</span>.*?'
    r'td-required-time">([A-Z]{3}\d{3,4})<.*?dep=([A-Z]{3}).*?arr=([A-Z]{3})', re.S)


def fetch(aid: int, d: date, retries: int = 3) -> list[dict]:
    url = BASE.format(aid=aid, ymd=d.strftime("%Y%m%d"))
    html = ""
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                html = r.read().decode("utf-8", "ignore")
            break
        except Exception as e:
            if i == retries - 1:
                print(f"FAIL {aid} {d}: {e}", file=sys.stderr)
                return []
            time.sleep(3 * (i + 1))
    out = []
    for rec in REC.findall(html):
        m = ROW.search(rec)
        if not m:
            continue
        dep_t, dep_n, arr_t, arr_n, fno, dep_c, arr_c = m.groups()
        out.append(dict(
            date=d.isoformat(), flight_no=fno,
            origin=CODE_FIX.get(dep_c, dep_c), destination=CODE_FIX.get(arr_c, arr_c),
            dep_time=dep_t, arr_time=arr_t, origin_name=dep_n, dest_name=arr_n))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--start", default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--out", default="data")
    ap.add_argument("--airports", default=None, help="IATA comma list (test用)")
    a = ap.parse_args()
    start = date.fromisoformat(a.start) if a.start else date.today()
    days = [start + timedelta(i) for i in range(a.days)]
    out = Path(a.out)
    out.mkdir(exist_ok=True)

    ids = AIRPORT_IDS
    if a.airports:
        want = set(a.airports.split(","))
        ids = {k: v for k, v in AIRPORT_IDS.items() if v in want}

    # 1) 初日で JAL 就航空港を判定 (逐次・低負荷)
    rows_all, active = [], []
    for aid in ids:
        rows = fetch(aid, days[0])
        time.sleep(a.delay)
        if rows:
            active.append(aid)
            rows_all.extend(rows)
    print(f"active airports: {len(active)}/{len(ids)}")

    # 2) 残りの日付を控えめな並列で取得
    jobs = [(aid, d) for d in days[1:] for aid in active]

    def work(job):
        aid, d = job
        time.sleep(a.delay + random.random() * 0.5)
        return fetch(aid, d)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(work, j) for j in jobs]
        for i, f in enumerate(as_completed(futs), 1):
            rows_all.extend(f.result())
            if i % 200 == 0:
                print(f"  {i}/{len(jobs)}")

    # 3) 重複除去・保存
    seen, uniq = set(), []
    for r in rows_all:
        k = (r["date"], r["flight_no"], r["origin"], r["destination"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    if not uniq:
        print("no data fetched; keeping previous files", file=sys.stderr)
        sys.exit(1)
    uniq.sort(key=lambda r: (r["date"], r["origin"], r["dep_time"]))
    with open(out / "flights_by_date.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(uniq[0].keys()))
        w.writeheader()
        w.writerows(uniq)

    names = {}
    for r in uniq:
        names[r["origin"]] = r["origin_name"]
        names[r["destination"]] = r["dest_name"]
    meta = dict(source="ekitan.com (JAL filter)", fetched_at=date.today().isoformat(),
                date_from=days[0].isoformat(), date_to=days[-1].isoformat(),
                flights=len(uniq), airports=len(names), airport_names=names)
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    print(f"saved {len(uniq)} flights, {len(names)} airports, {days[0]}..{days[-1]}")


if __name__ == "__main__":
    main()
