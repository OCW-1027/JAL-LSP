"""修行ルート検索 for JAL（非公式） — Streamlit

データ: data/flights_by_date.csv (駅探 JAL時刻表を GitHub Actions で週次自動取得)
"""
from datetime import date, timedelta
import pandas as pd
import streamlit as st

from engine.data import (load_meta, available_dates, airports, airport_label, reload)
from engine.optimizer import search_routes, route_to_dict
from engine.rules import (FARE_CLASSES, CABIN_CLASSES, STATUS_THRESHOLDS, LSP_MILESTONES,
                          fop_per_segment, LSP_PER_SEGMENT)
from engine.miles import route_miles
from engine.intl import INTL_AIRPORTS, GATEWAYS, INTL_CLASSES, FOP_RATE, intl_miles, intl_fop

APP_NAME = "修行ルート検索 for JAL"
st.set_page_config(page_title=APP_NAME, page_icon="🛫", layout="wide", initial_sidebar_state="collapsed")

meta = load_meta()
dates = available_dates()
HUBS = ["HND", "ITM", "KIX", "NGO", "CTS", "FUK", "OKA"]
NAMES = meta.get("airport_names", {})
MAX_BUDGET = 15  # 共有サーバー保護のため検索時間上限


def city(code: str) -> str:
    return f"{NAMES.get(code, code)} ({code})"


def jal_url(o, d, dt: date) -> str:
    return f"https://www.jal.co.jp/jp/ja/dom/booking/?dep={o}&arr={d}&date={dt.strftime('%Y%m%d')}"


def google_url(o, d, dt: date) -> str:
    return f"https://www.google.com/travel/flights?q=Flights%20from%20{o}%20to%20{d}%20on%20{dt.isoformat()}"


@st.cache_data(ttl=3600, max_entries=300, show_spinner=False)
def cached_search(bases, start, end, pattern, fare, seg_min, seg_max, top_n, budget,
                  diversify, max_per, finals, allowed, cabin, objective):
    return search_routes(list(bases), start, end, pattern, fare,
                         min_segments=seg_min, max_segments=seg_max, top_n=top_n,
                         time_budget_sec=float(budget), diversify=diversify,
                         max_per_first_dest=max_per, final_dests=list(finals) or None,
                         allowed_airports=list(allowed) or None, cabin=cabin, objective=objective)


def choice(label, options, fmt, key, default=None, help=None):
    """segmented_control があれば使い、無ければ radio."""
    try:
        kw = {} if key in st.session_state else {"default": default}
        v = st.segmented_control(label, options, format_func=fmt, key=key, help=help, **kw)
        return v if v is not None else default
    except AttributeError:
        idx = options.index(default) if default in options else 0
        return st.radio(label, options, format_func=fmt, key=key, index=idx, horizontal=True, help=help)


# ===== プリセット =====
PRESETS = {
    "沖縄タッチ":   {"desc": "HND-OKA 往復 ×2", "dep": "HND", "finals": ["HND"], "allowed": ["HND", "OKA"], "stay": "day", "obj": "fop", "seg": (4, 6)},
    "離島周遊":     {"desc": "那覇-石垣-宮古", "dep": "OKA", "finals": ["OKA"], "allowed": ["OKA", "ISG", "MMY", "OGN"], "stay": "day", "obj": "lsp", "seg": (4, 10)},
    "九州短距離":   {"desc": "福岡-宮崎-松山", "dep": "FUK", "finals": [], "allowed": ["FUK", "KMI", "MYJ", "KMJ", "KOJ", "OIT", "NGS"], "stay": "day", "obj": "lsp", "seg": (4, 10)},
    "日帰り最大":   {"desc": "8セグ = LSP 40", "dep": "HND", "finals": ["HND"], "allowed": [], "stay": "day", "obj": "lsp", "seg": (6, 10)},
}


def apply_preset(name: str):
    p = PRESETS[name]
    st.session_state.update({"dep": p["dep"], "bases_extra": [], "finals": p["finals"],
                             "allowed": p["allowed"], "stay": p["stay"], "obj": p["obj"], "seg": p["seg"]})


# ===== ヘッダー =====
h1, h2 = st.columns([3, 1])
with h1:
    st.markdown(f"## 🛫 {APP_NAME} &nbsp;<span style='font-size:0.55em;padding:2px 10px;border:1px solid #999;border-radius:999px;color:#666;vertical-align:middle'>非公式</span>",
                unsafe_allow_html=True)
    st.caption("日付を入れるだけで、LSP・FOPが貯まる乗継ルートを提案 ― 運賃は扱いません（JALで直接確認）")
with h2:
    if dates:
        st.caption(f"時刻表: {dates[0]} 〜 {dates[-1]}  \n更新 {meta.get('fetched_at', '?')}・{meta.get('flights', 0):,}便")

tab_search, tab_plan, tab_table, tab_help = st.tabs(["🔍 検索", "📈 年間プラン", "📋 路線別FOP・マイル表", "📖 使い方"])

# ===== 検索 =====
with tab_search:
    if not dates:
        st.error("時刻表データがありません。GitHub Actions の update-timetable を実行してください。")
        st.stop()
    dmin, dmax = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    ap_codes = airports()
    st.session_state.setdefault("dep", "HND" if "HND" in ap_codes else ap_codes[0])
    st.session_state.setdefault("stay", "day")
    st.session_state.setdefault("obj", "lsp")
    st.session_state.setdefault("seg", (4, 10))

    # --- かんたん検索 ---
    with st.container(border=True):
        c1, c2, c3 = st.columns([1.2, 1, 0.8])
        dep = c1.selectbox("出発空港", ap_codes, format_func=city, key="dep")
        default_day = min(max(dmin, date.today() + timedelta(days=1)), dmax)
        day = c2.date_input("日付", value=default_day, min_value=dmin, max_value=dmax, key="day")
        stay = c3.selectbox("滞在", ["day", "1n2d", "2n3d"], key="stay",
                            format_func=lambda k: {"day": "日帰り", "1n2d": "1泊2日", "2n3d": "2泊3日"}[k])
        obj = choice("なにを増やす？", ["lsp", "fop", "count"],
                     lambda k: {"lsp": "LSP（搭乗回数）", "fop": "FOP（年間ステイタス）", "count": "回数（短時間で）"}[k],
                     key="obj", default=st.session_state["obj"])
        go = st.button("🔍 ルートを探す", type="primary", width='stretch')

        with st.expander("詳細設定（到着空港・使う空港・運賃・座席・セグメント数）"):
            a1, a2 = st.columns(2)
            bases_extra = a1.multiselect("出発空港を追加", [c for c in ap_codes if c != dep], format_func=city, key="bases_extra")
            finals = a2.multiselect("最終到着空港（空欄=任意／出発と同じ=往復）", ap_codes, format_func=city, key="finals")
            allowed = st.multiselect("使う空港を限定（指定するとこの空港間のみ。出発・到着の指定は無視）",
                                     ap_codes, format_func=city, key="allowed")
            b1, b2, b3 = st.columns(3)
            end_day = b1.date_input("終了日（複数日を一括検索）", value=day, min_value=dmin, max_value=dmax, key="end_day")
            fare = b2.selectbox("運賃（FOP計算用）", list(FARE_CLASSES), index=2, format_func=lambda k: FARE_CLASSES[k]["label"], key="fare")
            cabin = b3.selectbox("座席（FOP計算用）", list(CABIN_CLASSES), index=0, format_func=lambda k: CABIN_CLASSES[k]["label"], key="cabin")
            seg_min, seg_max = st.slider("セグメント数の範囲", 2, 24, key="seg")
            d1, d2, d3 = st.columns(3)
            top_n = d1.slider("表示件数", 5, 30, 12, key="top_n")
            budget = d2.slider("最大検索時間（秒）", 2, MAX_BUDGET, 6, key="budget")
            max_per = d3.slider("同じ組合せの最大表示数", 1, 5, 2, key="max_per")
            diversify = st.checkbox("結果を多様化する", True, key="diversify")

    st.markdown("**よく使う修行パターン**（タップで条件をセット）")
    pcols = st.columns(4)
    for col, (name, p) in zip(pcols, PRESETS.items()):
        col.button(f"{name}\n\n{p['desc']}", key=f"preset_{name}", on_click=apply_preset, args=(name,), width='stretch')

    # --- 検索実行 ---
    if go:
        bases = [dep] + [b for b in bases_extra if b != dep]
        end_day = max(end_day, day)
        if end_day < day:
            end_day = day
        with st.spinner("検索中…"):
            results = cached_search(tuple(bases), day, end_day, stay, fare, seg_min, seg_max, top_n, budget,
                                    diversify, max_per, tuple(finals), tuple(allowed), cabin, obj)
        st.session_state["results"] = results
        st.session_state["results_ctx"] = dict(dep=dep, day=day, stay=stay, obj=obj, fare=fare, cabin=cabin)

    results = st.session_state.get("results")
    ctx = st.session_state.get("results_ctx", {})
    if results is not None:
        stay_jp = {"day": "日帰り", "1n2d": "1泊2日", "2n3d": "2泊3日"}
        obj_jp = {"lsp": "LSP優先", "fop": "FOP優先", "count": "回数優先"}
        st.markdown("---")
        if not results:
            st.info("条件に合うルートが見つかりませんでした。セグメント数の範囲を広げるか、検索時間を増やしてみてください。")
        else:
            r1, r2 = st.columns([2, 1])
            r1.markdown(f"#### {city(ctx['dep'])}発 ・ {ctx['day']} ・ {stay_jp[ctx['stay']]}　"
                        f"<span style='color:#666;font-size:0.8em'>{obj_jp[ctx['obj']]}・{len(results)}件</span>", unsafe_allow_html=True)
            sort_key = r2.selectbox("並び替え", ["lsp", "fop", "time"], format_func=lambda k: {"lsp": "LSP順", "fop": "FOP順", "time": "短時間順"}[k],
                                    key="sort_key", label_visibility="collapsed")
            view = st.radio("表示", ["カード", "表"], horizontal=True, key="view", label_visibility="collapsed")
            if sort_key == "lsp":
                results = sorted(results, key=lambda r: (-r.lsp, -r.fop))
            elif sort_key == "fop":
                results = sorted(results, key=lambda r: (-r.fop, -r.lsp))
            else:
                results = sorted(results, key=lambda r: (r.total_minutes / max(r.num_segments, 1)))

            if view == "表":
                df = pd.DataFrame([route_to_dict(r) for r in results])
                df["fop_seg"] = (df["fop"] / df["segments"]).round(0).astype(int)
                show = df[["date", "route", "segments", "airports", "lsp", "fop", "fop_seg", "miles"]]
                show.columns = ["日付", "ルート", "セグ", "空港数", "LSP", "FOP", "FOP/セグ", "マイル"]
                st.dataframe(show, width='stretch', hide_index=True, height=min(500, 50 + len(show) * 35))

            for i, r in enumerate(results):
                first, last = r.segments[0], r.segments[-1]
                names_path = " → ".join([NAMES.get(first.origin, first.origin)] + [NAMES.get(s.destination, s.destination) for s in r.segments])
                with st.container(border=True):
                    top = st.columns([1, 3])
                    if i == 0:
                        top[0].markdown("<span style='background:#0f6e78;color:#fff;padding:2px 10px;border-radius:6px;font-size:0.8em;font-weight:700'>おすすめ</span>", unsafe_allow_html=True)
                    else:
                        top[0].markdown(f"**#{i+1}**")
                    top[1].caption(f"{r.num_segments}セグ ・ {r.num_airports}空港 ・ {first.dep_time}〜{last.arr_time}"
                                   + (f" ・ {first.flight_date} 発" if ctx.get('stay') != 'day' or len(set(s.flight_date for s in r.segments)) > 1 else ""))
                    m1, m2, m3 = st.columns(3)
                    m1.metric("LSP", r.lsp)
                    m2.metric("FOP", f"{r.fop:,}")
                    m3.metric("マイル", f"{r.miles:,}")
                    st.markdown(f"**{names_path}**")
                    with st.expander("区間の詳細・JALで確認"):
                        rows = [{"便名": s.flight_no, "日付": s.flight_date.isoformat(),
                                 "区間": f"{NAMES.get(s.origin, s.origin)} → {NAMES.get(s.destination, s.destination)}",
                                 "出発": s.dep_time, "到着": s.arr_time, "マイル": s.miles,
                                 "FOP": fop_per_segment(s.miles, ctx["fare"], ctx["cabin"]),
                                 "JAL": jal_url(s.origin, s.destination, s.flight_date),
                                 "Google": google_url(s.origin, s.destination, s.flight_date)} for s in r.segments]
                        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True,
                                     column_config={"JAL": st.column_config.LinkColumn("JAL", display_text="JALで確認"),
                                                    "Google": st.column_config.LinkColumn("Google", display_text="Google")})
                        if any(getattr(s, "miles_est", False) for s in r.segments):
                            st.caption("※一部の区間マイルは推定値です")

    st.markdown("---")
    st.caption("時刻表出典: 駅探 JAL国内線時刻表（週1回自動更新）。本サイトは JAL とは無関係の非公式ツールです。"
               "運賃は表示しません。予約前に必ず JAL 公式で運航・乗継可否・運賃をご確認ください。"
               "FOP・ステイタス基準は変更されることがあります。")

with tab_plan:
    st.markdown("### 📈 年間プラン・シミュレーター")
    st.caption("現在値 + 予定している搭乗パターンから、年末の FOP / 回数 / LSP と到達ステイタスを試算します")
    c1, c2, c3, c4 = st.columns(4)
    cur_fop = c1.number_input("現在の年間FOP", 0, 300000, 0, step=1000)
    cur_cnt = c2.number_input("現在の年間搭乗回数", 0, 400, 0)
    cur_lsp = c3.number_input("現在のLSP", 0, 10000, 488, step=10)
    card_lsp = c4.number_input("カード等で年内に見込むLSP", 0, 1000, 100, step=10)

    pf, pc = st.columns(2)
    plan_fare = pf.selectbox("既定の運賃", list(FARE_CLASSES), index=2, format_func=lambda k: FARE_CLASSES[k]["label"], key="pf")
    plan_cabin = pc.selectbox("既定の座席", list(CABIN_CLASSES), index=0, format_func=lambda k: CABIN_CLASSES[k]["label"], key="pc")

    def _fop(route: str, fare_k: str, cabin_k: str) -> int:
        codes = [c.strip().upper() for c in route.replace("→", "-").split("-") if c.strip()]
        return sum(fop_per_segment(route_miles(a, b)[0], fare_k, cabin_k) for a, b in zip(codes, codes[1:]))

    default_rows = pd.DataFrame([
        {"名称": "長崎 Jクラス 往復", "ルート": "HND-NGS-HND", "座席": "J", "年間回数": 12},
        {"名称": "沖縄・石垣 8セグ", "ルート": "HND-OKA-ISG-OKA-HND-OKA-ISG-OKA-HND", "座席": "Y", "年間回数": 6},
        {"名称": "短距離 往復", "ルート": "HND-ITM-HND", "座席": "Y", "年間回数": 4},
    ])
    st.markdown("**搭乗パターン** (ルートは IATA コードをハイフン区切り。行の追加・削除可)")
    rows = st.data_editor(default_rows, num_rows="dynamic", width='stretch',
                          column_config={"座席": st.column_config.SelectboxColumn(options=list(CABIN_CLASSES))})
    calc = []
    for _, r in rows.iterrows():
        if not str(r.get("ルート", "")).strip():
            continue
        segs = str(r["ルート"]).count("-")
        cab = r["座席"] if r["座席"] in CABIN_CLASSES else plan_cabin
        f1 = _fop(str(r["ルート"]), plan_fare, cab)
        n = int(r["年間回数"] or 0)
        calc.append({"名称": r["名称"], "セグ/回": segs, "FOP/回": f1, "年間回数": n,
                     "年間セグ": segs * n, "年間FOP": f1 * n, "年間LSP": segs * n * LSP_PER_SEGMENT})
    if calc:
        cdf = pd.DataFrame(calc)
        st.dataframe(cdf, width='stretch', hide_index=True)
        tot_fop = cur_fop + int(cdf["年間FOP"].sum())
        tot_cnt = cur_cnt + int(cdf["年間セグ"].sum())
        tot_lsp = cur_lsp + int(cdf["年間LSP"].sum()) + card_lsp
        m1, m2, m3 = st.columns(3)
        m1.metric("年末 予想FOP", f"{tot_fop:,}")
        m2.metric("年末 予想搭乗回数", f"{tot_cnt}")
        m3.metric("年末 予想LSP", f"{tot_lsp:,}")

        st.markdown("**FLY ON ステイタス判定 (暦年)**")
        srows = []
        for t in STATUS_THRESHOLDS:
            by_fop = tot_fop >= t["fop"]
            by_cnt = tot_cnt >= t["count"] and tot_fop >= t["count_fop"]
            ok = by_fop or by_cnt
            need = "" if ok else f"FOPあと {t['fop']-tot_fop:,} / 回数あと {max(0, t['count']-tot_cnt)}"
            srows.append({"ステイタス": t["name"], "FOP基準": f"{t['fop']:,}",
                          "回数基準": f"{t['count']}回+{t['count_fop']:,}FOP",
                          "判定": "✅ 達成" if ok else "—", "不足": need})
        st.dataframe(pd.DataFrame(srows), width='stretch', hide_index=True)
        lrows = [{"LSP目標": m["name"], "必要LSP": f"{m['lsp']:,}",
                  "判定": "✅ 達成" if tot_lsp >= m["lsp"] else f"あと {m['lsp']-tot_lsp:,}"} for m in LSP_MILESTONES]
        st.dataframe(pd.DataFrame(lrows), width='stretch', hide_index=True)
        st.caption("※ JGCプレミアは JGC 会員のみ。ダイヤモンドMetal は JALグループ便のみで 150,000 FOP が必要。"
                   "ステイタス基準・FOP計算式は engine/rules.py で調整可。")

    st.markdown("---")
    st.markdown("**路線別 FOP 効率ランキング** (現在データに含まれる路線、選択した運賃・座席で計算)")
    from engine.data import _load_all
    pairs = set()
    for d in _load_all().values():
        for lst in d.values():
            for f in lst:
                pairs.add((f["origin"], f["destination"], f["miles"], f["miles_est"]))
    rk = sorted({(min(a, b), max(a, b), m, e) for a, b, m, e in pairs}, key=lambda x: -x[2])
    rdf = pd.DataFrame([{"路線": f"{a}-{b}", "区間マイル": f"{m}{' ※推定' if e else ''}",
                         "FOP/セグ": fop_per_segment(m, plan_fare, plan_cabin)} for a, b, m, e in rk[:40]])
    st.dataframe(rdf, width='stretch', hide_index=True, height=400)

with tab_table:
    st.markdown("### 📋 路線別 FOP・マイル表")
    st.caption("旅行計画用。国内線は現在データの全路線、国際線は JAL 主要就航地。運賃・座席を変えると FOP が再計算されます")

    # ---------- 国内線 ----------
    st.markdown("#### 🇯🇵 国内線 (全路線)")
    from engine.data import _load_all
    pairs = {}
    for d in _load_all().values():
        for lst in d.values():
            for f in lst:
                a, b = sorted((f["origin"], f["destination"]))
                pairs[(a, b)] = (f["miles"], f["miles_est"])
    t1, t2, t3 = st.columns(3)
    dom_fare = t1.selectbox("運賃", list(FARE_CLASSES), index=2, format_func=lambda k: FARE_CLASSES[k]["label"], key="tf")
    dom_cabin = t2.selectbox("座席", list(CABIN_CLASSES), index=0, format_func=lambda k: CABIN_CLASSES[k]["label"], key="tc")
    dom_ap = t3.selectbox("空港で絞り込み", ["(全て)"] + airports(), format_func=lambda c: c if c == "(全て)" else airport_label(c), key="ta")
    rows = []
    for (a, b), (m, e) in pairs.items():
        if dom_ap != "(全て)" and dom_ap not in (a, b):
            continue
        fop1 = fop_per_segment(m, dom_fare, dom_cabin)
        rows.append({"路線": f"{a} - {b}", "区間": f"{airport_label(a).split(' - ')[1]} - {airport_label(b).split(' - ')[1]}",
                     "区間マイル": m, "推定": "※" if e else "", "LSP/セグ": LSP_PER_SEGMENT,
                     "FOP/セグ": fop1, "往復FOP": fop1 * 2, "往復LSP": LSP_PER_SEGMENT * 2,
                     "フレックス普通席": fop_per_segment(m, "Flex", "Y"), "セイバー普通席": fop_per_segment(m, "Saver", "Y"),
                     "セイバーJ": fop_per_segment(m, "Saver", "J"), "フレックスJ": fop_per_segment(m, "Flex", "J"),
                     "ファースト(Flex)": fop_per_segment(m, "Flex", "F")})
    ddf = pd.DataFrame(rows).sort_values("FOP/セグ", ascending=False)
    st.dataframe(ddf, width='stretch', hide_index=True, height=480)
    st.download_button("国内線 CSV ダウンロード", ddf.to_csv(index=False).encode("utf-8-sig"),
                       "jal_domestic_fop_table.csv", "text/csv")
    st.caption(f"{len(ddf)} 路線。※=区間マイル推定 (FDA/AMX コードシェア等)。FOP = 区間マイル × 積算率 × 2 + 搭乗ボーナス")

    # ---------- 国際線 ----------
    st.markdown("#### 🌏 国際線 (JAL 主要就航地)")
    st.caption("FOP = 区間マイル × 予約クラス積算率 × 換算率 (アジア・オセアニア 1.5 / その他 1.0) + 搭乗ボーナス。"
               "区間マイルは大圏距離からの推定 (±3%程度)。data/intl_routes.csv で公式値に上書き可")
    i1, i2 = st.columns(2)
    gw = i1.selectbox("日本側の空港", list(GATEWAYS), index=0, key="igw")
    icls = i2.selectbox("予約クラス", list(INTL_CLASSES), index=3, key="icls")
    irows = []
    for code, (name, _, _, region) in INTL_AIRPORTS.items():
        m, est = intl_miles(gw, code)
        f1 = intl_fop(m, region, icls)
        irows.append({"路線": f"{gw} - {code}", "都市": name, "地域": "アジア・オセアニア" if region == "asia" else "その他",
                      "換算率": FOP_RATE[region], "区間マイル": m, "推定": "※" if est else "",
                      "FOP/片道": f1, "FOP/往復": f1 * 2, "LSP/往復": 10,
                      "ビジネス(J)往復": intl_fop(m, region, "J/C/D/X/I (ビジネス)") * 2,
                      "PE(R)往復": intl_fop(m, region, "W/R/E (プレミアムエコノミー)") * 2,
                      "Y/B往復": intl_fop(m, region, "Y/B (エコノミー正規)") * 2,
                      "H/K/M往復": intl_fop(m, region, "H/K/M (エコノミー割引)") * 2,
                      "L/V/S往復": intl_fop(m, region, "L/V/S (エコノミー割引)") * 2})
    idf = pd.DataFrame(irows).sort_values("FOP/片道", ascending=False)
    st.dataframe(idf, width='stretch', hide_index=True, height=480)
    st.download_button("国際線 CSV ダウンロード", idf.to_csv(index=False).encode("utf-8-sig"),
                       "jal_intl_fop_table.csv", "text/csv")
    st.info("国際線航空券に含まれる日本国内区間は積算率100%・搭乗ボーナス400 (国内線換算2倍) で計算されるため、"
            "例: OKA→HND→SIN の OKA-HND 区間は国内線より有利になることがあります。")

with tab_help:
    st.markdown("""
## 🎯 このツールの目的
JALのLSP (Life Status Points) を効率よく貯めるための **スケジュール組合せ検索** です。
「この日にどんな乗継ルートが組めるか」を自動で探し、LSPが多い順に表示します。

## ⚠️ 重要な前提
- **運賃は扱いません。** JAL国内線の運賃は残席で日々変動するため、事前推定に意味がありません。
  気になるルートは各便の **JAL リンク** から実価格を確認してください。
- **データは日付ごとの実運航スケジュール** (駅探のJAL時刻表を週1回自動取得)。
  曜日限定便・運休は自動反映されますが、最終確認は必ず JAL 公式で。
- **LSP は 1搭乗 = 5pt** (距離不問)。短距離・多セグメントが有利です。

## 🔍 検索条件
| 項目 | 意味 |
|---|---|
| ① 出発空港 | ルートの出発点 (複数可) |
| ② 最終到着空港 | 空欄=任意 / 出発と同じ=往復 / 違う=片道 |
| ③ 組合せ空港 | 指定した空港間のみで組合せ。①②は無視される |

| ① | ② | ③ | 動作 |
|---|---|---|---|
| HND | 空欄 | 空欄 | HND発、終点任意 |
| HND | OKA | 空欄 | HND→…→OKA 片道 |
| HND | HND | 空欄 | HND 往復 |
| 任意 | 任意 | HND/ITM/OKA | 3空港間で自由に組合せ |

**パターン**: 日帰り(4-8セグ) / 1泊2日(6-14セグ) / 2泊3日(10-22セグ)
**最大検索時間**: 2泊3日+多セグメントは 30秒以上を推奨
**結果の多様化**: 早朝便のある特定都市に結果が偏るのを防ぎます

## 📊 結果の見方
一覧表で概要を確認 → 各ルートを展開 → 便名・時刻・JALリンク。
表示マイルは JAL公式の区間マイル表 (新路線は推定値・注記あり)。FOP は参考値です。

## 🔄 データ更新
GitHub Actions が毎週月曜に翌60日分を自動取得して `data/` を更新し、Streamlit Cloud が再デプロイします。
手動更新: GitHub → Actions → update-timetable → Run workflow。

## 💡 活用例
- **JGC Three Star (1500 LSP)**: 2泊3日 22セグ = 110 LSP × 約10回
- **出張ついで**: ① HND / ② ITM / 1泊2日 → 出張経路に乗継を足す
- **九州内**: ③ FUK, KMI, MYJ, KMJ, KOJ, OIT / 日帰り → 短距離連打
- **離島**: ① OKA / ② OKA / ③ OKA, ISG, MMY → 那覇-石垣-宮古ループ
""")
