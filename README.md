# Value Catalyst Screener

PCローカルで動作する、割安株候補を機械的に抽出する分析ツールです。現在のMVPでは、SQLite、サンプル日本株データ、J-Quantsからの日本株データ同期、プリセットスクリーニング、CLI、Streamlit UI、CSV/HTMLレポートを実装しています。

このアプリは投資助言ではありません。投資判断は自己責任であり、最終判断はユーザーが行ってください。

## セットアップ

```bash
cd value-catalyst-screener
python -m pip install -r requirements.txt
python cli.py init
```

外部APIキーが未設定でもサンプルデータで動作します。J-Quants V2を使う場合は、APIキーを `JQUANTS_API_KEY` に設定してください。リポジトリには秘密情報を保存しません。

PowerShell例:

```powershell
[Environment]::SetEnvironmentVariable("JQUANTS_API_KEY", "your_api_key", "User")
```

## よく使うコマンド

```bash
python cli.py init
python cli.py app
python cli.py sync --market jp
python cli.py sync --market jp --source jquants --codes 7203,9432 --from 2025-01-01
python cli.py sync --market jp --source jquants --mode manual --codes 7203 --from 2025-01-01
python cli.py sync --market jp --source edinetdb --mode manual --codes 7203
python cli.py sync --market jp --source jquants --mode backfill --limit 100 --from 2024-01-01
python cli.py sync --market jp --source sample
python cli.py screen --preset balanced
python cli.py explain --ticker 7203
python cli.py report --preset balanced --format csv
python cli.py report --preset catalyst_value --format html
python cli.py backtest --market jp --preset balanced --from 2020-01-01 --to 2025-12-31
python cli.py watchlist add --ticker 7203
python cli.py watchlist show
```

## MVPの範囲

- SQLite DB作成
- 仕様書に基づくテーブル定義
- サンプル銘柄データ投入
- J-Quants認証
- J-Quants銘柄一覧同期
- J-Quants株価OHLC同期
- J-Quants財務サマリー同期
- J-Quants配当データ同期
- J-Quants決算予定イベント同期
- EDINET DB年度財務・有報開示一覧・有報テキストリスク語同期
- 手動更新履歴と最終同期状態の保存
- プリセット読み込み
- スコアリング
- スクリーニング結果保存
- 銘柄説明文生成
- Streamlit UI
- CSV/HTMLレポート出力
- 簡易バックテスト
- EDINET / SEC EDGAR / TDnet クライアント雛形

## ディレクトリ

```text
value-catalyst-screener/
  app.py
  cli.py
  config/
  data/
  src/
  tests/
```

## データソースの段階導入

1. MVP 1: サンプルデータ + SQLite + Streamlit + プリセットスクリーニング
2. MVP 2: J-Quants認証、銘柄一覧、株価、財務、配当、決算予定
3. MVP 3: EDINET DBによる年度財務、有報開示一覧、有報テキスト検索
4. MVP 4: TDnetカタリスト分析
5. MVP 5: SEC EDGARと米国株価API

## J-Quants同期の挙動

`python cli.py sync --market jp` は `--source auto` と同じです。J-Quants設定があればJ-Quantsを使い、未設定または認証失敗時はサンプルデータへフォールバックします。明示的に失敗を見たい場合は `--source jquants` を指定してください。

全銘柄の株価・財務を一気に取得するとAPI負荷が大きいため、価格・財務同期の対象は `config/settings.yaml` の `jquants_starter_codes` を初期ユニバースにしています。対象を変える場合は `--codes 7203,9432` または `--limit` を使ってください。

## 手動更新ポリシー

自動スケジューラはまだ使わず、ユーザーがCLIまたはStreamlitのボタンから手動更新します。同期履歴は `sync_jobs`、最終状態は `sync_state` に保存されます。

- 日次更新: `python cli.py sync --market jp --source jquants --mode daily --codes 7203,9432`
- 追加取得: `python cli.py sync --market jp --source jquants --mode backfill --limit 100 --from 2024-01-01`
- 有報補完: `python cli.py sync --market jp --source edinetdb --mode manual --codes 7203`
- 画面更新: Streamlit左サイドバーの `J-Quants手動更新`

## EDINET DB補完

EDINET DBを使う場合は `EDINETDB_API_KEY` を環境変数に設定してください。既存のCodex MCP用に `EDINETDB_AUTH=Bearer ...` を設定している場合も利用できます。

EDINET DB同期では、J-Quantsでは補いづらい年度有報ベースの財務、開示一覧、有報テキストブロックを取得します。有報テキストに `継続企業`、`債務超過`、`上場廃止` などの語が含まれる場合は、リスクイベントとして保存します。

