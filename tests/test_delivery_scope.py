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
    assert "role/${ProjectName}-${Environment}-vton-runtime" in template
    assert "Action: [s3:GetObject, s3:PutObject, s3:DeleteObject]" in template


def test_production_vton_uses_aws_backends():
    config = (ROOT / "infra/k8s/base/configmap.yaml").read_text()
    assert "VTON_STORAGE_BACKEND: s3" in config
    assert "VTON_QUEUE_BACKEND: sqs" in config


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
