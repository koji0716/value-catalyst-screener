# Value Catalyst Screener

PCローカルで動作する、割安株候補を機械的に抽出する分析ツールです。現在のMVPでは、SQLite、日米サンプルデータ、J-Quantsからの日本株データ同期、EDINET DB補完、SEC EDGARからの米国株財務同期、yfinance価格同期、プリセットスクリーニング、CLI、Streamlit UI、CSV/HTMLレポートを実装しています。

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
python cli.py sync --market us --source edgar --codes AAPL,MSFT --from 2025-01-01
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
- J-Quants財務サマリー由来のカタリスト推定
- EDINET DB年度財務・有報開示一覧・有報テキストリスク語同期
- SEC EDGAR会社マスター・Company Facts・提出書類同期
- yfinance米国株OHLC・配当同期
- 手動更新履歴と最終同期状態の保存
- プリセット読み込み
- スコアリング
- スクリーニング結果保存
- 銘柄説明文生成
- Streamlit UI
- CSV/HTMLレポート出力
- 簡易バックテスト
- EDINET / SEC EDGAR クライアント

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
4. MVP 4: 無料データによるカタリスト分析
5. MVP 5: SEC EDGARと米国株価API

## J-Quants同期の挙動

`python cli.py sync --market jp` は `--source auto` と同じです。J-Quants設定があればJ-Quantsを使い、未設定または認証失敗時はサンプルデータへフォールバックします。明示的に失敗を見たい場合は `--source jquants` を指定してください。

全銘柄の株価・財務を一気に取得するとAPI負荷が大きいため、価格・財務同期の対象は `config/settings.yaml` の `jquants_starter_codes` を初期ユニバースにしています。対象を変える場合は `--codes 7203,9432` または `--limit` を使ってください。

## 無料カタリスト分析

公式TDnet APIは有料サービスのため、MVPでは直接利用しません。代わりに、無料または既存キーで扱えるデータだけを使ってカタリスト候補を作ります。

- J-Quants財務サマリー: 業績予想の上方修正、下方修正、増配、黒字転換を推定
- J-Quants決算予定: 近い決算イベントを登録
- EDINET DB有報テキスト: 継続企業、債務超過、上場廃止などのリスク語を検出

J-QuantsのFreeプランは遅延データになるため、即時性のある売買判断ではなく、候補抽出・監視リスト作成・バックテスト寄りの用途として扱います。

非公式TDnet APIや公開HTMLスクレイピングは、可用性・利用条件・仕様変更リスクが高いため標準実装から外しています。必要になった場合だけ、明示的なオプトイン機能として追加します。

## 手動更新ポリシー

自動スケジューラはまだ使わず、ユーザーがCLIまたはStreamlitのボタンから手動更新します。同期履歴は `sync_jobs`、最終状態は `sync_state` に保存されます。

- 日次更新: `python cli.py sync --market jp --source jquants --mode daily --codes 7203,9432`
- 追加取得: `python cli.py sync --market jp --source jquants --mode backfill --limit 100 --from 2024-01-01`
- 有報補完: `python cli.py sync --market jp --source edinetdb --mode manual --codes 7203`
- 米国株更新: `python cli.py sync --market us --source edgar --mode manual --codes AAPL,MSFT`
- 画面更新: Streamlit左サイドバーの `J-Quants手動更新`

## EDINET DB補完

EDINET DBを使う場合は `EDINETDB_API_KEY` を環境変数に設定してください。既存のCodex MCP用に `EDINETDB_AUTH=Bearer ...` を設定している場合も利用できます。

EDINET DB同期では、J-Quantsでは補いづらい年度有報ベースの財務、開示一覧、有報テキストブロックを取得します。有報テキストに `継続企業`、`債務超過`、`上場廃止` などの語が含まれる場合は、リスクイベントとして保存します。

## 米国株同期

米国株は `SEC_USER_AGENT` を環境変数に設定すると、SEC EDGARの会社マスター、Company Facts、10-K/10-Q/8-K提出一覧を取得できます。株価OHLCと配当は `PRICE_PROVIDER=yfinance` で取得します。

SEC EDGARの利用では識別可能なUser-Agentが必要です。例: `ValueCatalystScreener your_email@example.com`
アクセス間隔は `config/settings.yaml` の `providers.edgar_rate_limit_per_sec` で制御します。

APIキーやUser-Agentが未設定の場合、`--source auto` ではサンプルデータへフォールバックします。明示的にEDGAR失敗を確認したい場合は `--source edgar` を指定してください。

