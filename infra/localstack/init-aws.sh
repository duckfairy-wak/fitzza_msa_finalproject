#!/bin/sh
set -eu

awslocal s3 mb s3://fitzza-assets || true
awslocal sqs create-queue --queue-name virtual-tryon-jobs >/dev/null
awslocal sqs create-queue --queue-name notification-events >/dev/null
