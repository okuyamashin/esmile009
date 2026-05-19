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

## 環境変数（Compose）

| 名前 | 説明 |
|------|------|
| `MAX_UPLOAD_BYTES` | アップロード上限（既定 15MB） |
| `CONVERT_TIMEOUT_SEC` | LibreOffice のタイムアウト秒（既定 120） |

ホストのポートは `docker-compose.yml` の `ports` で変更してください。`convert.sh` の既定 `API_URL` も合わせて調整します。

## ライセンス

（必要に応じて追記してください）
