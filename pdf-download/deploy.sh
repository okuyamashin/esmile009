#!/usr/bin/env bash
# CloudFront + S3 + Lambda の PDF ダウンロード画面をデプロイする。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

DOMAIN="${DOMAIN:-esmile009.engawa5656.com}"
HOSTED_ZONE_ID="${HOSTED_ZONE_ID:-Z2ZKUPPLN2ZWXX}"
ALB_ARN="${ALB_ARN:-arn:aws:elasticloadbalancing:ap-northeast-1:868118155022:loadbalancer/app/esmile009-api-alb/dbdc0199f1fa84b3}"
ALB_TG_ARN="${ALB_TG_ARN:-arn:aws:elasticloadbalancing:ap-northeast-1:868118155022:targetgroup/esmile009-api-tg/304b9aa2bc8aa83a}"
ALB_SG="${ALB_SG:-sg-0c293cc8e8af6da0c}"
STACK_NAME="${STACK_NAME:-esmile009-pdf-download}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-northeast-1}}"
SECRET_FILE="${ROOT}/.origin-secret"

if [[ ! -f "$SECRET_FILE" ]]; then
  python3 - <<'PY' > "$SECRET_FILE"
import secrets
print(secrets.token_urlsafe(32))
PY
fi
ORIGIN_SECRET="$(tr -d '[:space:]' < "$SECRET_FILE")"

echo "=== ALB HTTP:80 ==="
if aws elbv2 describe-listeners --load-balancer-arn "$ALB_ARN" \
  --query "Listeners[?Port==\`80\`].ListenerArn" --output text | grep -q .; then
  echo "HTTP listener already exists"
else
  aws elbv2 create-listener \
    --load-balancer-arn "$ALB_ARN" \
    --protocol HTTP \
    --port 80 \
    --default-actions "Type=forward,TargetGroupArn=${ALB_TG_ARN}" >/dev/null
  echo "created HTTP listener"
fi

if ! aws ec2 describe-security-groups --group-ids "$ALB_SG" \
  --query "SecurityGroups[0].IpPermissions[?FromPort==\`80\`]" --output text | grep -q .; then
  aws ec2 authorize-security-group-ingress \
    --group-id "$ALB_SG" \
    --ip-permissions 'IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0,Description=CloudFront origin HTTP}]' >/dev/null
  echo "opened SG 80"
else
  echo "SG 80 already open"
fi

echo "=== ACM us-east-1 ==="
CERT_ARN="$(aws acm list-certificates --region us-east-1 \
  --query "CertificateSummaryList[?DomainName=='${DOMAIN}'].CertificateArn | [0]" \
  --output text)"
if [[ -z "$CERT_ARN" || "$CERT_ARN" == "None" ]]; then
  CERT_ARN="$(aws acm request-certificate --region us-east-1 \
    --domain-name "$DOMAIN" \
    --validation-method DNS \
    --options CertificateTransparencyLoggingPreference=ENABLED \
    --idempotency-token esmile009cf1 \
    --query CertificateArn --output text)"
  echo "requested $CERT_ARN"
else
  echo "existing $CERT_ARN"
fi

for _ in $(seq 1 12); do
  CNAME_NAME="$(aws acm describe-certificate --region us-east-1 --certificate-arn "$CERT_ARN" \
    --query 'Certificate.DomainValidationOptions[0].ResourceRecord.Name' --output text)"
  CNAME_VALUE="$(aws acm describe-certificate --region us-east-1 --certificate-arn "$CERT_ARN" \
    --query 'Certificate.DomainValidationOptions[0].ResourceRecord.Value' --output text)"
  if [[ -n "$CNAME_NAME" && "$CNAME_NAME" != "None" ]]; then
    break
  fi
  sleep 5
done

CHANGE_BATCH="$(python3 - <<PY
import json
print(json.dumps({
  "Changes": [{
    "Action": "UPSERT",
    "ResourceRecordSet": {
      "Name": "${CNAME_NAME}",
      "Type": "CNAME",
      "TTL": 300,
      "ResourceRecords": [{"Value": "${CNAME_VALUE}"}]
    }
  }]
}))
PY
)"
aws route53 change-resource-record-sets --hosted-zone-id "$HOSTED_ZONE_ID" \
  --change-batch "$CHANGE_BATCH" >/dev/null
echo "validation CNAME upserted: $CNAME_NAME"

echo "waiting for certificate ISSUED..."
for _ in $(seq 1 60); do
  CERT_STATUS="$(aws acm describe-certificate --region us-east-1 --certificate-arn "$CERT_ARN" \
    --query 'Certificate.Status' --output text)"
  if [[ "$CERT_STATUS" == "ISSUED" ]]; then
    break
  fi
  sleep 10
done
if [[ "${CERT_STATUS:-}" != "ISSUED" ]]; then
  echo "certificate not issued: ${CERT_STATUS:-unknown}" >&2
  exit 1
fi
echo "certificate issued"

echo "=== SAM deploy ==="
sam build --template-file template.yaml
sam deploy \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset \
  --parameter-overrides \
    "DomainName=${DOMAIN}" \
    "CertificateArn=${CERT_ARN}" \
    "OriginSecret=${ORIGIN_SECRET}"

CF_DOMAIN="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDomain'].OutputValue" --output text)"
DIST_ID="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='DistributionId'].OutputValue" --output text)"
WEB_BUCKET="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='WebBucketName'].OutputValue" --output text)"

echo "=== upload frontend ==="
aws s3 sync frontend/ "s3://${WEB_BUCKET}/" --delete --cache-control "no-cache"

echo "=== Route53 alias ==="
CF_ZONE="Z2FDTNDATAQYW2"
DNS_BATCH="$(python3 - <<PY
import json
print(json.dumps({
  "Changes": [
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "${DOMAIN}.",
        "Type": "A",
        "AliasTarget": {
          "HostedZoneId": "${CF_ZONE}",
          "DNSName": "${CF_DOMAIN}",
          "EvaluateTargetHealth": False
        }
      }
    },
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "${DOMAIN}.",
        "Type": "AAAA",
        "AliasTarget": {
          "HostedZoneId": "${CF_ZONE}",
          "DNSName": "${CF_DOMAIN}",
          "EvaluateTargetHealth": False
        }
      }
    }
  ]
}))
PY
)"
aws route53 change-resource-record-sets --hosted-zone-id "$HOSTED_ZONE_ID" \
  --change-batch "$DNS_BATCH" >/dev/null

echo "=== invalidate ==="
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*" >/dev/null

echo "完了: https://${DOMAIN}/"
echo "CloudFront: https://${CF_DOMAIN}/"
echo "基本認証: esmile / osaka  または  engawa / SUSUKINO"
