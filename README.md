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

## Chrome 拡張（準備中）

`chrome-extension/` に Manifest V3 の雛形があります。開発者向け手順は同ディレクトリの `chrome-extension/README.md` を見てください。

## 環境変数（Compose）

| 名前 | 説明 |
|------|------|
| `MAX_UPLOAD_BYTES` | アップロード上限（既定 15MB） |
| `CONVERT_TIMEOUT_SEC` | LibreOffice のタイムアウト秒（既定 120） |
| `BASE_PATH` | URL のサブパス（例: `/esmile009`）。Apache がプレフィックスを削るときは不要 |
| `BIND_ADDRESS` | ホストにバインドするアドレス（既定 `127.0.0.1`）。**別マシンの Apache が `ProxyPass http://このEC2のIP:18083/` のときは `0.0.0.0`** にする |

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
