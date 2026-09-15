"""JAL LSP Optimizer v2 — スケジュール組合せ検索 (Streamlit)

データ: data/flights_by_date.csv (駅探 JAL時刻表を GitHub Actions で週次自動取得)
"""
from datetime import date, timedelta
import pandas as pd
import streamlit as st

from engine.data import (load_meta, available_dates, airports, airport_label, reload)
from engine.optimizer import search_routes, route_to_dict

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

tab_search, tab_help = st.tabs(["🔍 検索", "📖 使い方"])

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

    if st.button("🔍 ルート検索", type="primary", use_container_width=True):
        if not bases and not allowed:
            st.error("①出発空港 または ③組合せ空港 のいずれかを選択してください。")
        elif end_date < start_date:
            st.error("終了日が開始日より前です。")
        else:
            patterns = [k for k, on in (("day", pat_day), ("1n2d", pat_1n), ("2n3d", pat_2n)) if on]
            label = {"day": "日帰り", "1n2d": "1泊2日", "2n3d": "2泊3日"}
            with st.spinner("検索中..."):
                results = {p: search_routes(bases, start_date, end_date, p, "Saver",
                                            min_segments=seg_min, max_segments=seg_max,
                                            top_n=top_n, time_budget_sec=float(budget),
                                            diversify=diversify, max_per_first_dest=max_per,
                                            final_dests=finals or None,
                                            allowed_airports=allowed or None)
                           for p in patterns}
            for p, rts in results.items():
                if not rts:
                    st.info(f"{label[p]}: 結果なし")
                    continue
                st.subheader(f"📅 {label[p]} — {len(rts)}件")
                df = pd.DataFrame([route_to_dict(r) for r in rts])
                show = df[["date", "route", "segments", "airports", "lsp", "fop", "miles"]]
                show.columns = ["日付", "ルート", "セグ", "空港数", "LSP", "FOP", "マイル"]
                st.dataframe(show, use_container_width=True, hide_index=True,
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
                                 "JAL": jal_url(s.origin, s.destination, s.flight_date),
                                 "Google": google_url(s.origin, s.destination, s.flight_date)}
                                for s in r.segments]
                        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                                     column_config={
                                         "JAL": st.column_config.LinkColumn("JAL", display_text="🔗"),
                                         "Google": st.column_config.LinkColumn("Google", display_text="🔗")})
                        st.caption(f"FOP {r.fop} / マイル {r.miles}"
                                   + ("  ※一部マイルは推定値" if est else ""))

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
