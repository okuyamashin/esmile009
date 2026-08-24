# esmile009

Excel（`.xlsx` / `.xls`）をアップロードし、Docker 内の LibreOffice で PDF に変換して返す API とツールです。

- リポジトリ: [github.com/okuyamashin/esmile009](https://github.com/okuyamashin/esmile009.git)

## 個人情報・秘密情報について

**実データや社外秘になるファイルはこのリポジトリに含めないでください。**  
`samples/in/`・`samples/out/` の実ファイルは `.gitignore` で除外しています。変換テストはローカルにのみ `.xlsx` を置いて行ってください。

## 要件

- Docker / Docker Compose（Docker Desktop 可）

## 使い方

```bash
docker compose up -d --build
curl -sS http://127.0.0.1:18083/health
```

API ドキュメント（開発用）: `http://127.0.0.1:18083/docs`

変換:

```bash
curl -fsS -X POST http://127.0.0.1:18083/convert \
  -F 'file=@path/to/sample.xlsx' \
  -o /tmp/out.pdf
```

または:

```bash
./convert.sh samples/in/sample.xlsx
```

停止:

```bash
./stop
```

## 非同期ジョブ（パターン A: キュー + ワーカー）

同期 `POST /convert` に加え、**オンデマンド向け**の非同期 API があります。

| エンドポイント | 説明 |
|----------------|------|
| `POST /jobs` | xlsx を登録 → `{ jobId, status: "queued" }` |
| `GET /jobs/{jobId}` | 状態確認（`done` のとき `pdfUrl`） |
| `GET /jobs/{jobId}/pdf` | 完了後に PDF 取得 |

### ローカル / Docker（検証）

```bash
docker compose up -d --build
docker compose --profile worker up -d   # 変換ワーカーだけ別起動（オンデマンド）
```

```bash
# ジョブ登録
curl -fsS -X POST http://127.0.0.1:18083/jobs \
  -F 'file=@path/to/sample.xlsx'

# 状態（done まで数秒ポーリング）
curl -sS http://127.0.0.1:18083/jobs/<jobId>

# PDF 取得
curl -fsS http://127.0.0.1:18083/jobs/<jobId>/pdf -o out.pdf
```

`JOB_BACKEND=local`（既定）では `data/jobs/` にキューと入出力を置きます。  
**API だけ常時・ワーカーは必要時だけ**にするなら、普段は `docker compose up -d`、変換時だけ `docker compose --profile worker up -d` です。

### AWS（S3 + SQS）

`.env` または Compose の environment に設定:

```bash
JOB_BACKEND=aws
JOB_S3_BUCKET=your-bucket
JOB_SQS_QUEUE_URL=https://sqs....amazonaws.com/.../queue-name
AWS_REGION=ap-northeast-1
```

- API: 入力を S3 に保存し SQS にメッセージ投入  
- ワーカー: SQS をロングポール → S3 から読み込み → PDF を S3 に保存  

本番ではワーカーを **ECS Fargate（desired 0↔1）** や **EC2 + worker コンテナ** でオンデマンド起動する想定です。雛形は `docker-compose.yml` の `worker` サービス（`--profile worker`）です。

## Chrome 拡張

`chrome-extension/` に Manifest V3 の拡張があります。本番 API の例: `https://esmile009.engawa5656.com`（詳細は `docs/aws-domain-engawa5656.md`）。

## 環境変数（Compose）

| 名前 | 説明 |
|------|------|
| `MAX_UPLOAD_BYTES` | アップロード上限（既定 15MB） |
| `CONVERT_TIMEOUT_SEC` | LibreOffice のタイムアウト秒（既定 120） |
| `BASE_PATH` | URL のサブパス（例: `/esmile009`）。Apache がプレフィックスを削るときは不要 |
| `BIND_ADDRESS` | ホストにバインドするアドレス（既定 `127.0.0.1`）。**別マシンの Apache が `ProxyPass http://このEC2のIP:18083/` のときは `0.0.0.0`** にする |
| `JOB_BACKEND` | `local`（既定）または `aws` |
| `JOB_LOCAL_DIR` | ローカルキュー・ジョブファイルの保存先 |
| `JOB_S3_BUCKET` | AWS 時の S3 バケット |
| `JOB_SQS_QUEUE_URL` | AWS 時の SQS キュー URL |

ホストのポートは `docker-compose.yml` の `ports` で変更してください。`convert.sh` の既定 `API_URL` も合わせて調整します。

### ドメインのサブパスで公開する例（`/esmile009/health`）

コンテナに **`BASE_PATH=/esmile009`** を渡します（Compose の `environment` に追加）。

```yaml
environment:
  BASE_PATH: "/esmile009"
```

nginx が同じホストで **`https://example.com/esmile009/`** をコンテナへ送る例です。

```nginx
location /esmile009/ {
    proxy_pass http://127.0.0.1:18083/esmile009/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

変換 API は **`POST https://example.com/esmile009/convert`** になります。

※ nginx で **`/esmile009` を削ってから**バックエンドの `/health` に転送している場合は、アプリ側の `BASE_PATH` は空のままで構いません。

### 別サーバー（Apache）→ このマシンの公網 IP:18083（例: ProxyPass で `175.41.x.x:18083`）

このリポジトリの Compose は既定で **`127.0.0.1:18083` のみ**にバインドするため、**他ホストからは繋がりません**。EC2 にプロジェクト直下で **`.env`** を置いてください。

```bash
BIND_ADDRESS=0.0.0.0
```

そのうえで `docker compose up -d` をやり直すと **`0.0.0.0:18083`** で待ち受けます。  
AWS の **セキュリティグループ**は、`18083` の **ソースを Apache が動いているサーバーのパブリック IP / SG に限定**するのが安全です（世界中に開けるのは避けたいです）。

## ライセンス

（必要に応じて追記してください）
