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

**Python 3.10 以上が必要です。**

### Windows

```powershell
cd D:\oanda-mcp
pip install -e .
```

### macOS

macOS標準の `python3` は 3.9 のことがあり(その場合インストールが
`requires a different Python` エラーで失敗します)、システムへの直接
インストールも制限されているため、Homebrewで新しいPythonを入れて
venv(仮想環境)を使います:

```bash
brew install python
cd ~/oanda-mcp
python3.13 -m venv .venv        # brewで入ったバージョンに合わせる(python3.12等)
source .venv/bin/activate
pip install -e .
```

補足: venvのpipが古いと `pyproject.toml` のみのプロジェクトを
editableインストールできません(PEP 660はpip 21.3以降)。その場合は
`pip install -U pip` してから再実行してください。新しいPythonで
venvを作っていれば通常は問題になりません。

## 3. 認証情報の設定(.env)

プロジェクト直下に `.env` ファイルを作ります(サーバー起動時に自動で読み込まれます。
環境変数の設定は不要です):

```powershell
copy .env.example .env    # macOS/Linux: cp .env.example .env
```

`.env` をエディタで開き、自分の値に書き換えます:

```
OANDA_API_TOKEN=あなたのトークン
OANDA_ACCOUNT_ID=101-001-1234567-001
OANDA_ENV=practice
```

`.env` の検索順は「`OANDA_DOTENV` で明示指定したパス → カレントディレクトリと
その親 → プロジェクトルート」です。同名の環境変数が既に設定されている場合は
そちらが優先されます。

**注意**: `.env` は `.gitignore` で除外済みです。コミットしないでください。

## 4. 動作確認(MCP Inspector)

```powershell
# Windows
cd D:\oanda-mcp   # .env のある場所で起動する
npx @modelcontextprotocol/inspector oanda-mcp
```

```bash
# macOS(venvの実行ファイルを指定)
cd ~/oanda-mcp
npx @modelcontextprotocol/inspector .venv/bin/oanda-mcp
```

ブラウザで Inspector が開いたら:

1. Arguments欄は**空のまま**、**Connect** をクリック(左下が緑の「Connected」になる)
2. 上部の **Tools** タブ → **List Tools** で8ツールが表示される
3. `get_price` を選び、`instruments` に `USD_JPY` を入力して **Run Tool**
4. 現在のbid/askがJSONで返れば成功

## 5. Claude Desktop への登録

設定ファイルの場所:

- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

**`command` には `oanda-mcp` 実行ファイルのフルパスを指定してください。**
Claude Desktop はターミナルと同じ PATH を引き継がないため、コマンド名だけでは
起動に失敗することがあります。フルパスは PowerShell で確認できます:

```powershell
(Get-Command oanda-mcp).Source
# 例: C:\Users\<ユーザー名>\AppData\Local\Programs\Python\Python311\Scripts\oanda-mcp.exe
```

確認したパスを使って設定します。

Windows(JSON内の `\` は `\\` にエスケープ):

```json
{
  "mcpServers": {
    "oanda": {
      "command": "C:\\Users\\<ユーザー名>\\AppData\\Local\\Programs\\Python\\Python311\\Scripts\\oanda-mcp.exe",
      "env": {
        "OANDA_DOTENV": "D:\\oanda-mcp\\.env"
      }
    }
  }
}
```

macOS(venv内の実行ファイルをフルパスで指定。activateは使えないため
フルパス指定が必須です):

```json
{
  "mcpServers": {
    "oanda": {
      "command": "/Users/<ユーザー名>/oanda-mcp/.venv/bin/oanda-mcp",
      "env": {
        "OANDA_DOTENV": "/Users/<ユーザー名>/oanda-mcp/.env"
      }
    }
  }
}
```

既に他の設定(`preferences` など)があるファイルの場合、`mcpServers` は
最上位(一番外側の `{}` の直下)に、既存ブロックとカンマで区切って追加します。
保存前に `python3 -m json.tool <設定ファイル>` で構文チェックすると安全です。

`OANDA_DOTENV` で `.env` の場所を明示しているのは、Claude Desktop からの起動では
カレントディレクトリがプロジェクト外になるためです。

保存後、Claude Desktop を**完全に再起動**(タスクトレイのアイコンからも終了)すると
「oanda」サーバーが認識されます。「ドル円の今のレートは?」のように話しかければ
ツールが呼ばれます。

## 6. Claude Code への登録(任意)

```powershell
claude mcp add oanda -e OANDA_DOTENV="D:\oanda-mcp\.env" -- oanda-mcp
```

Claude Code はターミナルから起動するため、こちらはコマンド名のままで動きます
(動かない場合はフルパスを指定してください)。

## 7. 環境変数リファレンス

通常は `.env` に書くだけで足ります。

| 変数 | 必須 | 説明 |
|---|---|---|
| `OANDA_API_TOKEN` | ✔ | パーソナルアクセストークン |
| `OANDA_ACCOUNT_ID` | ✔ | 口座ID |
| `OANDA_ENV` | - | `practice`(デフォルト)/ `live` |
| `OANDA_DOTENV` | - | 読み込む `.env` ファイルのパスを明示指定 |

## テスト

```powershell
python tests\test_server.py
```

## 注意事項

- トークンは口座への広い権限を持ちます。`.env` の取り扱いに注意し、
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
