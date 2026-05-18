# Google Cloud Run へのデプロイ手順

このプロジェクトのPythonバックエンドAPIをGoogle Cloud Runで常時稼働させるための手順です。

## 前提条件

1. **Google Cloud アカウント** とプロジェクトが作成済みであること。
2. **gcloud CLI** がローカルPCにインストールされ、ログイン済みであること (`gcloud auth login`)。
3. プロジェクトで **Cloud Run API** と **Cloud Build API** が有効になっていること。
4. **Twelve Data の APIキー** を取得済みであること。

## デプロイ手順

コマンドプロンプトまたは PowerShell を開き、以下の手順を実行してください。

### 1. プロジェクトのディレクトリに移動
```bash
cd C:\Users\mao\Desktop\fx-trader-desktop\src-python
```

### 2. Google Cloud プロジェクトの設定
（`[YOUR_PROJECT_ID]` を実際のプロジェクトIDに置き換えてください）
```bash
gcloud config set project [YOUR_PROJECT_ID]
```

### 3. Cloud Run へのデプロイ実行
以下のコマンドを実行してソースコードから直接ビルド＆デプロイを行います。
途中で「Service name」や「Region（例: `asia-northeast1` 東京）」を聞かれたら入力してください。

```bash
gcloud run deploy fx-trader-api ^
  --source . ^
  --region asia-northeast1 ^
  --allow-unauthenticated ^
  --set-env-vars TWELVEDATA_API_KEY="あなたのTwelveData_APIキー" ^
  --port 8742
```
> [!NOTE]
> `^` は Windows コマンドプロンプトの改行文字です。PowerShell の場合は <code>`</code> (バッククォート) に置き換えるか、1行で繋げて実行してください。

### 4. デプロイ完了の確認
デプロイが成功すると、ターミナルに以下のようなURLが表示されます。
`Service URL: https://fx-trader-api-xxxxxxx-an.a.run.app`

ブラウザで `https://fx-trader-api-xxxxxxx-an.a.run.app/health` にアクセスし、`{"status":"ok","port":8742}` が返ってくることを確認します。

## フロントエンドの接続先変更について

デスクトップアプリ（Tauri / React）から、今回デプロイした Cloud Run の API に接続するには、フロントエンドの環境変数 `VITE_API_URL` などを設定するか、プロキシ設定を使わずに直接絶対URLをフェッチするように変更する必要があります。

現状のコード（`vite.config.ts`のproxy）はローカル開発用です。本番ビルド時には、`/api/...` という相対パスでのアクセスが Cloud Run の URL に向くよう、APIクライアント側の BaseURL を設定してください。
