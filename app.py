"""JAL LSP Optimizer v2 — スケジュール組合せ検索 (Streamlit)

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

st.set_page_config(page_title="JAL LSP Optimizer", page_icon="✈️",
                   layout="wide", initial_sidebar_state="collapsed")

meta = load_meta()
dates = available_dates()
HUBS = ["HND", "ITM", "KIX", "NGO", "CTS", "FUK", "OKA"]


def jal_url(o, d, dt: date) -> str:
    return (f"https://www.jal.co.jp/jp/ja/dom/booking/?dep={o}&arr={d}"
            f"&date={dt.strftime('%Y%m%d')}")


def google_url(o, d, dt: date) -> str:
    return f"https://www.google.com/travel/flights?q=Flights%20from%20{o}%20to%20{d}%20on%20{dt.isoformat()}"


# ===== サイドバー: データ状態 =====
with st.sidebar:
    st.title("📦 データ")
    if dates:
        st.markdown(f"**取得日**: {meta.get('fetched_at', '?')}  \n"
                    f"**カバー期間**: {dates[0]} 〜 {dates[-1]}  \n"
                    f"**便数**: {meta.get('flights', 0):,} / **空港**: {meta.get('airports', 0)}")
        st.caption("出典: 駅探 JAL時刻表 (週1回 GitHub Actions で自動更新)")
    else:
        st.error("データ未取得。`python etl/fetch_ekitan.py` を実行するか、"
                 "GitHub Actions の update-timetable を手動実行してください。")
    if st.button("再読込"):
        reload()
        st.rerun()

# ===== メイン =====
st.title("✈️ JAL LSP Optimizer")
st.caption("LSP最大化のためのフライト組合せ検索 ― 運賃は扱いません (JALで直接確認)")

tab_search, tab_plan, tab_help = st.tabs(["🔍 検索", "📈 年間プラン", "📖 使い方"])

with tab_search:
    with st.expander("📖 はじめての方へ", expanded=False):
        st.markdown("""
- 🎯 **目的**: 指定日に組める JAL国内線の乗継ルートを自動探索し、**LSP (1搭乗=5pt)** が多い順に提示
- 📅 **データは日付ごとの実運航スケジュール** (曜日運航・運休を反映)。カバー期間外の日付は検索できません
- 💴 **運賃は表示しません** — 残席で日々変動するため無意味。各便の JAL リンクから直接確認してください
- ✅ 予約前に必ず JAL 公式で運航・乗継可否をご確認ください
""")

    if not dates:
        st.stop()
    dmin, dmax = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    ap_codes = airports()
    hub_codes = [c for c in HUBS if c in ap_codes]

    c1, c2 = st.columns(2)
    bases = c1.multiselect("① 出発空港", ap_codes, default=["HND"] if "HND" in ap_codes else [],
                           format_func=airport_label,
                           help="ルートの出発点。③を指定した場合は無視されます")
    finals = c2.multiselect("② 最終到着空港 (任意)", ap_codes, default=[], format_func=airport_label,
                            help="空欄=任意で終了。出発と同じ空港=往復。違う空港=片道")
    allowed = st.multiselect("③ 組合せ空港 — 使用可能空港プール (任意)", ap_codes, default=[],
                             format_func=airport_label,
                             help="指定するとこの空港間のみで組合せ (①②は無視)。例: HND, ITM, OKA")
    if st.button("主要空港をセット", help="HND/ITM/KIX/NGO/CTS/FUK/OKA を③に入れる"):
        st.session_state["_allowed_preset"] = hub_codes
        st.rerun()

    d1, d2 = st.columns(2)
    default_start = max(dmin, date.today() + timedelta(days=1))
    start_date = d1.date_input("開始日", value=min(default_start, dmax), min_value=dmin, max_value=dmax)
    end_date = d2.date_input("終了日", value=min(start_date + timedelta(days=2), dmax),
                             min_value=dmin, max_value=dmax)

    o1, o2, o3 = st.columns(3)
    objective = o1.radio("目的", ["lsp", "fop", "count"], horizontal=True,
                         format_func=lambda k: {"lsp": "LSP優先", "fop": "FOP優先", "count": "回数優先"}[k],
                         help="LSP: 搭乗回数×5を最大化 / FOP: 年間ステイタス用ポイントを最大化 (長距離が有利) / 回数: 短時間で搭乗回数")
    fare = o2.selectbox("運賃 (FOP計算用)", list(FARE_CLASSES), index=2, format_func=lambda k: FARE_CLASSES[k]["label"])
    cabin = o3.selectbox("座席 (FOP計算用)", list(CABIN_CLASSES), index=0, format_func=lambda k: CABIN_CLASSES[k]["label"])

    p1, p2, p3 = st.columns(3)
    pat_day = p1.checkbox("日帰り", True)
    pat_1n = p2.checkbox("1泊2日", True)
    pat_2n = p3.checkbox("2泊3日", False)

    seg_min, seg_max = st.slider("セグメント数の範囲", 2, 24, (4, 12))
    s1, s2 = st.columns(2)
    top_n = s1.slider("表示件数", 5, 50, 15)
    budget = s2.slider("最大検索時間(秒)", 2, 60, 8)
    v1, v2 = st.columns(2)
    diversify = v1.checkbox("結果の多様化", True, help="同じ初訪都市・終点の組合せに偏らないよう分散")
    max_per = v2.slider("同一組合せの最大表示数", 1, 5, 2)

    if st.button("🔍 ルート検索", type="primary", width='stretch'):
        if not bases and not allowed:
            st.error("①出発空港 または ③組合せ空港 のいずれかを選択してください。")
        elif end_date < start_date:
            st.error("終了日が開始日より前です。")
        else:
            patterns = [k for k, on in (("day", pat_day), ("1n2d", pat_1n), ("2n3d", pat_2n)) if on]
            label = {"day": "日帰り", "1n2d": "1泊2日", "2n3d": "2泊3日"}
            with st.spinner("検索中..."):
                results = {p: search_routes(bases, start_date, end_date, p, fare,
                                            min_segments=seg_min, max_segments=seg_max,
                                            top_n=top_n, time_budget_sec=float(budget),
                                            diversify=diversify, max_per_first_dest=max_per,
                                            final_dests=finals or None,
                                            allowed_airports=allowed or None,
                                            cabin=cabin, objective=objective)
                           for p in patterns}
            for p, rts in results.items():
                if not rts:
                    st.info(f"{label[p]}: 結果なし")
                    continue
                st.subheader(f"📅 {label[p]} — {len(rts)}件")
                df = pd.DataFrame([route_to_dict(r) for r in rts])
                df["fop_seg"] = (df["fop"] / df["segments"]).round(0).astype(int)
                show = df[["date", "route", "segments", "airports", "lsp", "fop", "fop_seg", "miles"]]
                show.columns = ["日付", "ルート", "セグ", "空港数", "LSP", "FOP", "FOP/セグ", "マイル"]
                st.dataframe(show, width='stretch', hide_index=True,
                             height=min(420, 50 + len(show) * 35))
                st.markdown(f"**全ルート詳細 ({len(rts)}件)** — 各便の JAL リンクで運賃・運航を確認")
                for i, r in enumerate(rts):
                    path = " → ".join([r.segments[0].origin] + [s.destination for s in r.segments])
                    est = any(s.miles and getattr(s, "miles_est", False) for s in r.segments)
                    with st.expander(f"#{i+1} {r.segments[0].flight_date} セグ{r.num_segments}"
                                     f"/空港{r.num_airports}/LSP{r.lsp} | {path[:80]}"):
                        rows = [{"便名": s.flight_no, "日付": s.flight_date.isoformat(),
                                 "区間": f"{s.origin}→{s.destination}", "出発": s.dep_time,
                                 "到着": s.arr_time, "マイル": s.miles,
                                 "FOP": fop_per_segment(s.miles, fare, cabin),
                                 "JAL": jal_url(s.origin, s.destination, s.flight_date),
                                 "Google": google_url(s.origin, s.destination, s.flight_date)}
                                for s in r.segments]
                        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True,
                                     column_config={
                                         "JAL": st.column_config.LinkColumn("JAL", display_text="🔗"),
                                         "Google": st.column_config.LinkColumn("Google", display_text="🔗")})
                        st.caption(f"FOP {r.fop} / マイル {r.miles}"
                                   + ("  ※一部マイルは推定値" if est else ""))

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
