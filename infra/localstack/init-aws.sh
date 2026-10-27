#!/bin/sh
set -eu

awslocal s3 mb s3://fitzza-assets || true
awslocal s3 mb s3://fitzza-prod-assets-vton || true
vton_dlq_url="$(awslocal sqs create-queue \
  --queue-name vton-jobs-dlq \
  --attributes MessageRetentionPeriod=1209600 \
  --query QueueUrl \
  --output text)"
vton_dlq_arn="$(awslocal sqs get-queue-attributes \
  --queue-url "$vton_dlq_url" \
  --attribute-names QueueArn \
  --query Attributes.QueueArn \
  --output text)"
vton_queue_attributes="$(printf \
  '{"VisibilityTimeout":"300","ReceiveMessageWaitTimeSeconds":"20","RedrivePolicy":"{\\"deadLetterTargetArn\\":\\"%s\\",\\"maxReceiveCount\\":\\"3\\"}"}' \
  "$vton_dlq_arn")"
awslocal sqs create-queue \
  --queue-name vton-jobs \
  --attributes "$vton_queue_attributes" >/dev/null
awslocal sqs create-queue --queue-name virtual-tryon-jobs >/dev/null
awslocal sqs create-queue --queue-name notification-events >/dev/null
