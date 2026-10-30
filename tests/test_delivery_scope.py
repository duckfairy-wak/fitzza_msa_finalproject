import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_delivery_template_does_not_grant_cluster_admin():
    template = (ROOT / "infra/aws/cloudformation/delivery.yaml").read_text()
    assert "AmazonEKSClusterAdminPolicy" not in template
    assert "KubernetesGroups: [fitzza-delivery]" in template
    spec = (ROOT / "deployspec.yml").read_text()
    assert "overlays/delivery" in spec
    assert "get secret" not in spec


def test_production_delivery_uses_main_branch():
    template = (ROOT / "infra/aws/cloudformation/delivery.yaml").read_text()
    parameters = (ROOT / "infra/aws/cloudformation/delivery-parameters.example.json").read_text()
    assert "SourceBranch:\n    Type: String\n    Default: main" in template
    assert '"SourceBranch", "ParameterValue": "main"' in parameters


def test_artifact_endpoint_is_opt_in_and_account_scoped():
    template = (ROOT / "infra/aws/cloudformation/foundation.yaml").read_text()
    assert "HasDeliveryArtifactBucket: !Not" in template
    assert "aws:PrincipalAccount: !Ref AWS::AccountId" in template
    assert "s3:::${DeliveryArtifactBucketName}/*" in template


def test_product_images_use_private_s3_origin_and_prefix_scoped_cloudfront_access():
    template = (ROOT / "infra/aws/cloudformation/foundation.yaml").read_text()
    assert "Type: AWS::CloudFront::OriginAccessControl" in template
    assert "SigningBehavior: always" in template
    assert "OriginPath: /public/product-images" in template
    assert "ViewerProtocolPolicy: redirect-to-https" in template
    assert "Resource: !Sub '${DataBucket.Arn}/public/product-images/*'" in template
    assert "AWS:SourceAccount: !Ref AWS::AccountId" in template
    assert "AWS:SourceArn: !Sub 'arn:${AWS::Partition}:cloudfront::${AWS::AccountId}:distribution/${ProductImageDistribution}'" in template


def test_vton_runtime_endpoint_access_is_role_and_bucket_scoped():
    template = (ROOT / "infra/aws/cloudformation/foundation.yaml").read_text()
    assert "Sid: AllowVtonRuntimeAssets" in template
    assert "s3:::${ProjectName}-${Environment}-assets-vton/*" in template
    assert "aws:PrincipalArn: !GetAtt VtonRuntimeRole.Arn" in template
    assert "Action: [s3:GetObject, s3:PutObject, s3:DeleteObject]" in template


def test_production_vton_uses_aws_backends():
    config = (ROOT / "infra/k8s/base/configmap.yaml").read_text(encoding="utf-8")
    assert "VTON_STORAGE_BACKEND: s3" in config
    assert "VTON_QUEUE_BACKEND: sqs" in config
    assert "AWS_SQS_QUEUE_URL: CHANGE_ME_VTON_JOB_QUEUE_URL" in config
    assert "AWS_SQS_DLQ_URL: CHANGE_ME_VTON_JOB_DLQ_URL" in config
    assert 'SQS_MAX_RECEIVE_COUNT: "3"' in config


def test_vton_queue_has_bounded_retry_dlq_and_transport_protection():
    template = (ROOT / "infra/aws/cloudformation/foundation.yaml").read_text()
    assert "VtonJobQueue:" in template
    assert "VtonJobDeadLetterQueue:" in template
    assert "ReceiveMessageWaitTimeSeconds: 20" in template
    assert "VisibilityTimeout: 300" in template
    assert "maxReceiveCount: 3" in template
    assert "redrivePermission: byQueue" in template
    assert template.count("SqsManagedSseEnabled: true") >= 2
    assert "Sid: DenyInsecureTransport" in template
    assert "Action: sqs:*" in template


def test_vton_uses_dedicated_pod_identity_and_least_privilege_queue_role():
    template = (ROOT / "infra/aws/cloudformation/foundation.yaml").read_text()
    apps = (ROOT / "infra/k8s/base/apps.yaml").read_text()
    service_accounts = (ROOT / "infra/k8s/base/service-account.yaml").read_text()
    assert "VtonRuntimePodIdentityAssociation:" in template
    assert "ServiceAccount: fitzza-vton" in template
    assert "Resource: !GetAtt VtonJobQueue.Arn" in template
    assert "sqs:SendMessage" in template
    assert "sqs:ReceiveMessage" in template
    assert "name: fitzza-vton" in service_accounts
    assert apps.count("serviceAccountName: fitzza-vton") == 2


def test_only_qdrant_reading_workloads_pass_qdrant_network_policy():
    yaml = pytest.importorskip("yaml")
    apps = list(yaml.safe_load_all((ROOT / "infra/k8s/base/apps.yaml").read_text(encoding="utf-8")))
    qdrant = list(yaml.safe_load_all((ROOT / "infra/k8s/base/qdrant.yaml").read_text(encoding="utf-8")))
    policy = next(doc for doc in qdrant if doc and doc.get("kind") == "NetworkPolicy")
    allowed = policy["spec"]["ingress"][0]["from"][0]["podSelector"]["matchLabels"]
    assert allowed == {"fitzza.io/qdrant-client": "true"}

    clients = {
        doc["metadata"]["name"]
        for doc in apps
        if doc and doc.get("kind") == "Deployment"
        and doc["spec"]["template"]["metadata"]["labels"].get("fitzza.io/qdrant-client") == "true"
    }
    # vton-worker는 피팅 작업에서 상품 메타데이터를 Qdrant로 조회한다. 요청만 큐에 넣는 vton-service API에는 열지 않는다.
    assert clients == {"recommendation-service", "vton-worker"}


def test_grafana_uses_pod_identity_for_cloudwatch_metrics_only():
    yaml = pytest.importorskip("yaml")
    template = (
        ROOT / "infra/aws/cloudformation/grafana-cloudwatch.yaml"
    ).read_text()
    values = yaml.safe_load(
        (ROOT / "infra/k8s/observability/prometheus/values.yaml").read_text()
    )

    grafana = values["grafana"]
    assert grafana["serviceAccount"] == {
        "create": True,
        "name": "fitzza-monitoring-grafana",
    }
    assert grafana["additionalDataSources"] == [
        {
            "name": "CloudWatch",
            "uid": "cloudwatch",
            "type": "cloudwatch",
            "access": "proxy",
            "editable": False,
            "isDefault": False,
            "jsonData": {
                "authType": "default",
                "defaultRegion": "ap-northeast-2",
            },
        }
    ]

    role_block = template[
        template.index("  GrafanaCloudWatchRole:\n"):
        template.index("  GrafanaCloudWatchPodIdentityAssociation:\n")
    ]
    association_block = template[
        template.index("  GrafanaCloudWatchPodIdentityAssociation:\n"):
        template.index("\nOutputs:")
    ]
    assert "Principal: { Service: pods.eks.amazonaws.com }" in role_block
    assert "aws:RequestTag/eks-cluster-arn: !Sub" in role_block
    assert "cloudwatch:GetMetricData" in role_block
    assert "cloudwatch:ListMetrics" in role_block
    assert "aws:RequestedRegion:" in role_block
    assert "- ap-northeast-2" in role_block
    assert "- us-east-1" in role_block
    assert "logs:" not in role_block
    assert "Default: fitzza-monitoring" in template
    assert "Default: fitzza-monitoring-grafana" in template
    assert "Namespace: !Ref GrafanaNamespace" in association_block
    assert "ServiceAccount: !Ref GrafanaServiceAccount" in association_block
    assert values["kube-state-metrics"]["image"] == {
        "registry": "asia-east1-docker.pkg.dev",
        "repository": (
            "k8s-artifacts-prod/images/kube-state-metrics/kube-state-metrics"
        ),
        "tag": "v2.20.0",
    }


def test_prometheus_preflight_accepts_current_helm_crd_output_path():
    script = (ROOT / "scripts/deploy_prometheus_stack.ps1").read_text(
        encoding="utf-8"
    )
    assert "Join-Path $manifestRoot 'crds'" in script
    assert "Join-Path $manifestRoot 'charts/crds/crds'" in script
    assert "foreach ($crdRootCandidate in $crdRootCandidates)" in script
    assert "'--skip-tests'" in script
    assert (
        "'apply', '--server-side', '--force-conflicts', '--dry-run=server', "
        "'--recursive'" in script
    )


def test_base_tracing_stays_disabled_without_a_production_overlay():
    config = (ROOT / "infra/k8s/base/configmap.yaml").read_text(encoding="utf-8")
    assert "MANAGEMENT_OTLP_TRACING_ENDPOINT" not in config
    assert "MANAGEMENT_TRACING_SAMPLING_PROBABILITY" not in config


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl unavailable")
def test_production_overlay_enables_approved_jaeger_sampling():
    yaml = pytest.importorskip("yaml")
    result = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "infra/k8s/overlays/prod")],
        check=True, capture_output=True, text=True, timeout=30,
    )
    documents = list(yaml.safe_load_all(result.stdout))
    config = next(
        document for document in documents
        if document["kind"] == "ConfigMap"
        and document["metadata"]["name"] == "fitzza-app-config"
    )
    assert config["data"]["MANAGEMENT_OTLP_TRACING_ENDPOINT"] == (
        "http://jaeger:4318/v1/traces"
    )
    assert config["data"]["MANAGEMENT_TRACING_SAMPLING_PROBABILITY"] == "0.1"


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl unavailable")
def test_jaeger_pilot_is_internal_and_resource_bounded():
    yaml = pytest.importorskip("yaml")
    result = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "infra/k8s/observability/jaeger")],
        check=True, capture_output=True, text=True, timeout=30,
    )
    documents = list(yaml.safe_load_all(result.stdout))
    deployment = next(document for document in documents if document["kind"] == "Deployment")
    service = next(document for document in documents if document["kind"] == "Service")
    config = next(document for document in documents if document["kind"] == "ConfigMap")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert deployment["metadata"]["namespace"] == "fitzza"
    assert container["image"] == "cr.jaegertracing.io/jaegertracing/jaeger:2.22.0"
    assert container["resources"]["requests"] == {"cpu": "50m", "memory": "128Mi"}
    assert container["resources"]["limits"] == {"cpu": "500m", "memory": "512Mi"}
    assert "max_traces: 1000" in config["data"]["config.yaml"]
    assert service["spec"]["type"] == "ClusterIP"
    assert {port["port"] for port in service["spec"]["ports"]} == {4317, 4318, 16686}


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl unavailable")
def test_delivery_overlay_excludes_operator_owned_resources():
    yaml = pytest.importorskip("yaml")
    result = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "infra/k8s/overlays/delivery")],
        check=True, capture_output=True, text=True, timeout=30,
    )
    documents = list(yaml.safe_load_all(result.stdout))
    deployments = [d for d in documents if d["kind"] == "Deployment"]
    assert len(deployments) == 12
    vton_worker = next(d for d in deployments if d["metadata"]["name"] == "vton-worker")
    worker_container = vton_worker["spec"]["template"]["spec"]["containers"][0]
    assert worker_container["command"] == ["python", "-m", "app.worker"]
    openai_env = next(env for env in worker_container["env"] if env["name"] == "OPENAI_API_KEY")
    assert openai_env["valueFrom"]["secretKeyRef"] == {
        "name": "fitzza-app-secrets", "key": "OPENAI_API_KEY"
    }
    assert all(d["spec"]["progressDeadlineSeconds"] == 900 for d in deployments)
    assert all(d["kind"] in {"Deployment", "Service", "ConfigMap", "Ingress"}
               for d in documents)
    assert all(d["metadata"]["namespace"] == "fitzza" for d in documents)
    assert not any(d["kind"] == "Deployment" and d["metadata"]["name"] == "redis"
                   for d in documents)


def test_delivery_role_has_no_secret_storage_or_rbac_mutation():
    yaml = pytest.importorskip("yaml")
    role, binding = yaml.safe_load_all(
        (ROOT / "infra/k8s/bootstrap/delivery-rbac.yaml").read_text()
    )
    assert role["metadata"]["namespace"] == binding["metadata"]["namespace"] == "fitzza"
    assert binding["subjects"] == [
        {"kind": "Group", "name": "fitzza-delivery", "apiGroup": "rbac.authorization.k8s.io"}
    ]
    assert binding["roleRef"] == {
        "kind": "Role", "name": role["metadata"]["name"], "apiGroup": "rbac.authorization.k8s.io"
    }
    for rule in role["rules"]:
        assert "*" not in rule["verbs"] + rule["resources"] + rule["apiGroups"]
        assert "secrets" not in rule["resources"]
        assert "rbac.authorization.k8s.io" not in rule["apiGroups"]
        if set(rule["resources"]) & {"persistentvolumeclaims", "statefulsets"}:
            assert set(rule["verbs"]) <= {"get", "list", "watch"}
