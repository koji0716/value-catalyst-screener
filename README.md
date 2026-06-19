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
python cli.py mcp
python cli.py sync --market jp
python cli.py sync --market jp --source jquants --codes 7203,9432 --from 2025-01-01
python cli.py sync --market jp --source jquants --mode manual --codes 7203 --from 2025-01-01
python cli.py sync --market jp --source edinetdb --mode manual --codes 7203
python cli.py bulk-sync-jp --master-only --limit 1000
python cli.py bulk-sync-jp --section Prime,Standard,Growth --offset 0 --limit 100 --from 2025-01-01
python cli.py sync --market us --source edgar --codes AAPL,MSFT --from 2025-01-01
python cli.py bulk-sync-us --master-only --limit 1000
python cli.py bulk-sync-us --exchange Nasdaq,NYSE --limit 100 --from 2025-01-01
python cli.py refresh --market all --limit 10 --max-batches 20 --from 2025-01-01
python cli.py refresh-stale-us --stale-before 2026-06-10 --limit 50 --max-batches 20
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

## MCPサーバ

既存のSQLite DBと分析ロジックを、読み取り専用のMCPサーバとして利用できます。MCP SDKの要件によりPython 3.10以上が必要です。

```bash
python -m pip install -r requirements.txt

# MCPクライアントから起動する通常構成（stdio）
python cli.py mcp

# 必要な場合だけローカルHTTPで起動
python cli.py mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

Streamable HTTPの接続先は `http://127.0.0.1:8000/mcp` です。既定の `stdio` はポートを開きません。

MCPクライアント設定例:

```json
{
  "mcpServers": {
    "value-catalyst-screener": {
      "command": "C:\\path\\to\\python.exe",
      "args": [
        "C:\\path\\to\\value-catalyst-screener\\cli.py",
        "mcp"
      ],
      "cwd": "C:\\path\\to\\value-catalyst-screener"
    }
  }
}
```

公開する主な機能:

- DB概要・データカバレッジ・テーブル定義
- 銘柄検索、既存ロジックによる銘柄分析とスクリーニング
- 株価、財務、イベント、開示、コーポレートアクションの取得
- `SELECT` / `WITH` に限定した読み取り専用SQL

MCP経由では同期、ウォッチリスト更新、スクリーニング結果保存などの更新処理を実行しません。SQLツールもSQLiteのread-only接続、authorizer、最大返却件数、実行時間制限を適用します。

## MVPの範囲

- SQLite DB作成
- 仕様書に基づくテーブル定義
- サンプル銘柄データ投入
- J-Quants認証
- J-Quants銘柄一覧同期
- J-Quants銘柄一覧からの日本株バッチ同期
- J-Quants株価OHLC同期
- J-Quants財務サマリー同期
- J-Quants配当データ同期
- J-Quants決算予定イベント同期
- J-Quants財務サマリー由来のカタリスト推定
- EDINET DB年度財務・有報開示一覧・有報テキストリスク語同期
- SEC EDGAR会社マスター・Company Facts・提出書類同期
- SEC ticker/CIK一覧からの米国株バッチ同期
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

全銘柄の株価・財務を一気に取得するとAPI負荷が大きいため、通常の `sync` では `config/settings.yaml` の `jquants_starter_codes` を初期ユニバースにしています。対象を変える場合は `--codes 7203,9432` または `--limit` を使ってください。

### 日本株をできるだけ多く取り込む

J-Quantsの銘柄一覧を起点に、日本株をバッチ同期できます。まず会社マスターだけ広く取り込み、その後に株価・財務・配当・イベントを少量ずつ追加する運用が安全です。

```bash
# 銘柄コード、会社名、市場区分などの会社マスターだけを最大1000件取り込む
python cli.py bulk-sync-jp --master-only --limit 1000

# プライム/スタンダード/グロースに絞って100件ずつ詳細データを同期
python cli.py bulk-sync-jp --section Prime,Standard,Growth --offset 0 --limit 100 --from 2025-01-01
python cli.py bulk-sync-jp --section Prime,Standard,Growth --offset 100 --limit 100 --from 2025-01-01

# 429 Rate limitが出た場合は、結果のnext_offsetから後で再開
python cli.py bulk-sync-jp --section Prime,Standard,Growth --offset 200 --limit 100 --from 2025-01-01
```

`--section` を省略するか `all` にするとJ-Quants銘柄一覧の全市場区分を対象にします。既に必要データがある銘柄は既定でスキップされます。再取得したい場合は `--no-resume` を付けます。

429 Rate limitはアプリ側で完全に解除できるものではないため、運用で吸収します。会社マスターは `--master-only` で広く取り込み、詳細データは `--limit 5` から `--limit 20` 程度の小さなバッチで実行してください。429が出たら、その結果に表示される `next_offset` を控え、時間を空けて同じ条件のまま `--offset` に指定して再開します。`--no-resume` を付けない限り、既に株価・財務・配当・イベントが入っている銘柄はスキップされます。

進捗確認はCLIでもできます。

```bash
python cli.py coverage
```

手動でoffsetを追い続ける代わりに、最新化ジョブを使うこともできます。会社マスターが未完了なら先にマスターを進め、その後に詳細データを `next_offset` から小分けで取り込みます。完了、429 Rate limit、最大バッチ数到達、offset停滞のいずれかで止まり、状態は `sync_jobs` / `sync_state` に残ります。

```bash
python cli.py refresh --market jp --limit 10 --max-batches 20 --from 2025-01-01
python cli.py refresh --market us --limit 20 --max-batches 20 --from 2025-01-01
python cli.py refresh --market all --limit 10 --max-batches 30 --sleep-sec 2 --from 2025-01-01
```

既に全offsetを処理済みの米国株について、株価が古い銘柄だけを再取得する場合は `refresh-stale-us` を使います。これは既存の米国銘柄から最終株価日が `--stale-before` より古いものを選び、`--limit` 件ずつ株価を取り直します。

```bash
python cli.py refresh-stale-us --stale-before 2026-06-10 --limit 50 --max-batches 20
```

割安株スクリーニング用DBを広く作る場合は、`scripts/refresh_until_complete.py` を使います。既定の `screening` profile は全銘柄の最低限データを優先します。

- 日本株: J-Quantsの株価・財務を銘柄ごとではなく日付ごとに一括取得
- 米国株: yfinanceの株価をtickerごとではなくバッチ単位で一括取得
- 深掘りデータ: filing、配当、イベントは全銘柄ではなく後段の詳細調査向けに抑制
- 取得不能データ: SEC Company Factsが404になる銘柄は `unavailable_data` に記録し、次回以降の無駄な再試行を避ける

```bash
# スクリーニング用の最低限データを優先して収集
python scripts/refresh_until_complete.py --profile screening --from 2025-01-01

# 従来どおり、配当・filing・イベントまで全体に広げる深掘り運用
python scripts/refresh_until_complete.py --profile full --from 2025-01-01
```

Streamlitの `進捗` タブでは、市場別に以下を表示します。

- 会社マスター処理進捗: マスター同期の `next_offset` が直近一括同期の全体件数のどこまで進んだか
- DB会社数: 直近一括同期で確認できた全体件数に対するDB内会社数
- 詳細処理進捗: 最新化ジョブまたは詳細同期の `next_offset` が全体のどこまで進んだか
- 主要データ取り込み率: 株価・財務・開示の取得率の平均
- 主要データ最新化率: 株価が直近10日以内、財務が直近18か月以内の期末データを持つ会社の割合

## 無料カタリスト分析

公式TDnet APIは有料サービスのため、MVPでは直接利用しません。代わりに、無料または既存キーで扱えるデータだけを使ってカタリスト候補を作ります。

- J-Quants財務サマリー: 業績予想の上方修正、下方修正、増配、黒字転換を推定
- J-Quants決算予定: 近い決算イベントを登録
- EDINET DB有報テキスト: 継続企業、債務超過、上場廃止などのリスク語を検出

J-QuantsのFreeプランは遅延データになるため、即時性のある売買判断ではなく、候補抽出・監視リスト作成・バックテスト寄りの用途として扱います。

非公式TDnet APIや公開HTMLスクレイピングは、可用性・利用条件・仕様変更リスクが高いため標準実装から外しています。必要になった場合だけ、明示的なオプトイン機能として追加します。

## 手動更新ポリシー

常駐型の自動スケジューラはまだ使わず、ユーザーがCLIまたはStreamlitのボタンから更新します。同期履歴は `sync_jobs`、最終状態は `sync_state` に保存されます。`refresh` は再開可能な最新化ジョブとして、完了またはAPI制限までバッチを続けます。

- 日次更新: `python cli.py sync --market jp --source jquants --mode daily --codes 7203,9432`
- 追加取得: `python cli.py sync --market jp --source jquants --mode backfill --limit 100 --from 2024-01-01`
- 日本株バッチ: `python cli.py bulk-sync-jp --section Prime,Standard,Growth --limit 100 --from 2025-01-01`
- 有報補完: `python cli.py sync --market jp --source edinetdb --mode manual --codes 7203`
- 米国株更新: `python cli.py sync --market us --source edgar --mode manual --codes AAPL,MSFT`
- 米国株バッチ: `python cli.py bulk-sync-us --exchange Nasdaq,NYSE --limit 100 --from 2025-01-01`
- 全体最新化: `python cli.py refresh --market all --limit 10 --max-batches 30 --from 2025-01-01`
- 画面更新: Streamlitの `データ取得` タブで `日本株を日付単位で取得` / `米国株をまとめて取得` / `古い米国株価を再取得` / `日米まとめて取得`

Streamlitの `進捗` タブでは、取り込み率・最新化率、最終成功日時、最終試行日時、対象件数、処理済み件数、次のoffset、ジョブ履歴を確認できます。

## Streamlit UI

画面は `データ取得`、`スクリーニング`、`深掘り`、`進捗` の4タブに絞っています。

- `データ取得`: 日本株はJ-Quantsを日付単位で全銘柄取得し、米国株はSECマスターとyfinanceの複数ticker取得でスクリーニング用データを集めます。既に取り込み済みの米国銘柄は `古い米国株価を再取得` で株価鮮度を戻せます。
- `スクリーニング`: 日本株、米国株を別々のボタンで抽出します。プリセット条件に加えて、PER上限、PBR上限、ROE下限、自己資本比率下限などを画面から手動設定できます。結果は保存され、CSV出力できます。
- `深掘り`: スクリーニング結果から銘柄を選び、候補銘柄だけ詳細な財務・開示・イベントデータを追加取得して分析を表示します。
- `進捗`: データ取得率、最新化率、同期状態、ジョブ履歴を確認します。

スクリーニングと深掘りの画面には `用語ヘルプ` を用意しています。PER、PBR、ROE、自己資本比率、カタリスト、推奨ラベルなどの意味と注意点を確認できます。

## EDINET DB補完

EDINET DBを使う場合は `EDINETDB_API_KEY` を環境変数に設定してください。既存のCodex MCP用に `EDINETDB_AUTH=Bearer ...` を設定している場合も利用できます。

EDINET DB同期では、J-Quantsでは補いづらい年度有報ベースの財務、開示一覧、有報テキストブロックを取得します。有報テキストに `継続企業`、`債務超過`、`上場廃止` などの語が含まれる場合は、リスクイベントとして保存します。

## 米国株同期

米国株は `SEC_USER_AGENT` を環境変数に設定すると、SEC EDGARの会社マスター、Company Facts、10-K/10-Q/8-K提出一覧を取得できます。株価OHLCと配当は `PRICE_PROVIDER=yfinance` で取得します。

SEC EDGARの利用では識別可能なUser-Agentが必要です。例: `ValueCatalystScreener your_email@example.com`
アクセス間隔は `config/settings.yaml` の `providers.edgar_rate_limit_per_sec` で制御します。

APIキーやUser-Agentが未設定の場合、`--source auto` ではサンプルデータへフォールバックします。明示的にEDGAR失敗を確認したい場合は `--source edgar` を指定してください。

### 米国株をできるだけ多く取り込む

SECのticker/CIK一覧を起点に、米国株をバッチ同期できます。まず会社マスターだけ広く取り込み、その後に財務・提出書類・株価を少量ずつ追加する運用が安全です。

```bash
# SEC ticker/CIK/company name/exchange だけを最大1000件取り込む
python cli.py bulk-sync-us --master-only --limit 1000

# Nasdaq/NYSEに絞って100件ずつ、Company Facts・提出書類・株価・配当を同期
python cli.py bulk-sync-us --exchange Nasdaq,NYSE --offset 0 --limit 100 --from 2025-01-01
python cli.py bulk-sync-us --exchange Nasdaq,NYSE --offset 100 --limit 100 --from 2025-01-01

# 途中で止まった場合、既に必要データがある銘柄は既定でスキップされます
python cli.py bulk-sync-us --exchange Nasdaq,NYSE --offset 200 --limit 100 --from 2025-01-01
```

`--exchange` を省略するか `all` にするとSECのticker一覧にある全exchangeを対象にします。ETF、ADR、優先株、特殊なtickerも混ざるため、最初は `Nasdaq,NYSE,NYSE American` のように絞るのがおすすめです。

`SEC_USER_AGENT` を環境変数に設定していない場合は、単発実行時だけ `--user-agent "ValueCatalystScreener your_email@example.com"` を渡すこともできます。

