# JAL LSP Optimizer

JAL 국내선 세그먼트 런 최적 루트 검색기. **LSP 최대화 / 체인 검색 / 가격은 참고용**.

## 주요 기능

- **체인 검색**: 단순 왕복뿐 아니라 `HND→KMQ→OKA→ISG→KIX→HND` 같은 진짜 스트레치 루트도 자동 탐색
- **다양화**: 첫 출발 도시별로 분산해 결과의 다양성 보장
- **모든 후보 표시**: 검색된 모든 루트를 펼쳐볼 수 있어 본인이 직접 선택
- **JAL/Google 직링크**: 각 세그먼트마다 실제 가격 확인 링크
- **모바일 친화적 UI**

## 폴더 구조

```
jal_lsp_optimizer/
├── app.py              # Streamlit 웹앱
├── seed.py             # 공항·노선 시드
├── db.py               # SQLite 액세스
├── schema.sql          # DB 스키마
├── optimizer.py        # 체인 검색 엔진
├── rules.py            # JAL 규칙
├── csv_import.py       # 시각표 임포트
├── fare_sources.py     # JAL/Google 링크
├── requirements.txt
├── .gitignore
├── README.md
└── data/
    ├── jal_timetable_hnd_2026summer.csv      # HND 출발 288편
    └── jal_timetable_itm_oka_2026summer.csv  # ITM·OKA 출발 106편
```

## 자동 초기화

앱 시작 시 다음을 자동으로 수행:
1. DB 비어있으면 → `seed()` 실행 (공항·노선·MCT)
2. flights 비어있으면 → `data/` 폴더 CSV 자동 임포트

별도의 수동 단계 없이 즉시 사용 가능.

## 로컬 실행

```cmd
pip install -r requirements.txt
streamlit run app.py
```

## 휴대폰에서 접속 (같은 WiFi)

```cmd
streamlit run app.py --server.address 0.0.0.0
```

PC IP(`ipconfig`로 확인) 후 휴대폰에서 `http://192.168.x.x:8501`

## 어디서든 접속 (Streamlit Community Cloud 무료 배포)

1. 이 저장소를 본인 GitHub에 fork 또는 clone
2. https://share.streamlit.io/ 접속
3. GitHub 계정으로 로그인
4. "New app" → 본인의 저장소 / `main` 브랜치 / `app.py` 선택
5. Deploy → 1~2분 후 `https://[앱이름].streamlit.app` URL 발급
6. 이 URL을 휴대폰 북마크 → 어디서든 접속 가능

## 사용법

검색 탭에서:
- 출발 베이스 공항 (HND, ITM, OKA 등 복수 선택)
- 검색 기간 (당일~3일)
- 패턴 (당일 / 1박2일 / 2박3일)
- 세그먼트 범위 (4~22)
- 결과 다양화 옵션

각 결과는 펼쳐서 항공편 상세 + JAL/Google 링크 확인.

## 시각표 갱신 (시즌별)

JAL 국내선은 동계(11~3월) / 하계(4~10월) 시즌별로 갱신됩니다. 새 시즌 시작 전:
1. JAL 공식 시각표에서 노선별 데이터 확보
2. CSV 형식으로 변환 (`flight_no,origin,destination,dep_time,arr_time,op_days`)
3. `data/` 폴더에 저장
4. GitHub에 push → Streamlit Cloud 자동 재배포
