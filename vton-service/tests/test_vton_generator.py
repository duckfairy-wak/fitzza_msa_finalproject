"""가상 피팅(VTON) 코어 제너레이터 단위 테스트."""

import base64
import io
from types import SimpleNamespace

import pytest
from openai import OpenAIError
from PIL import Image

from app.services.vton_generator import (
    SUPPORTED_CATEGORIES,
    TryonResult,
    VtonConfigurationError,
    VtonUpstreamError,
    VtonValidationError,
    build_prompt,
    generate_tryon_image,
    load_avatar_png,
    load_sample_clothing_png,
    parse_categories,
    to_png_bytes,
)


def make_rgba_png(color: tuple[int, int, int, int]) -> bytes:
    image = Image.new("RGBA", (8, 8), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("raw_input", "expected"),
    [
        ('["상의", "하의"]', ["상의", "하의"]),
        ("상의,아우터,신발", ["상의", "아우터", "신발"]),
        (["상의", "모자"], ["상의", "모자"]),
        (["상의", "하의", "아우터", "신발", "모자"], ["상의", "하의", "아우터", "신발", "모자"]),
    ],
)
def test_parse_categories_accepts_supported_korean_categories(
    raw_input: str | list[str], expected: list[str]
) -> None:
    assert parse_categories(raw_input) == expected


@pytest.mark.parametrize(
    "invalid_input",
    [
        "",
        "   ",
        "[]",
        [],
        "[invalid json",
        ["상의", "상의"],
        ["상의", "하의", "아우터", "신발", "모자", "가방"],
        ["unknown-category"],
        ["top"],
        [123],  # type: ignore[list-item]
    ],
)
def test_parse_categories_rejects_invalid_inputs(invalid_input: object) -> None:
    with pytest.raises(VtonValidationError):
        parse_categories(invalid_input)  # type: ignore[arg-type]


def test_to_png_bytes_composites_transparency_onto_white_background() -> None:
    transparent_png = make_rgba_png((0, 0, 0, 0))

    converted = to_png_bytes(transparent_png)

    with Image.open(io.BytesIO(converted)) as image:
        assert image.format == "PNG"
        assert image.mode == "RGB"
        assert image.getpixel((0, 0)) == (255, 255, 255)


def test_to_png_bytes_rejects_invalid_bytes() -> None:
    with pytest.raises(Exception):
        to_png_bytes(b"not-an-image")


def test_build_prompt_numbers_reference_images_starting_at_two() -> None:
    prompt = build_prompt(["상의", "아우터", "신발"])

    assert "- 참조 이미지 2: 상의" in prompt
    assert "- 참조 이미지 3: 아우터" in prompt
    assert "- 참조 이미지 4: 신발" in prompt


def test_bundled_avatar_and_sample_clothing_assets_load_as_valid_pngs() -> None:
    avatar_png = load_avatar_png()
    assert avatar_png.startswith(b"\x89PNG\r\n\x1a\n")

    for category in SUPPORTED_CATEGORIES:
        sample_png = load_sample_clothing_png(category)
        assert sample_png.startswith(b"\x89PNG\r\n\x1a\n")


def test_generate_tryon_image_calls_openai_images_edit_and_decodes_png() -> None:
    expected_output = make_rgba_png((10, 20, 30, 255))
    captured_kwargs: dict[str, object] = {}

    class FakeImagesClient:
        def edit(self, **kwargs: object) -> object:
            captured_kwargs.update(kwargs)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(
                        b64_json=base64.b64encode(expected_output).decode("ascii")
                    )
                ],
                usage=SimpleNamespace(input_tokens=450, output_tokens=900),
            )

    fake_client = SimpleNamespace(images=FakeImagesClient())
    top_png = load_sample_clothing_png("상의")
    shoes_png = load_sample_clothing_png("신발")

    result = generate_tryon_image(
        ["상의", "신발"],
        [top_png, shoes_png],
        openai_client=fake_client,
        model="gpt-image-2.5-sunburst",
    )

    assert isinstance(result, TryonResult)
    assert result.image_bytes == expected_output
    assert result.prompt_tokens == 450
    assert result.completion_tokens == 900
    assert captured_kwargs["model"] == "gpt-image-2.5-sunburst"
    assert captured_kwargs["size"] == "1024x1536"
    assert captured_kwargs["quality"] == "high"
    assert captured_kwargs["output_format"] == "png"
    image_inputs = captured_kwargs["image"]
    assert isinstance(image_inputs, list)
    assert len(image_inputs) == 3
    assert image_inputs[0][0] == "avatar.png"
    assert image_inputs[1][0] == "clothing_1.png"
    assert image_inputs[2][0] == "clothing_2.png"


def test_generate_tryon_image_validates_counts_and_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    top_png = load_sample_clothing_png("상의")

    with pytest.raises(VtonValidationError, match="일치하지 않습니다"):
        generate_tryon_image(["상의", "신발"], [top_png], api_key="test-key")

    with pytest.raises(VtonConfigurationError, match="OPENAI_API_KEY"):
        generate_tryon_image(["상의"], [top_png])


def test_generate_tryon_image_wraps_openai_errors() -> None:
    class FailingImagesClient:
        def edit(self, **_: object) -> object:
            raise OpenAIError("upstream failure")

    fake_client = SimpleNamespace(images=FailingImagesClient())
    top_png = load_sample_clothing_png("상의")

    with pytest.raises(VtonUpstreamError, match="OpenAI 이미지 생성 요청이 실패했습니다"):
        generate_tryon_image(["상의"], [top_png], openai_client=fake_client)
