"""Minimal EKS Kubernetes API client for Lambda Job adapters."""

from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.request
from typing import Any

import boto3
from botocore.awsrequest import AWSRequest
from botocore.auth import SigV4QueryAuth


class KubernetesApiError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class EksKubernetesApi:
    """Kubernetes batch API client using the Lambda role's EKS IAM identity."""

    def __init__(self, cluster_name: str, region: str, session: Any | None = None):
        self.region = region
        self.session = session or boto3.Session(region_name=region)
        eks = self.session.client("eks", region_name=region)
        cluster = eks.describe_cluster(name=cluster_name)["cluster"]
        self.endpoint = cluster["endpoint"].rstrip("/")
        self.ca_data = base64.b64decode(cluster["certificateAuthority"]["data"])
        self.cluster_name = cluster_name

    def _token(self) -> str:
        credentials = self.session.get_credentials().get_frozen_credentials()
        request = AWSRequest(
            method="GET",
            # The presigned host must be the regional endpoint that matches the signing region.
            url=f"https://sts.{self.region}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15",
            headers={"x-k8s-aws-id": self.cluster_name},
        )
        SigV4QueryAuth(credentials, "sts", self.region, expires=60).add_auth(request)
        encoded = base64.urlsafe_b64encode(request.url.encode()).decode().rstrip("=")
        return f"k8s-aws-v1.{encoded}"

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        request = urllib.request.Request(
            f"{self.endpoint}{path}",
            data=payload,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        context = ssl.create_default_context(cadata=self.ca_data.decode())
        try:
            with urllib.request.urlopen(request, context=context, timeout=30) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise KubernetesApiError(error.code, detail) from error

    def read_namespaced_job(self, name: str, namespace: str) -> dict[str, Any]:
        return self._request("GET", f"/apis/batch/v1/namespaces/{namespace}/jobs/{name}")

    def create_namespaced_job(self, namespace: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/apis/batch/v1/namespaces/{namespace}/jobs", body)
