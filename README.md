# Value Catalyst Screener

PCローカルで動作する、割安株候補を機械的に抽出する分析ツールです。初期MVPでは、SQLite、サンプル日本株データ、プリセットスクリーニング、CLI、Streamlit UI、CSV/HTMLレポートを実装しています。

このアプリは投資助言ではありません。投資判断は自己責任であり、最終判断はユーザーが行ってください。

## セットアップ

```bash
cd value-catalyst-screener
python -m pip install -r requirements.txt
python cli.py init
```

現在の実装は外部APIキーが未設定でもサンプルデータで動作します。API連携クライアントは `src/providers/` に雛形を用意しています。

## よく使うコマンド

```bash
python cli.py init
python cli.py app
python cli.py sync --market jp
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
- プリセット読み込み
- スコアリング
- スクリーニング結果保存
- 銘柄説明文生成
- Streamlit UI
- CSV/HTMLレポート出力
- 簡易バックテスト
- J-Quants / EDINET / SEC EDGAR / 株価 / TDnet クライアント雛形

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
3. MVP 3: EDINET書類一覧、XBRL CSV ZIP、有報テキスト検索
4. MVP 4: TDnetカタリスト分析
5. MVP 5: SEC EDGARと米国株価API

