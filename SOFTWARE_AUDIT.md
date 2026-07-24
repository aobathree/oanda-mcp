# oanda-mcp ソフトウェア評価レポート

- 評価日: 2026-07-24
- 対象バージョン: 0.2.1
- 対象範囲: MCPツール定義、OANDA APIクライアント、設定読込、テスト、パッケージ設定
- 評価方法: コードレビュー、ローカル再現テスト、既存テスト実行、OANDA公式API仕様との照合

## 結論

参照専用MCPサーバーとしての基本設計は守られており、発注・決済を行う書き込みHTTPメソッドは実装されていない。一方、設定ファイルの信頼境界、トランザクション取得の境界値と期間、MCP入力スキーマ、回帰テスト基盤には修正を推奨する課題がある。

優先順位は次のとおり。

1. `.env` 読込処理の安全化
2. `get_recent_transactions` の件数・期間処理の修正
3. MCP入力スキーマへの制約追加
4. 回帰テストと静的解析の整備

## 評価結果

### 1. 高: 作業フォルダーの `.env` を信頼しすぎている

対象:

- `src/oanda_mcp/client.py:42`
- `src/oanda_mcp/client.py:65`
- `src/oanda_mcp/client.py:118`

`_load_dotenv()` はカレントディレクトリからその親ディレクトリまで `.env` を探索し、最初に見つけたファイルからOANDA以外を含むすべてのキーを `os.environ` に取り込む。

この実装には次の問題がある。

- 作業フォルダーに無関係な `.env` があると、推奨保存先の `~/.oanda/.env` が読み込まれない。
- `HTTPS_PROXY`、`ALL_PROXY`、`SSL_CERT_FILE` など、HTTPXの通信経路や証明書検証に影響するキーも読み込まれる。
- HTTPXの `AsyncClient` は既定で環境変数を信頼するため、固定されたOANDAホストへの認証付き通信が作業フォルダー側の設定に影響される。
- MCP設定から認証情報を環境変数として渡している場合、信頼できない作業フォルダーの `.env` が通信経路へ影響する可能性がある。

推奨対応:

- 読み込むキーを `OANDA_API_TOKEN`、`OANDA_ACCOUNT_ID`、`OANDA_ENV` など必要なものだけに限定する。
- `OANDA_DOTENV` の明示指定と `~/.oanda/.env` を、作業フォルダーの `.env` より優先する。
- 固定OANDAホストへの通信では、必要性を確認したうえで `httpx.AsyncClient(trust_env=False)` を使用する。
- 候補ファイルが認証情報を含まない場合に、次の候補へ進むか明示的にエラーにする。

参考:

- [HTTPX Environment Variables](https://www.python-httpx.org/environment_variables/)

### 2. 中: `get_recent_transactions(count=0)` が要求件数を守らない

対象:

- `src/oanda_mcp/client.py:194`
- `src/oanda_mcp/client.py:205`
- `src/oanda_mcp/server.py:140`

`count` に下限がなく、`count=0` の場合は `pageSize=0` がOANDA APIへ送られる。また、Pythonの `[-0:]` は全体を返すため、取得済みページの全トランザクションが返る。

ローカル再現結果:

```text
入力: count=0
OANDA向けパラメーター: {"pageSize": 0}
返却結果: ページ内の全トランザクション
```

負数も不正な `pageSize` と意図しないスライス動作を起こす。1000超の値は `min(count, 1000)` で黙って切り詰められ、要求件数との不一致が発生する。OANDAの `pageSize` 上限は1000件である。

推奨対応:

- MCPスキーマとクライアントの両方で `1 <= count <= 1000` を検証する。
- 1000件を超える取得を提供する場合は、複数ページを明示的に取得する。
- 境界値 `-1`、`0`、`1`、`1000`、`1001` のテストを追加する。

参考:

- [OANDA Transaction API](https://developer.oanda.com/rest-live-v20/transaction-ep/)

### 3. 中: 古い口座で最近のトランザクション取得が失敗する可能性がある

対象:

- `src/oanda_mcp/client.py:197`

トランザクション一覧APIを `from` と `to` なしで呼び出している。この場合、公式仕様上は口座作成時から現在までが既定期間になる一方、1回に照会できる期間は最大365日である。

開設から1年以上経過した口座では、最初のページ一覧取得がAPIエラーになる可能性があり、「最近のトランザクションを取得する」というツールの目的を満たせない。

推奨対応:

- 現在時刻を基準に365日以内の明示的な期間を指定する。
- または最新トランザクションIDを基準に `idrange` や `sinceid` を利用する。
- 1年以上経過した口座を模したレスポンスでテストする。

参考:

- [OANDA Transaction API](https://developer.oanda.com/rest-live-v20/transaction-ep/)

### 4. 低: MCP入力スキーマにAPI制約が反映されていない

対象:

- `src/oanda_mcp/server.py:61`
- `src/oanda_mcp/server.py:140`

生成されたMCP入力スキーマでは、`get_candles.count` と `get_recent_transactions.count` が制約なしの整数になっている。ローソク足の上限5000件を超える値や負数も、認証付きAPIリクエストを送った後で初めてエラーになる。

加えて、OANDAで利用可能な時間足 `M3` が `get_candles` の説明から抜けている。

推奨対応:

- `Annotated` とPydanticの `Field` などを使い、最小値・最大値をMCPスキーマへ反映する。
- `granularity` と `price` は `Literal` または列挙型で表現する。
- `M3` をツール説明とテストへ追加する。
- `from_time` と `to_time` の前後関係、RFC3339形式を検証する。

参考:

- [OANDA Pricing and Candles API](https://developer.oanda.com/rest-live-v20/pricing-ep/)

### 5. 低: 回帰テストと静的解析の基盤が不足している

既存のスモークテストは、ツール登録、環境設定、価格整形、ローソク足パラメーターの4件のみである。次の領域が未検証になっている。

- `.env` の探索順序とキー制限
- HTTPタイムアウト、非JSON応答、4xx・5xx応答
- トランザクションの境界値とページ処理
- MCP入力スキーマの制約
- 認証情報不足時のMCPエラー応答

また、開発環境には `pytest`、`ruff`、`mypy` が導入されておらず、標準的な自動検証を実行できなかった。

推奨対応:

- `[project.optional-dependencies]` に `test` または `dev` 依存を定義する。
- `pytest`、`pytest-asyncio`、`respx` または `httpx.MockTransport` を利用する。
- CIでテスト、静的解析、型検査、パッケージビルドを実行する。
- 実口座テストはpractice環境だけに限定し、通常のCIとは分離する。

## 実行した確認

| 確認項目 | 結果 |
|---|---|
| 既存スモークテスト4件 | 成功 |
| Python構文コンパイル (`compileall`) | 成功 |
| インストール済み依存の整合性 (`pip check`) | 成功 |
| MCPツール8件の登録 | 成功 |
| `count=0` 境界値のローカル再現 | 問題を再現 |
| `pytest` | 未導入のため未実行 |
| `ruff` | 未導入のため未実行 |
| `mypy` | 未導入のため未実行 |
| OANDA practice API統合テスト | 実行環境の外部接続制限により未確認 |

## 良好な点

- OANDAへの操作はすべてGETであり、発注・変更・決済処理は実装されていない。
- practice環境が既定で、live環境は明示指定が必要になっている。
- Bearerトークンをログや通常のツール出力へ含める処理は見当たらない。
- HTTPエラーと非JSON応答を `OandaError` へ変換している。
- ローソク足で `from` と `to` の両方がある場合に `count` を除外している。
- READMEには認証情報をリポジトリ外へ保存する方針が記載されている。

## 総合評価

現状でも小規模な参照用途には利用できるが、金融口座の認証情報を扱うMCPサーバーとしては、作業フォルダー由来の環境変数を信頼する設計を最優先で改善すべきである。

`.env` の信頼境界とトランザクション取得を修正し、境界値テストと入力スキーマ制約を追加すれば、参照専用サーバーとしての安全性と予測可能性を大きく高められる。
