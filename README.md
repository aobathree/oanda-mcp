# oanda-mcp

OANDA v20 REST API の **参照系(read-only)** 機能を Claude から使えるようにする MCP サーバーです。
発注・決済などの取引系ツールは含まれていません(安全のため、まず参照系のみ)。

## 提供ツール

| ツール | 内容 |
|---|---|
| `get_price` | 現在のBid/Askレート取得(複数通貨ペア可) |
| `get_candles` | ローソク足(履歴)取得。S5〜月足、最大5000本 |
| `get_account_summary` | 口座サマリー(残高・評価損益・証拠金など) |
| `get_open_positions` | 保有ポジション一覧 |
| `get_pending_orders` | 未約定注文一覧 |
| `get_open_trades` | オープントレード一覧 |
| `get_recent_transactions` | 直近の取引履歴(トランザクション) |
| `list_instruments` | 取引可能な銘柄一覧 |

通貨ペアは OANDA 形式(`USD_JPY`, `EUR_USD` など)で指定します。

## 1. OANDA側の準備(デモ口座)

1. [OANDA fxTrade Practice(デモ口座)](https://www.oanda.com/demo-account/) を開設
2. ログイン後、**Manage API Access**(My Account → Manage API Access)で
   パーソナルアクセストークンを生成
3. アカウントID(`101-001-1234567-001` のような形式)を控える

## 2. インストール

Python 3.10 以上が必要です。

```bash
cd oanda-mcp
pip install -e .
```

## 3. 認証情報の設定(.env 推奨)

プロジェクト直下に `.env` ファイルを作るのが最も簡単です(自動で読み込まれます):

```bash
cp .env.example .env   # Windows: copy .env.example .env
```

`.env` の中身:

```
OANDA_API_TOKEN=あなたのトークン
OANDA_ACCOUNT_ID=101-001-1234567-001
OANDA_ENV=practice
```

`.env` はカレントディレクトリ(とその親)→ プロジェクトルートの順で検索されます。
既に設定済みの環境変数が優先されます。

環境変数で渡す場合:

```powershell
# Windows (PowerShell)
$env:OANDA_API_TOKEN = "あなたのトークン"
$env:OANDA_ACCOUNT_ID = "101-001-1234567-001"
$env:OANDA_ENV = "practice"
```

```bash
# macOS / Linux (bash)
export OANDA_API_TOKEN="あなたのトークン"
export OANDA_ACCOUNT_ID="101-001-1234567-001"
export OANDA_ENV="practice"
```

## 4. 動作確認(MCP Inspector)

```bash
cd oanda-mcp   # .env のある場所で
npx @modelcontextprotocol/inspector oanda-mcp
```

ブラウザで Inspector が開くので、`get_price` に `USD_JPY` を渡すなどして
レスポンスが返ることを確認してください。

テストだけ走らせる場合:

```bash
python tests/test_server.py
```

## 5. Claude への登録

### Claude Desktop

`claude_desktop_config.json`(macOS: `~/Library/Application Support/Claude/`、
Windows: `%APPDATA%\Claude\`)に追記します:

```json
{
  "mcpServers": {
    "oanda": {
      "command": "oanda-mcp",
      "env": {
        "OANDA_DOTENV": "D:\\oanda-mcp\\.env"
      }
    }
  }
}
```

`.env` を使わない場合は、`env` に `OANDA_API_TOKEN` / `OANDA_ACCOUNT_ID` /
`OANDA_ENV` を直接書くこともできます。

`oanda-mcp` コマンドが PATH にない場合は、`"command": "python"`,
`"args": ["-m", "oanda_mcp.server"]` の形式でも起動できます。

### Claude Code

```bash
claude mcp add oanda \
  -e OANDA_API_TOKEN="あなたのトークン" \
  -e OANDA_ACCOUNT_ID="101-001-1234567-001" \
  -e OANDA_ENV="practice" \
  -- oanda-mcp
```

登録後、Claude に「ドル円の今のレートは?」「USD_JPYの日足を30本見せて」の
ように話しかければツールが呼ばれます。

## 6. 環境変数

| 変数 | 必須 | 説明 |
|---|---|---|
| `OANDA_API_TOKEN` | ✔ | パーソナルアクセストークン |
| `OANDA_ACCOUNT_ID` | ✔ | 口座ID |
| `OANDA_ENV` | - | `practice`(デフォルト)/ `live` |
| `OANDA_DOTENV` | - | 読み込む `.env` ファイルのパスを明示指定 |

## 注意事項

- トークンは口座への広い権限を持ちます。設定ファイルの取り扱いに注意し、
  リポジトリにコミットしないでください。
- `OANDA_ENV=live` にすると本番口座のデータを参照します(このサーバーは
  参照のみなので発注はできませんが、口座情報は実データになります)。
- OANDA証券(日本)の口座でAPIを使う場合は、口座コースごとのAPI利用条件を
  事前に確認してください。

## 今後の拡張(取引系を足す場合)

`client.py` に POST/PUT 系メソッド(`/orders`, `/trades/{id}/close` など)を
追加し、`server.py` にツールを足すだけで拡張できます。その際は
最大ロット数の上限チェックや、`OANDA_ENV=live` 時は発注を拒否する
ガードを入れることを強く推奨します。
