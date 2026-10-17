from typing import Any

import httpx

from app.core.config import Settings, get_settings

SERVICE_TOKEN_HEADER = "X-Service-Token"
REQUEST_ID_HEADER = "X-Request-Id"


def normalize_measurement_spec(raw_spec: dict[str, Any] | None) -> dict[str, float]:
    if not raw_spec or not isinstance(raw_spec, dict):
        return {}

    normalized: dict[str, float] = {}
    for raw_key, raw_val in raw_spec.items():
        if raw_val is None:
            continue
        try:
            numeric_val = float(raw_val)
        except (TypeError, ValueError):
            continue

        clean_key = str(raw_key).strip()
        if clean_key and numeric_val > 0:
            normalized[clean_key] = numeric_val

    return normalized


class ProductServiceClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(
            self.settings.product_service_url.strip()
            and self.settings.recommendation_service_token.strip()
        )

    def get_product_measurements(
        self,
        product_ids: list[int],
        request_id_header: str | None = None,
    ) -> dict[int, list[dict[str, Any]]]:
        distinct_ids = sorted({int(pid) for pid in product_ids if pid and int(pid) > 0})
        if not distinct_ids or not self.is_configured:
            return {}

        base_url = self.settings.product_service_url.rstrip("/")
        url = f"{base_url}/products/measurements"
        params = {"productIds": ",".join(str(pid) for pid in distinct_ids)}
        headers = {
            SERVICE_TOKEN_HEADER: self.settings.recommendation_service_token,
        }
        if request_id_header:
            headers[REQUEST_ID_HEADER] = request_id_header

        try:
            with httpx.Client(timeout=self.settings.http_timeout_seconds) as client:
                response = client.get(url, params=params, headers=headers)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    return {}

                measurements_by_product: dict[int, list[dict[str, Any]]] = {}
                for entry in payload:
                    if not isinstance(entry, dict):
                        continue
                    pid = entry.get("productId")
                    if pid is None:
                        continue
                    options = entry.get("options") or []
                    parsed_options: list[dict[str, Any]] = []
                    for opt in options:
                        if not isinstance(opt, dict):
                            continue
                        spec = normalize_measurement_spec(opt.get("measurementSpec"))
                        if not spec:
                            continue
                        parsed_options.append(
                            {
                                "option_id": opt.get("optionId"),
                                "color": opt.get("color"),
                                "size": opt.get("size") or "FREE",
                                "measurements": spec,
                            }
                        )
                    measurements_by_product[int(pid)] = parsed_options
                return measurements_by_product
        except Exception as exc:
            print(
                f"[WARN] product-service 실측 조회 실패 (productIds={distinct_ids}): "
                f"{type(exc).__name__}: {exc}"
            )
            return {}

    def find_option_measurement(
        self,
        product_id: int,
        option_id: int,
        request_id_header: str | None = None,
    ) -> dict[str, float] | None:
        measurements_by_product = self.get_product_measurements(
            [product_id],
            request_id_header=request_id_header,
        )
        options = measurements_by_product.get(int(product_id), [])
        for option in options:
            if option.get("option_id") == option_id:
                return option.get("measurements")
        if options:
            return options[0].get("measurements")
        return None
