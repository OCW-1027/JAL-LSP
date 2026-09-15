# JAL LSP Optimizer v2

JAL国内線の乗継ルートを自動探索し、LSP (Life Status Points, 1搭乗=5pt) が多い順に提示する
スケジュール組合せ検索ツール。**運賃は扱いません** (JALで直接確認)。

## v2 の変更点

| | v1 | v2 |
|---|---|---|
| 時刻表データ | スクリーンショット→手作業CSV (76路線) | 駅探 JAL時刻表を **自動取得** (約300路線・65空港) |
| 運航日 | 全便「毎日運航」と仮定 | **日付ごとの実スケジュール** (曜日運航・運休を反映) |
| 更新 | 手動 | GitHub Actions が **毎週自動更新** → Streamlit Cloud 再デプロイ |
| DB | SQLite + seed + CSV import | CSV をメモリ読込 (DB廃止) |
| 運賃/予約/キャッシュ/Amadeus | あり | 削除 (意味がないため) |
| 区間マイル | 手入力 | JAL公式マイル表 (新路線は推定・注記) |

## 構成

```
app.py                       Streamlit UI (日本語)
engine/
  optimizer.py               チェーン探索エンジン (v1と同じアルゴリズム)
  data.py                    data/ の CSV 読込
  miles.py                   区間マイル表 + 推定フォールバック
  rules.py                   MCT / FOP / LSP 定数
etl/fetch_ekitan.py          駅探から日付別時刻表を取得
data/
  flights_by_date.csv        date, flight_no, origin, destination, dep_time, arr_time
  meta.json                  取得日・カバー期間・空港名
.github/workflows/update-timetable.yml   週次自動更新
```

## セットアップ

```bash
pip install -r requirements.txt
python etl/fetch_ekitan.py --days 60      # 初回データ取得 (約15分)
streamlit run app.py
```

Streamlit Community Cloud: リポジトリを接続し `app.py` を指定するだけ。
`data/` はリポジトリに含まれるので、起動時に追加処理は不要。

## 自動更新

`.github/workflows/update-timetable.yml` が毎週月曜 03:00 JST に翌60日分を取得して
`data/` を commit。Streamlit Cloud は push を検知して再デプロイする。

手動実行: GitHub → **Actions** → **update-timetable** → **Run workflow**。

初回のみ: GitHub → Settings → Actions → General → **Workflow permissions** を
**Read and write permissions** にする (bot が commit するため)。

## データ出典と注意

- 時刻表: [駅探 JAL国内線時刻表](https://ekitan.com/timetable/airplane/domestic/jal) を
  リクエスト間隔をあけて取得。JAL公式サイトにはアクセスしない。
- 公式データではないため、予約前に必ず JAL 公式で運航・乗継可否・運賃を確認すること。
- 区間マイルは JAL 時刻表の固定値。表に無い路線 (FDA コードシェア等) は大圏距離から推定し UI に注記。
- FDA (EMJ) / AMX / ORC コードシェア便は JAL 便名で含まれる。LSP 積算対象かは JAL 規定を確認。
