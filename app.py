"""JAL LSP Optimizer — Streamlit Web App.

실행:
    streamlit run app.py

휴대폰에서 접속하려면:
    streamlit run app.py --server.address 0.0.0.0
    같은 WiFi의 휴대폰 브라우저에서 http://[PC_IP]:8501
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
    initial_sidebar_state="collapsed",  # 모바일 친화: 사이드바 닫혀서 시작
)


# ===== 초기화 (Streamlit Cloud 자동 시드 + CSV 임포트) =====
@st.cache_resource
def _init():
    """앱 시작 시 자동 초기화.

    - DB가 비어있으면: seed() 실행 (공항·노선 데이터)
    - flights 테이블이 비어있으면: data/ 폴더 CSV 자동 임포트
      (Streamlit Cloud는 재시작 시 DB가 사라질 수 있어 자동 복원 필요)
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
        # data/ 폴더의 CSV 자동 임포트
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
                    print(f"CSV 임포트 실패 {csv_file}: {e}")
    return True

_init()


# ===== 사이드바 =====
st.sidebar.title("⚙️ 설정 / 데이터")

with st.sidebar.expander("🔌 Amadeus API (선택)"):
    st.caption("월 2,000콜 무료. 체크박스 켤 때만 호출.")
    use_amadeus = st.checkbox("Amadeus API 사용",
                              value=False, key="use_amadeus")
    amadeus_id = st.text_input("Client ID",
                                value=get_setting("amadeus_client_id", ""),
                                type="password")
    amadeus_secret = st.text_input("Client Secret",
                                    value=get_setting("amadeus_client_secret", ""),
                                    type="password")
    if st.button("API 키 저장"):
        set_setting("amadeus_client_id", amadeus_id)
        set_setting("amadeus_client_secret", amadeus_secret)
        st.success("저장됨")

    quota = amadeus_quota_status()
    color = {"ok": "🟢", "warn": "🟡", "blocked": "🔴"}[quota["level"]]
    st.markdown(f"{color} {quota['used']:,} / {quota['limit']:,}콜 ({quota['pct']}%)")

with st.sidebar.expander("📅 시각표 CSV 임포트"):
    from csv_import import import_csv, routes_with_data

    st.caption("JAL 시각표 CSV 업로드.")
    uploaded = st.file_uploader("CSV 파일", type=["csv"], key="csv_upload")
    import_mode = st.radio(
        "모드",
        options=["merge", "replace_route", "replace_all"],
        format_func=lambda m: {
            "merge": "병합",
            "replace_route": "노선별 교체",
            "replace_all": "전체 교체",
        }[m],
        index=1,
    )

    if uploaded and st.button("📥 임포트 실행"):
        result = import_csv(uploaded.read(), mode=import_mode)
        if result["success"]:
            st.success(f"✅ {result['imported']}건 / {result['routes_affected']}개 노선")
            if result["errors"]:
                with st.expander(f"⚠️ 경고 {len(result['errors'])}건"):
                    for e in result["errors"][:20]:
                        st.text(e)
        else:
            st.error("❌ 임포트 실패")
            for e in result["errors"][:10]:
                st.text(e)

    routes_data = routes_with_data()
    if routes_data:
        st.caption(f"보유: {len(routes_data)}개 노선 / "
                   f"{sum(r['flight_count'] for r in routes_data)}편")

with st.sidebar.expander("🔧 데이터 관리"):
    if st.button("DB 재시드 (공항·노선만)"):
        seed()
        st.success("재시드 완료")
        st.cache_resource.clear()
    if st.button("운임 캐시 초기화"):
        with get_conn() as c:
            c.execute("DELETE FROM fare_cache WHERE source != 'seed'")
        st.success("초기화됨")
    if st.button("⚠️ 모든 항공편 삭제"):
        with get_conn() as c:
            c.execute("DELETE FROM flights")
        st.success("삭제됨")


# ===== 메인 =====
st.title("✈️ JAL LSP Optimizer")
st.caption("LSP 우선 / 체인 검색 / 가격은 참고용")

tabs = st.tabs(["🔍 검색", "💰 운임", "📋 예약", "📊 캐시"])


# ===== Tab 1: 검색 =====
with tabs[0]:
    # 입력은 세로로 쌓아서 모바일 친화
    all_bases = get_base_airports()
    base_codes = [b["code"] for b in all_bases]
    base_labels = {b["code"]: f"{b['code']} - {b['name_ko']}" for b in all_bases}

    selected_bases = st.multiselect(
        "출발 베이스 공항",
        options=base_codes,
        default=["HND"],
        format_func=lambda c: base_labels.get(c, c),
    )

    cdate1, cdate2 = st.columns(2)
    with cdate1:
        start_date = st.date_input("시작일",
                                   value=date.today() + timedelta(days=14))
    with cdate2:
        end_date = st.date_input("종료일",
                                 value=date.today() + timedelta(days=16))

    fare_class = st.selectbox(
        "운임 클래스 (참고용)",
        options=list(FARE_CLASSES.keys()),
        format_func=lambda c: FARE_CLASSES[c]["label"],
        index=1,
    )

    # 패턴 선택
    cp1, cp2, cp3 = st.columns(3)
    pattern_day = cp1.checkbox("당일", value=True)
    pattern_1n = cp2.checkbox("1박2일", value=True)
    pattern_2n = cp3.checkbox("2박3일", value=False)

    # 세그먼트 범위
    seg_range = st.slider("세그먼트 수 범위", 2, 24, (4, 12),
                          help="LSP 회수 채우려면 4 이상 권장. "
                               "2박3일에 20세그 이상 가능 (검색시간 늘려야 함)")
    min_segments, max_segments = seg_range

    cn1, cn2 = st.columns(2)
    top_n = cn1.slider("상위 N개", 5, 50, 15)
    time_budget = cn2.slider("최대 검색시간(초)", 2, 60, 8,
                              help="복잡한 검색(2박3일+많은 세그)은 30초+ 필요")

    cd1, cd2 = st.columns(2)
    diversify = cd1.checkbox("결과 다양화 (첫 도시별 분산)",
                              value=True,
                              help="같은 첫 도시로 시작하는 루트가 결과를 점령하지 않도록 분산")
    max_per_first = cd2.slider("첫 도시별 최대 노출",
                                 1, 5, 2,
                                 help="다양화 ON일 때, 같은 첫 도시 시작 결과는 N개까지만 상위에 표시")

    # 검색 버튼
    if st.button("🔍 루트 검색", type="primary", width='stretch'):
        if not selected_bases:
            st.error("출발 공항을 선택하세요.")
        elif end_date < start_date:
            st.error("종료일이 시작일보다 빠릅니다.")
        else:
            with st.spinner("검색 중..."):
                results = {}
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
                    )

            # 결과 표시
            for ptn, rts in results.items():
                if not rts:
                    st.info(f"{PATTERNS[ptn]['label']}: 결과 없음")
                    continue

                st.subheader(f"📅 {PATTERNS[ptn]['label']} — {len(rts)}건")
                df = pd.DataFrame([route_to_dict(r) for r in rts])

                # 모바일: 핵심 컬럼만 (날짜, 루트, 세그, 공항, LSP)
                display = df[["date", "route", "segments", "airports",
                               "lsp", "fop", "miles"]].copy()
                display.columns = ["날짜", "루트", "세그", "공항",
                                    "LSP", "FOP", "마일"]
                st.dataframe(display, width='stretch', hide_index=True,
                             height=min(420, 50 + len(display) * 35))

                st.markdown(f"**모든 루트 상세 ({len(rts)}건)**")
                st.caption("각 루트를 펼쳐서 항공편·시각·JAL 링크 확인. "
                           "가격은 참고용일 뿐 정확하지 않으니 JAL에서 직접 검색하세요.")
                for i, r in enumerate(rts):
                    route_path = " → ".join(
                        [r.segments[0].origin] +
                        [s.destination for s in r.segments]
                    ) if r.segments else ""
                    # 긴 루트는 제목에서 잘라서 표시
                    route_short = (route_path[:80] + "..."
                                   if len(route_path) > 80 else route_path)
                    with st.expander(
                        f"#{i+1}  {r.segments[0].flight_date}  "
                        f"세그{r.num_segments}/공항{r.num_airports}/LSP{r.lsp}  "
                        f"| {route_short}"
                    ):
                        st.markdown(f"**전체 루트**: {route_path}")
                        seg_rows = []
                        for s in r.segments:
                            seg_rows.append({
                                "편명": s.flight_no,
                                "날짜": s.flight_date.isoformat(),
                                "구간": f"{s.origin}→{s.destination}",
                                "출발": s.dep_time,
                                "도착": s.arr_time,
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
                            f"참고가격(추정): ¥{r.price:,} / "
                            f"FOP {r.fop} / 마일 {r.miles}"
                        )


# ===== Tab 2: 운임 입력 =====
with tabs[1]:
    st.markdown("### 💰 운임 입력")
    st.caption("JAL/Google에서 본 가격을 저장 → 다음 검색의 참고치로 사용")

    airports = get_all_airports()
    codes = [a["code"] for a in airports]
    labels = {a["code"]: f"{a['code']} - {a['name_ko']}" for a in airports}

    cf1, cf2 = st.columns(2)
    f_origin = cf1.selectbox("출발", codes,
                              format_func=lambda c: labels[c],
                              key="fare_origin")
    f_dest = cf2.selectbox("도착", codes,
                            format_func=lambda c: labels[c],
                            index=1, key="fare_dest")

    cf3, cf4 = st.columns(2)
    f_date = cf3.date_input("탑승일",
                             value=date.today() + timedelta(days=14),
                             key="fare_date")
    f_class = cf4.selectbox("운임", list(FARE_CLASSES.keys()),
                             format_func=lambda c: FARE_CLASSES[c]["label"],
                             key="fare_class_input")

    f_price = st.number_input("가격 (엔)", min_value=0, step=100,
                               key="fare_price")
    f_notes = st.text_input("메모", key="fare_notes")

    if st.button("💾 저장", type="primary", width='stretch'):
        if f_price <= 0:
            st.error("가격을 입력해주세요.")
        elif f_origin == f_dest:
            st.error("출발지와 도착지가 같습니다.")
        else:
            add_fare(f_origin, f_dest, f_date.isoformat(),
                     f_class, int(f_price),
                     source="manual", confidence=2,
                     notes=f_notes or "")
            st.success(f"✅ {f_origin}→{f_dest} ¥{f_price:,} 저장됨")


# ===== Tab 3: 예약 기록 =====
with tabs[2]:
    st.markdown("### 📋 예약 기록")

    airports = get_all_airports()
    codes = [a["code"] for a in airports]
    labels = {a["code"]: f"{a['code']} - {a['name_ko']}" for a in airports}

    cb1, cb2 = st.columns(2)
    b_flight_no = cb1.text_input("편명", key="bk_flight")
    b_pnr = cb2.text_input("PNR", key="bk_pnr")

    cb3, cb4 = st.columns(2)
    b_origin = cb3.selectbox("출발", codes,
                              format_func=lambda c: labels[c],
                              key="bk_origin")
    b_dest = cb4.selectbox("도착", codes,
                            format_func=lambda c: labels[c],
                            index=1, key="bk_dest")

    cb5, cb6 = st.columns(2)
    b_date = cb5.date_input("탑승일",
                             value=date.today() + timedelta(days=14),
                             key="bk_date")
    b_class = cb6.selectbox("운임", list(FARE_CLASSES.keys()),
                             format_func=lambda c: FARE_CLASSES[c]["label"],
                             key="bk_class")
    b_price = st.number_input("결제 (엔)", min_value=0, step=100, key="bk_price")
    b_notes = st.text_input("메모", key="bk_notes")

    if st.button("✅ 등록", type="primary", width='stretch'):
        if not b_flight_no or b_price <= 0:
            st.error("편명과 가격은 필수입니다.")
        else:
            add_booking(b_flight_no, b_origin, b_dest, b_date.isoformat(),
                        b_class, int(b_price), b_pnr or "", b_notes or "")
            st.success(f"✅ 등록됨")

    st.markdown("---")
    st.markdown("**최근 예약**")
    with get_conn() as c:
        rows = c.execute(
            "SELECT * FROM bookings ORDER BY booked_at DESC LIMIT 30"
        ).fetchall()
    if rows:
        df_b = pd.DataFrame([dict(r) for r in rows])
        st.dataframe(df_b, width='stretch', hide_index=True)
    else:
        st.info("등록된 예약 없음")


# ===== Tab 4: 캐시 현황 =====
with tabs[3]:
    st.markdown("### 📊 캐시 현황")
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
        df_c.columns = ["출발", "도착", "운임", "건수",
                        "평균", "최저", "최고", "★최대"]
        st.dataframe(df_c, width='stretch', hide_index=True)
    else:
        st.info("캐시 비어있음")
