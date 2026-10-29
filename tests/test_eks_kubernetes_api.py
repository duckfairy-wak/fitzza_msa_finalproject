from unittest.mock import Mock

from infra.aws.orchestration.eks_kubernetes_api import EksKubernetesApi, KubernetesApiError


def test_http_error_exposes_status():
    error = KubernetesApiError(404, "missing")
    assert error.status == 404
    assert str(error) == "missing"


def test_read_and_create_use_batch_api_paths(monkeypatch):
    client = object.__new__(EksKubernetesApi)
    client._request = Mock(side_effect=[{"metadata": {"name": "job"}}, {"metadata": {"name": "job"}}])

    client.read_namespaced_job("job", "fitzza")
    client.create_namespaced_job("fitzza", {"kind": "Job"})

    assert client._request.call_args_list[0].args == ("GET", "/apis/batch/v1/namespaces/fitzza/jobs/job")
    assert client._request.call_args_list[1].args == ("POST", "/apis/batch/v1/namespaces/fitzza/jobs", {"kind": "Job"})


def test_token_is_presigned_for_the_regional_sts_endpoint():
    import base64
    from urllib.parse import parse_qs, urlparse

    from botocore.credentials import Credentials

    client = object.__new__(EksKubernetesApi)
    client.region = "ap-northeast-2"
    client.cluster_name = "fitzza-prod"
    client.session = Mock()
    client.session.get_credentials.return_value = Credentials("AKIDEXAMPLE", "secret")

    token = client._token()

    assert token.startswith("k8s-aws-v1.")
    encoded = token.removeprefix("k8s-aws-v1.")
    url = urlparse(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode())
    query = parse_qs(url.query)
    assert url.netloc == "sts.ap-northeast-2.amazonaws.com"
    assert "/ap-northeast-2/sts/aws4_request" in query["X-Amz-Credential"][0]
    assert "x-k8s-aws-id" in query["X-Amz-SignedHeaders"][0]
