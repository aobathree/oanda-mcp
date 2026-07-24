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

```powershell
cd D:\oanda-mcp
pip install -e .
```

## 3. 認証情報の設定(.env)

`.env` ファイルは**プロジェクトの外**、ホームディレクトリ配下の
`%USERPROFILE%\.oanda\.env` に置きます(サーバー起動時に自動で読み込まれます。
環境変数の設定は不要です):

```powershell
New-Item -ItemType Directory -Force $env:USERPROFILE\.oanda | Out-Null
copy .env.example $env:USERPROFILE\.oanda\.env
notepad $env:USERPROFILE\.oanda\.env
```

エディタが開いたら自分の値に書き換えます:

```
OANDA_API_TOKEN=あなたのトークン
OANDA_ACCOUNT_ID=101-001-1234567-001
OANDA_ENV=practice
```

**プロジェクト直下に `.env` を置かない理由**: このフォルダーで Claude Code などの
コーディングエージェントを使うと、ワークスペース内のファイルとして認証情報が
読める状態になるためです(Webull 公式 MCP サーバーのセキュリティ指針に倣った
配置です)。`.gitignore` では引き続き `.env` を除外していますが、これは誤って
プロジェクト内に置いてしまった場合の保険です。

`.env` の検索順は「`OANDA_DOTENV` で明示指定したパス → `%USERPROFILE%\.oanda\.env`
→ カレントディレクトリとその親 → プロジェクトルート」です。読み込まれるのは
`OANDA_` で始まるキーだけで(`HTTPS_PROXY` などの通信系キーは無視されます)、
`OANDA_` キーを1つも含まないファイルはスキップして次の候補へ進みます。同名の
環境変数が既に設定されている場合はそちらが優先されます。

## 4. 動作確認(MCP Inspector)

```powershell
npx @modelcontextprotocol/inspector oanda-mcp
```

(`.env` は `%USERPROFILE%\.oanda\.env` から自動で読み込まれるため、
どのディレクトリから起動しても構いません)

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

確認したパスを使って設定します(JSON内の `\` は `\\` にエスケープ):

```json
{
  "mcpServers": {
    "oanda": {
      "command": "C:\\Users\\<ユーザー名>\\AppData\\Local\\Programs\\Python\\Python311\\Scripts\\oanda-mcp.exe"
    }
  }
}
```

`.env` は `%USERPROFILE%\.oanda\.env` から自動で読み込まれるため、`env` ブロックは
不要です。別の場所に置いた場合のみ、`env` ブロックで `OANDA_DOTENV` にそのパスを
指定してください。

保存後、Claude Desktop を**完全に再起動**(タスクトレイのアイコンからも終了)すると
「oanda」サーバーが認識されます。「ドル円の今のレートは?」のように話しかければ
ツールが呼ばれます。

## 6. Claude Code への登録(任意)

```powershell
claude mcp add oanda -- oanda-mcp
```

Claude Code はターミナルから起動するため、こちらはコマンド名のままで動きます
(動かない場合はフルパスを指定してください)。

### どのプロジェクトからでも使う(user スコープ + フルパス)

上のコマンドはデフォルトの **local スコープ**(実行したプロジェクト限定)で
登録されます。どのプロジェクトからでも使いたい場合は `--scope user` を
付けます。また、デスクトップアプリ版など PATH を引き継がない環境でも
確実に起動するよう、`command` には実行ファイルのフルパスを指定するのが
安全です:

```powershell
# フルパスを確認
(Get-Command oanda-mcp).Source
# 例: C:\Users\<ユーザー名>\...\Python313\Scripts\oanda-mcp.exe

# user スコープでフルパス登録
claude mcp add --scope user oanda -- "<上で確認したフルパス>"
```

登録後は接続状態を確認できます:

```powershell
claude mcp list
# oanda: ...\oanda-mcp.exe - √ Connected と表示されれば成功
```

設定は `%USERPROFILE%\.claude.json` に保存されます。なお、Microsoft Store 版
Python を使っている場合、Python のバージョンアップで Scripts フォルダーの
パスが変わるため、その際は `claude mcp add` を再実行してください。
起動中の Claude Code セッションには途中から追加したサーバーは反映されません。
新しいセッションを開くとツールが使えるようになります。

## 7. 環境変数リファレンス

通常は `%USERPROFILE%\.oanda\.env` に書くだけで足ります。

| 変数 | 必須 | 説明 |
|---|---|---|
| `OANDA_API_TOKEN` | ✔ | パーソナルアクセストークン |
| `OANDA_ACCOUNT_ID` | ✔ | 口座ID |
| `OANDA_ENV` | - | `practice`(デフォルト)/ `live` |
| `OANDA_DOTENV` | - | 読み込む `.env` ファイルのパスを明示指定 |

## テスト

2層構成です(公式 Alpaca MCP サーバーのテスト戦略に倣ったもの):

```powershell
python tests\test_server.py        # ユニット: モックのみ、認証情報・ネットワーク不要
python tests\test_integration.py   # 統合: practice口座の実APIに read-only GET で接続
```

統合テストは `.env` に実際の認証情報がないとき、および `OANDA_ENV=live` の
ときは自動的にスキップされます(安全のため live 口座では実行されません)。

なお、API リクエストには `User-Agent: oanda-mcp/<version>` が付与されます。

## 注意事項

- トークンは口座への広い権限を持ちます。`.env` はプロジェクトの外
  (`%USERPROFILE%\.oanda\.env`)に置き、リポジトリにコミットしたり
  チャットに貼り付けたりしないでください。
- `OANDA_ENV=live` にすると本番口座のデータを参照します(このサーバーは
  参照のみなので発注はできませんが、口座情報は実データになります)。
- OANDA証券(日本)の口座でAPIを使う場合は、口座コースごとのAPI利用条件を
  事前に確認してください。

## 今後の拡張(取引系を足す場合)

`client.py` に POST/PUT 系メソッド(`/orders`, `/trades/{id}/close` など)を
追加し、`server.py` にツールを足すだけで拡張できます。その際は
最大ロット数の上限チェックや、`OANDA_ENV=live` 時は発注を拒否する
ガードを入れることを強く推奨します。
