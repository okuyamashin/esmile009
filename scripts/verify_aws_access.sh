#!/usr/bin/env bash
# ses002 と同様: ~/.aws/credentials または環境変数で AWS 認証を確認する。
set -euo pipefail

echo "=== AWS CLI ==="
command -v aws >/dev/null || { echo "aws CLI が見つかりません"; exit 1; }
aws --version

echo ""
echo "=== 呼び出し元 (sts get-caller-identity) ==="
aws sts get-caller-identity

echo ""
echo "=== 設定 (aws configure list) ==="
aws configure list

REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-northeast-1}}"
echo ""
echo "=== リージョン: ${REGION} ==="

# ses002 で使っているバケット（読み取りのみ・先頭数行）
BUCKET="${VERIFY_S3_BUCKET:-ses-mail-dx-engawa5656}"
echo ""
echo "=== S3 一覧 (先頭) s3://${BUCKET}/ ==="
if aws s3 ls "s3://${BUCKET}/" 2>/dev/null | head -5; then
  echo "(OK)"
else
  echo "S3 にアクセスできません。バケット名・権限を確認してください。"
fi

echo ""
echo "=== Route53 ホストゾーン (名前のみ) ==="
aws route53 list-hosted-zones --query 'HostedZones[*].Name' --output text 2>/dev/null || echo "Route53 一覧に失敗（権限不足の可能性）"

echo ""
echo "完了。キーは表示していません。"
