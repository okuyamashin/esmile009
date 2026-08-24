# esmile009.engawa5656.com（AWS 構成メモ）

## 構成

| 項目 | 値 |
|------|-----|
| 公開 URL | `https://esmile009.engawa5656.com` |
| Route53 | `esmile009.engawa5656.com` → ALB（エイリアス） |
| ALB | `esmile009-api-alb`（HTTPS 443） |
| ACM | `esmile009.engawa5656.com`（ap-northeast-1） |
| ターゲット | EC2 `i-03eb3d0cea8a41d29`（`175.41.196.33`）ポート **18083** |
| API | ルート直下 `/health` `/convert` `/jobs`（`BASE_PATH` 不要） |

## 動作確認

```bash
curl -sS https://esmile009.engawa5656.com/health
```

## EC2 側の前提

- `docker compose up -d` で API が起動している
- `BIND_ADDRESS=0.0.0.0`（ALB から 18083 へ届くこと）
- セキュリティグループで **18083** が ALB / 必要ソースから到達可能

## 以前の Apache 経由（engawa2525.com/esmile009/）との違い

- サブドメイン直結なので **パスプレフィックス `/esmile009` は不要**
- Chrome 拡張の API ベース URL は  
  **`https://esmile009.engawa5656.com`**

## 再作成時の AWS CLI 概要

証明書・ALB・Route53 はコンソールまたは CLI で管理。  
検証用: `./scripts/verify_aws_access.sh`
