"""가상 피팅(VTON) 이미지 전처리, 프롬프트 생성 및 OpenAI 이미지 편집 서비스."""

from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError
from PIL import Image, UnidentifiedImageError

APP_DIR = Path(__file__).resolve().parents[1]
SERVICE_ROOT = APP_DIR.parent
PROJECT_ROOT = SERVICE_ROOT.parent

# vton-service/.env 또는 전체 프로젝트 루트의 .env 파일 자동 로드
load_dotenv(SERVICE_ROOT / ".env", override=False)
load_dotenv(PROJECT_ROOT / ".env", override=False)

DEFAULT_MODEL = "gpt-image-2.5-sunburst"

# 지원하는 5대 표준 카테고리 (product-service의 categoryL1Name과 동일)
SUPPORTED_CATEGORIES = ("상의", "하의", "아우터", "신발", "모자")


class VtonError(Exception):
    """가상 피팅 처리 기본 예외."""


class VtonValidationError(VtonError):
    """카테고리나 의류 이미지가 올바르지 않을 때 발생 (HTTP 400)."""


class VtonConfigurationError(VtonError):
    """기본 아바타 이미지나 OpenAI API 키 설정이 누락/손상되었을 때 발생 (HTTP 500)."""


class VtonUpstreamError(VtonError):
    """OpenAI 이미지 편집 API 호출 실패 시 발생 (HTTP 502)."""


from dataclasses import dataclass


@dataclass
class TryonResult:
    image_bytes: bytes
    prompt_tokens: int = 0
    completion_tokens: int = 0


def parse_categories(categories_input: str | list[str]) -> list[str]:
    """
    의류 카테고리를 검증하고 표준 카테고리 목록으로 파싱합니다.

    지원 형식:
    - JSON 배열 문자열: '["상의", "하의"]'
    - 쉼표 구분 문자열: '상의,하의'
    - 파이썬 리스트: ["상의", "하의"]
    """
    if isinstance(categories_input, list):
        raw_categories = categories_input
    elif isinstance(categories_input, str):
        cleaned_input = categories_input.strip()
        if not cleaned_input:
            raise VtonValidationError("최소 하나 이상의 카테고리를 선택해야 합니다.")
        try:
            if cleaned_input.startswith("["):
                raw_categories = json.loads(cleaned_input)
            else:
                raw_categories = [
                    item.strip()
                    for item in cleaned_input.split(",")
                    if item.strip()
                ]
        except json.JSONDecodeError as exc:
            raise VtonValidationError(
                '카테고리는 올바른 JSON 배열 형식(예: ["상의", "하의"]) 또는 쉼표 구분 문자열이어야 합니다.'
            ) from exc
    else:
        raise VtonValidationError("카테고리 형식이 올바르지 않습니다.")

    if not isinstance(raw_categories, list) or not raw_categories:
        raise VtonValidationError("최소 하나 이상의 카테고리를 선택해야 합니다.")

    if len(raw_categories) > len(SUPPORTED_CATEGORIES):
        raise VtonValidationError(f"카테고리는 최대 {len(SUPPORTED_CATEGORIES)}개까지 지원됩니다.")

    if any(not isinstance(item, str) for item in raw_categories):
        raise VtonValidationError("모든 카테고리는 문자열이어야 합니다.")

    categories = [item.strip() for item in raw_categories]

    unknown = [
        item for item in categories
        if item not in SUPPORTED_CATEGORIES
    ]
    if unknown:
        raise VtonValidationError(
            f"지원하지 않는 카테고리입니다: {unknown}. 허용 카테고리: {list(SUPPORTED_CATEGORIES)}"
        )

    if len(set(categories)) != len(categories):
        raise VtonValidationError("중복된 카테고리는 허용되지 않습니다.")

    return categories


def to_png_bytes(image_bytes: bytes) -> bytes:
    """
    이미지 바이트를 읽어 투명 배경을 흰색으로 합성한 뒤 RGB PNG 바이트로 변환합니다.
    """
    if not image_bytes:
        raise VtonValidationError("이미지 데이터가 비어 있습니다.")

    with Image.open(io.BytesIO(image_bytes)) as image:
        image.load()
        rgba_image = image.convert("RGBA")
        white_background = Image.new(
            "RGBA",
            rgba_image.size,
            (255, 255, 255, 255),
        )
        white_background.alpha_composite(rgba_image)

        buffer = io.BytesIO()
        white_background.convert("RGB").save(buffer, format="PNG")
        return buffer.getvalue()


def build_prompt(categories: list[str], *, has_user_face: bool = False) -> str:
    """OpenAI 이미지 편집 API에 전달할 한국어 지시문 프롬프트를 생성합니다."""
    start_index = 3 if has_user_face else 2
    clothing_instructions = "\n".join(
        f"- 참조 이미지 {index + start_index}: {category}"
        for index, category in enumerate(categories)
    )

    face_prompt_section = (
        """
[인물 얼굴 합성 요구사항]
1. 첫 번째 입력 이미지는 기본 전신 인물(아바타) 체형 및 포즈 참조 사진입니다.
2. 두 번째 입력 이미지는 사용자의 얼굴(인물) 사진입니다.
3. 아바타 인물의 전체적인 서 있는 포즈, 체형 비율, 어깨너비, 키 비율은 첫 번째 아바타 이미지를 그대로 따르되, 얼굴의 이목구비, 표정, 시선, 헤어스타일은 두 번째 사용자 얼굴 사진의 특징을 자연스럽게 반영하여 합성하세요.
4. 얼굴과 목, 어깨 연결선, 피부 톤이 어색함 없이 하나의 자연스러운 인물로 이어지도록 블렌딩하세요.
""".strip()
        if has_user_face
        else """
[기본 인물 요구사항]
1. 첫 번째 입력 이미지는 기본 전신 인물(아바타) 사진입니다.
2. 기본 인물의 고유한 얼굴, 헤어스타일, 체형 비율, 포즈, 표정, 시선, 촬영 구도 및 배경을 그대로 유지하세요.
""".strip()
    )

    return f"""
{face_prompt_section}

[의류 참조 이미지 매핑]
{clothing_instructions}

[가상 피팅 요구사항]
1. 각 참조 이미지로 전달된 의류 상품을 인물에게 자연스럽게 입히세요.
2. 제공되지 않은 카테고리의 새로운 의류나 아이템을 임의로 추가하거나 생성하지 마세요.
3. 각 상품의 고유한 색상, 패턴, 소재 질감, 실루엣, 디테일 디자인을 충실히 반영하세요.
4. 상의와 아우터가 모두 전달된 경우 아우터를 상의 위에 자연스럽게 겉옷으로 걸치세요.
5. 신발은 발에 착용하고, 모자는 머리에 맞추어 씌우세요.
6. 인물의 포즈와 체형에 맞추어 주름, 원단 핏, 그림자, 조명이 현실적이고 자연스럽게 어우러지도록 합성하세요.
7. 여러 장의 사진을 이어붙인 콜라주가 아닌, 하나의 완성된 자연스러운 피팅 전신 사진으로 출력하세요.
""".strip()


def resolve_avatar_path(custom_path: str | Path | None = None) -> Path:
    """기본 전신 아바타 이미지의 경로를 찾습니다."""
    setting = custom_path or os.getenv("AVATAR_IMAGE_PATH")
    if setting:
        candidate = Path(setting)
        if candidate.is_absolute():
            return candidate
        for base in (APP_DIR, PROJECT_ROOT):
            resolved = base / candidate
            if resolved.is_file():
                return resolved
        return PROJECT_ROOT / candidate

    app_asset = APP_DIR / "assets" / "avatar.png"
    if app_asset.is_file():
        return app_asset
    return PROJECT_ROOT / "assets" / "avatar.png"


def load_avatar_png(custom_path: str | Path | None = None) -> bytes:
    """기본 아바타 이미지를 불러와 PNG 바이트로 변환합니다."""
    avatar_path = resolve_avatar_path(custom_path)
    if not avatar_path.is_file():
        raise VtonConfigurationError(f"기본 아바타 이미지를 찾을 수 없습니다: {avatar_path}")

    try:
        return to_png_bytes(avatar_path.read_bytes())
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise VtonConfigurationError("설정된 아바타 이미지 파일이 유효한 이미지가 아닙니다.") from exc


def resolve_sample_clothing_path(category: str) -> Path:
    """지원되는 카테고리의 기본 샘플 의류 이미지 경로를 반환합니다."""
    category_name = category.strip()
    if category_name not in SUPPORTED_CATEGORIES:
        raise VtonValidationError(
            f"지원하지 않는 카테고리입니다: '{category}'. 허용: {list(SUPPORTED_CATEGORIES)}"
        )
    return APP_DIR / "data" / f"{category_name}.png"


def load_sample_clothing_png(category: str) -> bytes:
    """카테고리별 샘플 의류 이미지를 읽어 PNG 바이트로 반환합니다."""
    sample_path = resolve_sample_clothing_path(category)
    if not sample_path.is_file():
        raise VtonConfigurationError(f"샘플 의류 이미지를 찾을 수 없습니다: {sample_path}")
    try:
        return to_png_bytes(sample_path.read_bytes())
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise VtonConfigurationError(f"샘플 의류 이미지 파일이 유효하지 않습니다: {sample_path}") from exc


def generate_tryon_image(
    categories: str | list[str],
    clothing_images: list[bytes],
    *,
    avatar_bytes: bytes | None = None,
    avatar_path: str | Path | None = None,
    user_face_bytes: bytes | None = None,
    api_key: str | None = None,
    model: str | None = None,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
    openai_client: Any = None,
) -> TryonResult:
    """
    기본 아바타와 의류 이미지들(및 선택적으로 사용자 얼굴 사진)을 OpenAI Image Edit API에 전달하여 가상 피팅 결과 이미지를 생성합니다.
    """
    parsed_categories = parse_categories(categories)

    if len(clothing_images) != len(parsed_categories):
        raise VtonValidationError(
            f"입력된 의류 이미지 개수({len(clothing_images)}개)와 카테고리 개수({len(parsed_categories)}개)가 일치하지 않습니다."
        )

    if avatar_bytes is not None:
        try:
            avatar_png = to_png_bytes(avatar_bytes)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise VtonConfigurationError("전달된 아바타 이미지가 유효하지 않습니다.") from exc
    else:
        avatar_png = load_avatar_png(avatar_path)

    # 사용자 얼굴 이미지가 전달된 경우 PNG 검증
    user_face_png: bytes | None = None
    if user_face_bytes is not None:
        try:
            user_face_png = to_png_bytes(user_face_bytes)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise VtonValidationError("사용자 얼굴 이미지가 유효하지 않습니다.") from exc

    clothing_png_list: list[bytes] = []
    for index, raw_bytes in enumerate(clothing_images):
        if not raw_bytes:
            raise VtonValidationError(f"{index + 1}번째 상품 이미지가 비어 있습니다.")
        try:
            clothing_png = to_png_bytes(raw_bytes)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise VtonValidationError(
                f"{index + 1}번째 상품 이미지가 유효한 이미지 파일이 아닙니다."
            ) from exc
        clothing_png_list.append(clothing_png)

    resolved_api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
    if openai_client is None and not resolved_api_key:
        raise VtonConfigurationError("OPENAI_API_KEY 환경 변수가 설정되지 않았습니다.")

    resolved_model = model or os.getenv("OPENAI_IMAGE_MODEL", DEFAULT_MODEL)
    resolved_timeout = (
        float(timeout_seconds)
        if timeout_seconds is not None
        else float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))
    )
    resolved_retries = (
        int(max_retries)
        if max_retries is not None
        else int(os.getenv("OPENAI_MAX_RETRIES", "1"))
    )

    image_inputs: list[tuple[str, bytes, str]] = [
        ("avatar.png", avatar_png, "image/png"),
    ]
    if user_face_png is not None:
        image_inputs.append(("user_face.png", user_face_png, "image/png"))

    for index, clothing_png in enumerate(clothing_png_list):
        image_inputs.append(
            (f"clothing_{index + 1}.png", clothing_png, "image/png")
        )

    client = openai_client or OpenAI(
        api_key=resolved_api_key,
        timeout=resolved_timeout,
        max_retries=resolved_retries,
    )

    try:
        result = client.images.edit(
            model=resolved_model,
            image=image_inputs,
            prompt=build_prompt(parsed_categories, has_user_face=user_face_png is not None),
            n=1,
            size="1024x1536",
            quality="high",
            output_format="png",
        )
    except OpenAIError as exc:
        raise VtonUpstreamError(
            f"OpenAI 이미지 생성 요청이 실패했습니다 ({type(exc).__name__}): {exc}"
        ) from exc

    if not getattr(result, "data", None) or not getattr(result.data[0], "b64_json", None):
        raise VtonUpstreamError("OpenAI 이미지 API에서 생성된 이미지 데이터를 받지 못했습니다.")

    p_tokens = 0
    c_tokens = 0
    usage = getattr(result, "usage", None)
    if usage is not None:
        in_tok = getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", 0) or 0
        out_tok = getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", 0) or 0
        p_tokens = int(in_tok)
        c_tokens = int(out_tok)

    image_bytes = base64.b64decode(result.data[0].b64_json)
    return TryonResult(
        image_bytes=image_bytes,
        prompt_tokens=p_tokens,
        completion_tokens=c_tokens,
    )
