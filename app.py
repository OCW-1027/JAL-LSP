"""JAL LSP Optimizer — Streamlit Web App (日本語版).

実行:
    streamlit run app.py

スマホからアクセス (同じWiFi):
    streamlit run app.py --server.address 0.0.0.0
    スマホブラウザで http://[PC_IP]:8501
"""

from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st

from db import (init_db, get_conn, get_base_airports, get_all_airports,
                get_setting, set_setting,
                add_fare, add_booking, get_amadeus_usage)
from seed import seed
from optimizer import search_routes, route_to_dict
from fare_sources import (jal_search_url, google_flights_url,
                          fetch_amadeus_price, amadeus_quota_status)
from rules import FARE_CLASSES, PATTERNS

st.set_page_config(
    page_title="JAL LSP Optimizer",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ===== 初期化 (Streamlit Cloud 自動シード + CSV 自動インポート) =====
@st.cache_resource
def _init():
    """アプリ起動時の自動初期化.

    - DBが空なら: seed() を実行 (空港・路線データ)
    - flightsが空なら: data/ フォルダの CSV を自動インポート
    """
    import os
    init_db()

    with get_conn() as c:
        airport_count = c.execute("SELECT COUNT(*) FROM airports").fetchone()[0]
    if airport_count == 0:
        seed()

    with get_conn() as c:
        flight_count = c.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
    if flight_count == 0:
        from csv_import import import_csv_file
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        if os.path.isdir(data_dir):
            csv_files = sorted([f for f in os.listdir(data_dir)
                                if f.endswith(".csv")])
            for i, csv_file in enumerate(csv_files):
                path = os.path.join(data_dir, csv_file)
                mode = "replace_all" if i == 0 else "merge"
                try:
                    import_csv_file(path, mode=mode)
                except Exception as e:
                    print(f"CSV インポート失敗 {csv_file}: {e}")
    return True

_init()


# ===== サイドバー =====
st.sidebar.title("⚙️ 設定 / データ")

with st.sidebar.expander("🔌 Amadeus API (任意)"):
    st.caption("月2,000コール無料。チェックON時のみ呼び出し。")
    use_amadeus = st.checkbox("Amadeus API を使用",
                              value=False, key="use_amadeus")
    amadeus_id = st.text_input("Client ID",
                                value=get_setting("amadeus_client_id", ""),
                                type="password")
    amadeus_secret = st.text_input("Client Secret",
                                    value=get_setting("amadeus_client_secret", ""),
                                    type="password")
    if st.button("APIキーを保存"):
        set_setting("amadeus_client_id", amadeus_id)
        set_setting("amadeus_client_secret", amadeus_secret)
        st.success("保存しました")

    quota = amadeus_quota_status()
    color = {"ok": "🟢", "warn": "🟡", "blocked": "🔴"}[quota["level"]]
    st.markdown(f"{color} {quota['used']:,} / {quota['limit']:,}コール ({quota['pct']}%)")

with st.sidebar.expander("📅 時刻表 CSV インポート"):
    from csv_import import import_csv, routes_with_data

    st.caption("JAL時刻表 CSVをアップロード")
    uploaded = st.file_uploader("CSV ファイル", type=["csv"], key="csv_upload")
    import_mode = st.radio(
        "モード",
        options=["merge", "replace_route", "replace_all"],
        format_func=lambda m: {
            "merge": "マージ",
            "replace_route": "路線別に置換",
            "replace_all": "全置換",
        }[m],
        index=1,
    )

    if uploaded and st.button("📥 インポート実行"):
        result = import_csv(uploaded.read(), mode=import_mode)
        if result["success"]:
            st.success(f"✅ {result['imported']}件 / {result['routes_affected']}路線")
            if result["errors"]:
                with st.expander(f"⚠️ 警告 {len(result['errors'])}件"):
                    for e in result["errors"][:20]:
                        st.text(e)
        else:
            st.error("❌ インポート失敗")
            for e in result["errors"][:10]:
                st.text(e)

    routes_data = routes_with_data()
    if routes_data:
        st.caption(f"保有: {len(routes_data)}路線 / "
                   f"{sum(r['flight_count'] for r in routes_data)}便")

with st.sidebar.expander("🔧 データ管理"):
    if st.button("DB再シード (空港・路線のみ)"):
        seed()
        st.success("再シード完了")
        st.cache_resource.clear()
    if st.button("運賃キャッシュ初期化"):
        with get_conn() as c:
            c.execute("DELETE FROM fare_cache WHERE source != 'seed'")
        st.success("初期化しました")
    if st.button("⚠️ 全フライト削除"):
        with get_conn() as c:
            c.execute("DELETE FROM flights")
        st.success("削除しました")


# ===== メイン =====
st.title("✈️ JAL LSP Optimizer")
st.caption("LSP優先 / チェーン検索 / 価格は参考用")

tabs = st.tabs(["🔍 検索", "💰 運賃", "📋 予約", "📊 キャッシュ", "📖 使い方"])


# ===== Tab 1: 検索 =====
with tabs[0]:
    # 簡潔な案内 (折りたたみ可)
    with st.expander("📖 はじめての方へ — このツールの使い方", expanded=False):
        st.markdown("""
**このツールの目的**: JALのLSP(生涯ステータスポイント)を効率よく貯めるための
**フライトスケジュール組合せ検索**ツールです。

**重要なポイント**:
- 🎯 **メインはスケジュールの組合せ確認** — 「この日にこのルートが組めるか」を見るためのツール
- 💴 **運賃は参考値のみで意味は薄い** — JALの運賃は残席状況で日々大きく変動するため、
  本ツールの運賃表示は当てになりません。実際の価格は **JALリンクから直接検索** してください
- ✈️ **LSPは1セグメント = 5点** — 距離に関係なく、搭乗回数(セグメント数)で決まります

**詳しい使い方**は **「📖 使い方」タブ** をご覧ください。
        """)

    all_bases = get_base_airports()
    base_codes = [b["code"] for b in all_bases]
    base_labels = {b["code"]: f"{b['code']} - {b['name_jp']}" for b in all_bases}

    # 条件 1: 出発ベース
    selected_bases = st.multiselect(
        "① 出発ベース空港 (出発・帰着地)",
        options=base_codes,
        default=["HND"],
        format_func=lambda c: base_labels.get(c, c),
        help="ルートの出発・帰着空港。複数選択可。",
    )

    # 条件 2 & 3: 全空港プール
    all_aps = get_all_airports()
    ap_codes = [a["code"] for a in all_aps]
    ap_labels = {a["code"]: f"{a['code']} - {a['name_jp']}" for a in all_aps}

    final_dests = st.multiselect(
        "② 最終到着空港 (任意)",
        options=ap_codes,
        default=[],
        format_func=lambda c: ap_labels.get(c, c),
        help="ルートの最終到着空港。空欄なら任意の空港で終了 (片道OK)。"
             "出発と同じ空港を選ぶと往復になります。"
             "例: HND出発+OKA到着 → HND→...→OKA の片道ルート",
    )

    allowed_airports = st.multiselect(
        "③ 組合せ空港 — 使用可能空港プール (任意)",
        options=ap_codes,
        default=[],
        format_func=lambda c: ap_labels.get(c, c),
        help="ここで選択した空港間でのみ飛行。空欄なら全空港使用可。"
             "③を指定すると①出発空港・②最終到着空港の指定は無視され、"
             "③の中から自由に出発・到着・経由が組合せされます。"
             "例: HND, ITM, OKAのみ選択 → この3空港間で自由に組合せ",
    )

    cdate1, cdate2 = st.columns(2)
    with cdate1:
        start_date = st.date_input("開始日",
                                   value=date.today() + timedelta(days=14))
    with cdate2:
        end_date = st.date_input("終了日",
                                 value=date.today() + timedelta(days=16))

    fare_class = st.selectbox(
        "運賃クラス (参考用)",
        options=list(FARE_CLASSES.keys()),
        format_func=lambda c: FARE_CLASSES[c]["label"],
        index=1,
    )

    # パターン選択
    cp1, cp2, cp3 = st.columns(3)
    pattern_day = cp1.checkbox("日帰り", value=True)
    pattern_1n = cp2.checkbox("1泊2日", value=True)
    pattern_2n = cp3.checkbox("2泊3日", value=False)

    # セグメント範囲
    seg_range = st.slider("セグメント数の範囲", 2, 24, (4, 12),
                          help="LSP回収には4以上推奨。"
                               "2泊3日では20セグ以上も可能 (検索時間を増やす)")
    min_segments, max_segments = seg_range

    cn1, cn2 = st.columns(2)
    top_n = cn1.slider("上位N件", 5, 50, 15)
    time_budget = cn2.slider("最大検索時間(秒)", 2, 60, 8,
                              help="複雑な検索 (2泊3日+多セグメント) は30秒+必要")

    cd1, cd2 = st.columns(2)
    diversify = cd1.checkbox("結果の多様化 (初訪都市別に分散)",
                              value=True,
                              help="同じ初訪都市で始まるルートが結果を占めないよう分散")
    max_per_first = cd2.slider("初訪都市別の最大表示数",
                                 1, 5, 2,
                                 help="多様化ON時、同じ初訪都市のルートは上位N件まで")

    # 検索ボタン
    if st.button("🔍 ルート検索", type="primary", width='stretch'):
        if not selected_bases and not allowed_airports:
            st.error("①出発空港または③組合せ空港のいずれかを選択してください。")
        elif end_date < start_date:
            st.error("終了日が開始日より前です。")
        else:
            with st.spinner("検索中..."):
                results = {}
                # 빈 리스트는 None으로 (필터 미적용)
                _final = final_dests if final_dests else None
                _allowed = allowed_airports if allowed_airports else None

                if pattern_day:
                    results["day"] = search_routes(
                        selected_bases, start_date, end_date,
                        "day", fare_class,
                        min_segments=min_segments,
                        max_segments=max_segments,
                        top_n=top_n,
                        time_budget_sec=float(time_budget),
                        diversify=diversify,
                        max_per_first_dest=max_per_first,
                        final_dests=_final,
                        allowed_airports=_allowed,
                    )
                if pattern_1n:
                    results["1n2d"] = search_routes(
                        selected_bases, start_date, end_date,
                        "1n2d", fare_class,
                        min_segments=min_segments,
                        max_segments=max_segments,
                        top_n=top_n,
                        time_budget_sec=float(time_budget),
                        diversify=diversify,
                        max_per_first_dest=max_per_first,
                        final_dests=_final,
                        allowed_airports=_allowed,
                    )
                if pattern_2n:
                    results["2n3d"] = search_routes(
                        selected_bases, start_date, end_date,
                        "2n3d", fare_class,
                        min_segments=min_segments,
                        max_segments=max_segments,
                        top_n=top_n,
                        time_budget_sec=float(time_budget),
                        diversify=diversify,
                        max_per_first_dest=max_per_first,
                        final_dests=_final,
                        allowed_airports=_allowed,
                    )

            # 結果表示
            pattern_jp = {"day": "日帰り", "1n2d": "1泊2日", "2n3d": "2泊3日"}
            for ptn, rts in results.items():
                if not rts:
                    st.info(f"{pattern_jp.get(ptn, ptn)}: 結果なし")
                    continue

                st.subheader(f"📅 {pattern_jp.get(ptn, ptn)} — {len(rts)}件")
                df = pd.DataFrame([route_to_dict(r) for r in rts])

                display = df[["date", "route", "segments", "airports",
                               "lsp", "fop", "miles"]].copy()
                display.columns = ["日付", "ルート", "セグ", "空港数",
                                    "LSP", "FOP", "マイル"]
                st.dataframe(display, width='stretch', hide_index=True,
                             height=min(420, 50 + len(display) * 35))

                st.markdown(f"**全ルート詳細 ({len(rts)}件)**")
                st.caption("各ルートを展開してフライト詳細・JALリンクを確認。"
                           "価格は参考値で正確ではないため、JALで直接検索してください。")
                for i, r in enumerate(rts):
                    route_path = " → ".join(
                        [r.segments[0].origin] +
                        [s.destination for s in r.segments]
                    ) if r.segments else ""
                    route_short = (route_path[:80] + "..."
                                   if len(route_path) > 80 else route_path)
                    with st.expander(
                        f"#{i+1}  {r.segments[0].flight_date}  "
                        f"セグ{r.num_segments}/空港{r.num_airports}/LSP{r.lsp}  "
                        f"| {route_short}"
                    ):
                        st.markdown(f"**全ルート**: {route_path}")
                        seg_rows = []
                        for s in r.segments:
                            seg_rows.append({
                                "便名": s.flight_no,
                                "日付": s.flight_date.isoformat(),
                                "区間": f"{s.origin}→{s.destination}",
                                "出発": s.dep_time,
                                "到着": s.arr_time,
                                "JAL": jal_search_url(s.origin, s.destination,
                                                       s.flight_date),
                                "Google": google_flights_url(
                                    s.origin, s.destination, s.flight_date),
                            })
                        seg_df = pd.DataFrame(seg_rows)
                        st.dataframe(
                            seg_df,
                            column_config={
                                "JAL": st.column_config.LinkColumn(
                                    "JAL", display_text="🔗"),
                                "Google": st.column_config.LinkColumn(
                                    "Google", display_text="🔗"),
                            },
                            width='stretch', hide_index=True,
                        )
                        st.caption(
                            f"参考価格 (推定): ¥{r.price:,} / "
                            f"FOP {r.fop} / マイル {r.miles}"
                        )


# ===== Tab 2: 運賃入力 =====
with tabs[1]:
    st.markdown("### 💰 運賃入力")
    st.caption("JAL/Googleで見た価格を保存 → 次回検索の参考値として使用")

    airports = get_all_airports()
    codes = [a["code"] for a in airports]
    labels = {a["code"]: f"{a['code']} - {a['name_jp']}" for a in airports}

    cf1, cf2 = st.columns(2)
    f_origin = cf1.selectbox("出発", codes,
                              format_func=lambda c: labels[c],
                              key="fare_origin")
    f_dest = cf2.selectbox("到着", codes,
                            format_func=lambda c: labels[c],
                            index=1, key="fare_dest")

    cf3, cf4 = st.columns(2)
    f_date = cf3.date_input("搭乗日",
                             value=date.today() + timedelta(days=14),
                             key="fare_date")
    f_class = cf4.selectbox("運賃", list(FARE_CLASSES.keys()),
                             format_func=lambda c: FARE_CLASSES[c]["label"],
                             key="fare_class_input")

    f_price = st.number_input("価格 (円)", min_value=0, step=100,
                               key="fare_price")
    f_notes = st.text_input("メモ", key="fare_notes")

    if st.button("💾 保存", type="primary", width='stretch'):
        if f_price <= 0:
            st.error("価格を入力してください。")
        elif f_origin == f_dest:
            st.error("出発地と到着地が同じです。")
        else:
            add_fare(f_origin, f_dest, f_date.isoformat(),
                     f_class, int(f_price),
                     source="manual", confidence=2,
                     notes=f_notes or "")
            st.success(f"✅ {f_origin}→{f_dest} ¥{f_price:,} 保存しました")


# ===== Tab 3: 予約記録 =====
with tabs[2]:
    st.markdown("### 📋 予約記録")

    airports = get_all_airports()
    codes = [a["code"] for a in airports]
    labels = {a["code"]: f"{a['code']} - {a['name_jp']}" for a in airports}

    cb1, cb2 = st.columns(2)
    b_flight_no = cb1.text_input("便名", key="bk_flight")
    b_pnr = cb2.text_input("PNR", key="bk_pnr")

    cb3, cb4 = st.columns(2)
    b_origin = cb3.selectbox("出発", codes,
                              format_func=lambda c: labels[c],
                              key="bk_origin")
    b_dest = cb4.selectbox("到着", codes,
                            format_func=lambda c: labels[c],
                            index=1, key="bk_dest")

    cb5, cb6 = st.columns(2)
    b_date = cb5.date_input("搭乗日",
                             value=date.today() + timedelta(days=14),
                             key="bk_date")
    b_class = cb6.selectbox("運賃", list(FARE_CLASSES.keys()),
                             format_func=lambda c: FARE_CLASSES[c]["label"],
                             key="bk_class")
    b_price = st.number_input("支払額 (円)", min_value=0, step=100, key="bk_price")
    b_notes = st.text_input("メモ", key="bk_notes")

    if st.button("✅ 登録", type="primary", width='stretch'):
        if not b_flight_no or b_price <= 0:
            st.error("便名と価格は必須です。")
        else:
            add_booking(b_flight_no, b_origin, b_dest, b_date.isoformat(),
                        b_class, int(b_price), b_pnr or "", b_notes or "")
            st.success(f"✅ 登録しました")

    st.markdown("---")
    st.markdown("**最近の予約**")
    with get_conn() as c:
        rows = c.execute(
            "SELECT * FROM bookings ORDER BY booked_at DESC LIMIT 30"
        ).fetchall()
    if rows:
        df_b = pd.DataFrame([dict(r) for r in rows])
        st.dataframe(df_b, width='stretch', hide_index=True)
    else:
        st.info("登録された予約なし")


# ===== Tab 4: キャッシュ状況 =====
with tabs[3]:
    st.markdown("### 📊 キャッシュ状況")
    with get_conn() as c:
        rows = c.execute("""
            SELECT origin, destination, fare_class,
                   COUNT(*) as records,
                   AVG(price_jpy) as avg_price,
                   MIN(price_jpy) as min_price,
                   MAX(price_jpy) as max_price,
                   MAX(confidence) as best_confidence
            FROM fare_cache
            GROUP BY origin, destination, fare_class
            ORDER BY origin, destination, fare_class
        """).fetchall()
    if rows:
        df_c = pd.DataFrame([dict(r) for r in rows])
        df_c["avg_price"] = df_c["avg_price"].apply(lambda x: f"¥{int(x):,}")
        df_c["min_price"] = df_c["min_price"].apply(lambda x: f"¥{x:,}")
        df_c["max_price"] = df_c["max_price"].apply(lambda x: f"¥{x:,}")
        df_c.columns = ["出発", "到着", "運賃", "件数",
                        "平均", "最低", "最高", "★最大"]
        st.dataframe(df_c, width='stretch', hide_index=True)
    else:
        st.info("キャッシュは空です")


# ===== Tab 5: 使い方ガイド =====
with tabs[4]:
    st.markdown("# 📖 使い方ガイド")
    st.caption("各項目の意味と活用方法を詳しく説明します")

    # ===== 1. 目的とコンセプト =====
    st.markdown("## 🎯 このツールの目的")
    st.markdown("""
**JALのLSP (Life Status Points / 生涯ステータスポイント) を効率よく貯めるための
フライトスケジュール組合せ検索ツール**です。

JGC Three Star等の高ステータスを目指す方が、
「この日程・この空港でどんなルートが組めるか?」をシミュレーションするために使います。
    """)

    st.markdown("---")

    # ===== 2. 重要な前提 =====
    st.markdown("## ⚠️ 重要な前提")

    st.error("""
**運賃は参考値で、ほとんど意味がありません**

JAL国内線の運賃は予約時の残席状況によって日々大きく変動します。
このツールに表示される価格は固定的な推定値で、実際の購入価格とは異なります。

**正しい使い方**: ツールでスケジュール組合せを確認 → 気になるルートの
**JALリンクをクリックして実際の価格を直接JAL公式で確認** してください。
    """)

    st.success("""
**メインはスケジュール組合せの発見です**

このツールの本当の価値は、
- どの日にどんなセグメント数のルートが組めるか
- どの空港を経由すれば効率よくLSPが貯まるか
- MCT (最短乗継時間) を満たす実現可能なルートはどれか

を **自動的にシミュレーション** することにあります。
    """)

    st.markdown("---")

    # ===== 3. LSP / FOP の仕組み =====
    st.markdown("## ✈️ LSP / FOP の基本")
    st.markdown("""
| 指標 | 意味 | 計算方法 |
|---|---|---|
| **LSP** | Life Status Points (生涯ポイント) | **1搭乗 = 5点** (距離に関係なく一律) |
| **FOP** | Fly On Points (年次ステータス用) | 区間マイル × 運賃倍率 + ボーナス |
| **マイル** | フライトマイル | 区間マイル × 運賃倍率 |

**LSPの効率を上げるには「短距離・多セグメント」が有利**です。
例: HND-NGO 往復 (2セグ・LSP 10) より、HND-FUK-OKA-HND (3セグ・LSP 15) が良い
    """)

    st.markdown("---")

    # ===== 4. 検索条件 =====
    st.markdown("## 🔍 検索条件の使い方")

    st.markdown("### ① 出発ベース空港")
    st.markdown("""
ルートの **出発空港** を指定します。複数選択可能。

- 通常は自宅 / 勤務地に近い空港 (HND, ITM, OKA など) を選択
- 複数選択すると、それぞれを起点とするルートを並列検索
- ②③ が空欄の場合: **同じ空港に戻る往復ルート** を検索
    """)

    st.markdown("### ② 最終到着空港 (任意)")
    st.markdown("""
ルートの **最終到着空港** を指定します。空欄可能。

| 設定 | 動作 |
|---|---|
| 空欄 | 任意の空港で終了 (システムが最適なものを選択) |
| 出発と同じ空港 | **往復ルート** (最も一般的) |
| 出発と違う空港 | **片道ルート** (例: HND出発 → OKA到着) |

**活用例**: 「出張で大阪に行くついでにLSPを稼ぎたい」
→ ① HND, ② ITM を指定 → 東京から大阪に至る間に
セグメントを稼ぐルートを提案
    """)

    st.markdown("### ③ 組合せ空港 — 使用可能空港プール (任意)")
    st.markdown("""
ルートで **使用できる空港を制限** します。空欄可能。

| 設定 | 動作 |
|---|---|
| 空欄 | 全空港使用可能 (デフォルト) |
| 指定 | **指定した空港間でのみ飛行**。①②は無視されます |

**活用例 1**: 「九州内だけで効率よく回りたい」
→ ③ に FUK, KMI, MYJ, KMJ, KOJ を指定 → 九州内ルートのみ表示

**活用例 2**: 「主要幹線だけで組合せたい」
→ ③ に HND, ITM, OKA, FUK, CTS を指定 → 主要5空港間のルートのみ
    """)

    st.markdown("### 4つの基本パターン")
    st.markdown("""
| ① 出発 | ② 到着 | ③ 組合せ | 動作 |
|---|---|---|---|
| HND | (空欄) | (空欄) | HND発、任意の空港着 |
| HND | OKA | (空欄) | HND→...→OKA の片道 |
| HND | HND | (空欄) | HND往復 |
| (任意) | (任意) | HND/ITM/OKA | ③の空港間で自由に組合せ (①②無視) |
    """)

    st.markdown("---")

    # ===== 5. パターン =====
    st.markdown("## 📅 パターン (滞在期間)")
    st.markdown("""
| パターン | 意味 | 想定セグメント数 |
|---|---|---|
| **日帰り** | 朝出発・夜帰着 (同日完結) | 4-8セグ |
| **1泊2日** | 1泊して翌日帰着 | 6-14セグ |
| **2泊3日** | 2泊して3日目帰着 | 10-22セグ |

長期パターンほど多くのセグメントを稼げますが、
体力的・スケジュール的な負担も大きくなります。
    """)

    st.markdown("---")

    # ===== 6. その他のオプション =====
    st.markdown("## ⚙️ その他のオプション")

    st.markdown("""
**セグメント数の範囲**: 検索するルートの最小・最大セグメント数
- 4以上を推奨 (LSP回収には十分なセグメント数が必要)
- 上限を上げるほど検索時間も延長

**上位N件**: 表示する結果の数 (デフォルト15件)

**最大検索時間(秒)**: アルゴリズムの探索時間上限
- 簡単な検索なら2-5秒、複雑な検索 (2泊3日+多セグ) は30秒以上が必要

**結果の多様化**: 同じ初訪都市で始まるルートが結果を独占しないよう分散
- ON: 様々な空港で始まるルートを表示 (推奨)
- OFF: スコア順そのまま (KMJ等の早朝便起点に偏る可能性)
    """)

    st.markdown("---")

    # ===== 7. 結果の見方 =====
    st.markdown("## 📊 結果の見方")
    st.markdown("""
検索結果は2つの形式で表示されます:

### 上部: 一覧表
全結果のサマリー (日付, ルート, セグ数, 空港数, LSP, FOP, マイル)。
ソート・絞り込みが可能。

### 下部: 詳細展開エリア
各ルートをクリックで展開すると:
- フライトごとの **便名・出発時刻・到着時刻**
- **🔗 JAL** リンク → JAL公式サイトで実際の運賃を確認
- **🔗 Google** リンク → Google Flightsで他社含む価格比較

**実際の予約手順**:
1. ツールで気になるルート組合せを発見
2. 各セグメントの **JALリンクをクリック** して実価格を確認
3. 全セグメントの価格を合計し、予算内ならJAL公式で予約
    """)

    st.markdown("---")

    # ===== 8. 注意事項 =====
    st.markdown("## ⚠️ 注意事項")
    st.markdown("""
**運航日について**:
本ツールは時刻表データを **毎日運航 (1111111)** として登録しています。
実際には特定曜日のみ運航する便もあるため、
**本人の搭乗日に運航しているかは必ずJAL公式で確認** してください。

**運賃について** (再掲):
表示される運賃は固定推定値で、実際とは異なります。**参考値以上の意味はありません**。

**MCT (最短乗継時間)**:
本ツールは安全マージンを含めた MCT を考慮していますが、
実際の予約時には JAL の規定で乗継不可と判定される場合があります。

**コードシェア便**:
JL/AMX等の特定日運休便は除外していますが、運航ステータスは
予約時に必ずご確認ください。
    """)

    st.markdown("---")

    # ===== 9. 活用シナリオ =====
    st.markdown("## 💡 活用シナリオ例")

    with st.expander("シナリオ 1: JGC Three Star 達成までの計画"):
        st.markdown("""
**目標**: 1500 LSP達成

**現状確認**: JAL公式で現在のLSPを確認 (例: 488 LSP)

**残り必要**: 1500 - 488 = 1012 LSP

**戦略**:
- 2泊3日 22セグ = LSP 110点 を約9-10回 → 達成可能
- または 1泊2日 14セグ = LSP 70点 を 約15回
- 体力・予算と相談して計画

**ツールの使い方**:
- ① HND (本人の出発空港)
- ② HND (往復)
- ③ 空欄 (全空港使用)
- パターン: 2泊3日
- セグメント範囲: 18-22
- 最大検索時間: 30秒
        """)

    with st.expander("シナリオ 2: 出張ついでにLSPを稼ぐ"):
        st.markdown("""
**状況**: 月曜HND発、火曜ITM着で出張

**ツールの使い方**:
- ① HND
- ② ITM
- ③ 空欄
- パターン: 1泊2日
- セグメント範囲: 6-12

→ 出張のついでに6-12セグメント稼ぐルートを提案
        """)

    with st.expander("シナリオ 3: 九州内ルートでまったり稼ぐ"):
        st.markdown("""
**状況**: 福岡周辺で短距離を多数搭乗

**ツールの使い方**:
- ① 空欄
- ② 空欄
- ③ FUK, KMI, MYJ, KMJ, KOJ, OIT
- パターン: 日帰り or 1泊2日
- セグメント範囲: 6-10

→ 九州内の短距離フライトのみで効率よくLSPを稼ぐルート
        """)

    with st.expander("シナリオ 4: 沖縄で離島めぐりLSP稼ぎ"):
        st.markdown("""
**状況**: 沖縄旅行ついでに離島往復でLSP稼ぎ

**ツールの使い方**:
- ① OKA
- ② OKA (往復)
- ③ 空欄 (または OKA, ISG, MMY のみに制限)
- パターン: 日帰り or 1泊2日

→ 那覇-石垣-那覇-宮古-那覇 のような離島ルートを提案
        """)

    st.markdown("---")
    st.caption("📝 改善要望や不具合報告は GitHub: https://github.com/OCW-1027/JAL-LSP")
