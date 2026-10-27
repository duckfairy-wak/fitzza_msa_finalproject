#!/usr/bin/env python3
"""Render validated production-only values into the packaged Kubernetes manifests."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlparse


RDS_ENDPOINT_PATTERN = re.compile(r"^[A-Za-z0-9.-]+$")
SECURITY_GROUP_PATTERN = re.compile(r"^sg-[0-9a-f]+$")
DOMAIN_PATTERN = re.compile(r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")
CERTIFICATE_ARN_PATTERN = re.compile(
    r"^arn:(?:aws|aws-us-gov|aws-cn):acm:[a-z0-9-]+:\d{12}:certificate/[0-9a-f-]+$"
)
SQS_QUEUE_URL_PATTERN = re.compile(
    r"^https://sqs\.[a-z0-9-]+\.amazonaws\.com(?:\.cn)?/\d{12}/[A-Za-z0-9_-]{1,80}$"
)


def validate_frontend_origin(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("frontend origin must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("frontend origin must not include credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("frontend origin must not include a path")
    return value.rstrip("/")


def require_match(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not pattern.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def replace_once(content: str, old: str, new: str, label: str) -> str:
    count = content.count(old)
    if count != 1:
        raise ValueError(f"expected exactly one {label} placeholder, found {count}")
    return content.replace(old, new)


def render(
    root: Path,
    rds_endpoint: str,
    frontend_origin: str,
    alb_security_group_id: str,
    vton_job_queue_url: str,
    vton_job_dlq_url: str,
    api_domain: str = "",
    acm_certificate_arn: str = "",
) -> None:
    rds_endpoint = require_match(rds_endpoint, RDS_ENDPOINT_PATTERN, "RDS endpoint")
    frontend_origin = validate_frontend_origin(frontend_origin)
    alb_security_group_id = require_match(
        alb_security_group_id, SECURITY_GROUP_PATTERN, "ALB security group ID"
    )
    vton_job_queue_url = require_match(
        vton_job_queue_url, SQS_QUEUE_URL_PATTERN, "VTON job queue URL"
    )
    vton_job_dlq_url = require_match(
        vton_job_dlq_url, SQS_QUEUE_URL_PATTERN, "VTON job DLQ URL"
    )
    if vton_job_queue_url == vton_job_dlq_url:
        raise ValueError("VTON job queue and DLQ URLs must differ")

    has_domain = bool(api_domain)
    has_certificate = bool(acm_certificate_arn)
    if has_domain != has_certificate:
        raise ValueError("API domain and ACM certificate ARN must be supplied together")
    if has_domain:
        api_domain = require_match(api_domain, DOMAIN_PATTERN, "API domain")
        acm_certificate_arn = require_match(
            acm_certificate_arn, CERTIFICATE_ARN_PATTERN, "ACM certificate ARN"
        )

    configmap_path = root / "infra/k8s/base/configmap.yaml"
    ingress_path = root / "infra/k8s/base/ingress.yaml"

    configmap = configmap_path.read_text(encoding="utf-8")
    configmap = replace_once(
        configmap, "CHANGE_ME_RDS_ENDPOINT", rds_endpoint, "RDS endpoint"
    )
    configmap = replace_once(
        configmap, "CHANGE_ME_FRONTEND_ORIGIN", frontend_origin, "frontend origin"
    )
    # Browsers drop Secure cookies over plain HTTP, so the flag follows the TLS inputs.
    configmap = replace_once(
        configmap,
        "CHANGE_ME_REFRESH_COOKIE_SECURE",
        '"true"' if has_domain else '"false"',
        "refresh cookie security",
    )
    configmap = replace_once(
        configmap,
        "CHANGE_ME_VTON_JOB_QUEUE_URL",
        vton_job_queue_url,
        "VTON job queue URL",
    )
    configmap = replace_once(
        configmap,
        "CHANGE_ME_VTON_JOB_DLQ_URL",
        vton_job_dlq_url,
        "VTON job DLQ URL",
    )

    ingress = ingress_path.read_text(encoding="utf-8")
    ingress = replace_once(
        ingress,
        "CHANGE_ME_ALB_SECURITY_GROUP_ID",
        alb_security_group_id,
        "ALB security group",
    )
    if has_domain:
        ingress = replace_once(
            ingress,
            "CHANGE_ME_ACM_CERTIFICATE_ARN",
            acm_certificate_arn,
            "ACM certificate",
        )
        ingress = replace_once(ingress, "CHANGE_ME_API_DOMAIN", api_domain, "API domain")
    else:
        ingress = ingress.replace(
            '    alb.ingress.kubernetes.io/listen-ports: \'[{"HTTP": 80}, {"HTTPS": 443}]\'\n',
            '    alb.ingress.kubernetes.io/listen-ports: \'[{"HTTP": 80}]\'\n',
        )
        ingress = ingress.replace(
            '    alb.ingress.kubernetes.io/ssl-redirect: "443"\n', ""
        )
        ingress = ingress.replace(
            "    alb.ingress.kubernetes.io/certificate-arn: CHANGE_ME_ACM_CERTIFICATE_ARN\n",
            "",
        )
        ingress = ingress.replace("    - host: CHANGE_ME_API_DOMAIN\n", "    -\n")

    unresolved = []
    for path, content in ((configmap_path, configmap), (ingress_path, ingress)):
        if "CHANGE_ME_" in content:
            unresolved.append(str(path))
    if unresolved:
        raise ValueError(f"unresolved production placeholders: {', '.join(unresolved)}")
    # Validate both documents before writing either, so invalid input can be corrected and retried.
    configmap_path.write_text(configmap, encoding="utf-8", newline="\n")
    ingress_path.write_text(ingress, encoding="utf-8", newline="\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--rds-endpoint", required=True)
    parser.add_argument("--frontend-origin", required=True)
    parser.add_argument("--alb-security-group-id", required=True)
    parser.add_argument("--vton-job-queue-url", required=True)
    parser.add_argument("--vton-job-dlq-url", required=True)
    parser.add_argument("--api-domain", default="")
    parser.add_argument("--acm-certificate-arn", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    render(
        root=args.root,
        rds_endpoint=args.rds_endpoint,
        frontend_origin=args.frontend_origin,
        alb_security_group_id=args.alb_security_group_id,
        vton_job_queue_url=args.vton_job_queue_url,
        vton_job_dlq_url=args.vton_job_dlq_url,
        api_domain=args.api_domain,
        acm_certificate_arn=args.acm_certificate_arn,
    )


if __name__ == "__main__":
    main()
