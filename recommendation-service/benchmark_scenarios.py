import os
import sys
import time
from typing import Any
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 서비스 모듈 import
from app.clients.user_client import UserServiceClient
from app.services.coordinator import FashionPipelineCoordinator
import app.services.harmonizer as harmonizer_module

load_dotenv()

TEST_QUERY = "결혼식 하객룩으로 입을 깔끔한 셋업이랑 셔츠, 로퍼 추천해줘. 예산은 30만원 이하로 부탁해."
USER_ID = 1

SCENARIOS = [
    {
        "name": "Baseline",
        "description": "기본 모델 조합 (gpt-6.1-sol / gpt-6-astra / gpt-6-luna, 후보 9개)",
        "parser_model": "gpt-6.1-sol",
        "harmonizer_model": "gpt-6-astra",
        "responder_model": "gpt-6-luna",
        "max_candidates": 9,
    },
    {
        "name": "Test #1",
        "description": "텍스트 모델 sol 통일 (gpt-6-sol / gpt-6-astra / gpt-6-sol, 후보 9개)",
        "parser_model": "gpt-6-sol",
        "harmonizer_model": "gpt-6-astra",
        "responder_model": "gpt-6-sol",
        "max_candidates": 9,
    },
    {
        "name": "Test #2",
        "description": "파서 6.1-sol + 응답 6-sol (gpt-6.1-sol / gpt-6-astra / gpt-6-sol, 후보 9개)",
        "parser_model": "gpt-6.1-sol",
        "harmonizer_model": "gpt-6-astra",
        "responder_model": "gpt-6-sol",
        "max_candidates": 9,
    },
    {
        "name": "Test #3",
        "description": "파서 6-sol + 응답 6-luna (gpt-6-sol / gpt-6-astra / gpt-6-luna, 후보 9개)",
        "parser_model": "gpt-6-sol",
        "harmonizer_model": "gpt-6-astra",
        "responder_model": "gpt-6-luna",
        "max_candidates": 9,
    },
    {
        "name": "Test #4",
        "description": "Harmonizer Vision 검수 후보 축소 (후보 9개 -> 3개, Baseline 모델)",
        "parser_model": "gpt-6.1-sol",
        "harmonizer_model": "gpt-6-astra",
        "responder_model": "gpt-6-luna",
        "max_candidates": 3,
    },
]


def run_benchmark():
    """모델 조합 및 후보 수 시나리오별 파이프라인 응답 시간과 성능을 측정해 비교 리포트를 출력한다."""
    print("=" * 80)
    print("🚀 [Fitzza AI 추천 엔진] GPT-6 모델 조합 및 최적화 시나리오 벤치마크")
    print(f"📌 테스트 질의: \"{TEST_QUERY}\"")
    print(f"👤 테스트 유저: user_id = {USER_ID}")
    print("=" * 80)

    # 1. User-Service HTTP 통신으로 신체 정보 로드
    print("\n[Step 1] User-Service (http://localhost:8081/users/1/body) 신체 데이터 연동...")
    user_client = UserServiceClient()
    user_body = user_client.get_user_body(USER_ID) or None
    if user_body:
        print(f"✅ 유저 신체 정보 로드 성공: 키 {user_body.get('height')}cm, 몸무게 {user_body.get('weight')}kg, 발 {user_body.get('shoeSize')}mm")
    else:
        print("⚠️ User-Service 신체 정보를 가져오지 못했습니다. 신체 정보 없이 진행합니다.")

    # 2. 파이프라인 코디네이터 초기화
    print("\n[Step 2] FashionPipelineCoordinator 초기화 (CLIP 모델 / Qdrant 준비)...")
    os.environ.setdefault("ENABLE_DEV_MOCK_SIZE_DATA", "true")
    coordinator = FashionPipelineCoordinator()
    print("✅ 준비 완료!")

    # 2-1. 콜드 스타트(워밍업) 왜곡 방지를 위한 사전 폐기용 워밍업 1회 실행
    if SCENARIOS:
        warmup_sc = SCENARIOS[0]
        print("\n[Warmup] 측정 왜곡 방지를 위해 사전 워밍업(폐기용 1회)을 실행합니다...")
        coordinator.parser.model_name = warmup_sc["parser_model"]
        coordinator.harmonizer.model_name = warmup_sc["harmonizer_model"]
        harmonizer_module.MAX_CANDIDATES_TO_REVIEW = warmup_sc["max_candidates"]
        coordinator.responder.model_name = warmup_sc["responder_model"]
        try:
            coordinator.run(
                user_query=TEST_QUERY,
                user_id=str(USER_ID),
                user_body=user_body,
            )
            print("✅ 워밍업 완료 (측정 결과에서 제외)")
        except Exception as warmup_err:
            print(f"⚠️ 워밍업 실행 실패 (무시하고 본 측정 진행): {warmup_err}")

    results = []

    # 3. 각 시나리오별 실행
    for idx, sc in enumerate(SCENARIOS, 1):
        print("\n" + "#" * 80)
        print(f"🧪 [{idx}/{len(SCENARIOS)}] 시나리오 실행 (순번 #{idx}): {sc['name']} - {sc['description']}")
        print(f"   - QueryParser 모델     : {sc['parser_model']}")
        print(f"   - OutfitHarmonizer 모델: {sc['harmonizer_model']} (검수 후보 {sc['max_candidates']}개)")
        print(f"   - ResponseGenerator 모델: {sc['responder_model']}")
        print("#" * 80)

        # 모델 및 설정 주입
        coordinator.parser.model_name = sc["parser_model"]
        coordinator.harmonizer.model_name = sc["harmonizer_model"]
        harmonizer_module.MAX_CANDIDATES_TO_REVIEW = sc["max_candidates"]
        coordinator.responder.model_name = sc["responder_model"]

        # 실행
        try:
            start_wall = time.perf_counter()
            res = coordinator.run(
                user_query=TEST_QUERY,
                user_id=str(USER_ID),
                user_body=user_body,
            )
            wall_duration = time.perf_counter() - start_wall

            lats = res.get("latencies", {})
            qp_l = lats.get("query_parser", {})
            se_l = lats.get("search_engine", {})
            sr_l = lats.get("size_resolver", {})
            hm_l = lats.get("harmonizer", {})
            rg_l = lats.get("response_generator", {})

            internal_total = (
                qp_l.get("prompt_build", 0.0)
                + se_l.get("total", 0.0)
                + sr_l.get("total", 0.0)
                + hm_l.get("cartesian_and_vector", 0.0)
                + hm_l.get("s3_presigned_url", 0.0)
                + rg_l.get("prompt_build", 0.0)
            )
            llm_total = (
                qp_l.get("llm_api", 0.0)
                + hm_l.get("vision_llm_api", 0.0)
                + rg_l.get("llm_api", 0.0)
            )
            pipe_total = lats.get("total_pipeline", wall_duration)

            outfits_cnt = len(res.get("outfits", []))
            first_outfit = res.get("outfits", [{}])[0] if outfits_cnt > 0 else {}

            sc_summary = {
                "run_order": idx,
                "name": sc["name"],
                "parser_model": sc["parser_model"],
                "harmonizer_model": sc["harmonizer_model"],
                "max_candidates": sc["max_candidates"],
                "responder_model": sc["responder_model"],
                "qp_llm": qp_l.get("llm_api", 0.0),
                "se_total": se_l.get("total", 0.0),
                "sr_total": sr_l.get("total", 0.0),
                "hm_combo": hm_l.get("cartesian_and_vector", 0.0),
                "hm_llm": hm_l.get("vision_llm_api", 0.0),
                "rg_llm": rg_l.get("llm_api", 0.0),
                "internal_total": internal_total,
                "llm_total": llm_total,
                "pipe_total": pipe_total,
                "wall_duration": wall_duration,
                "prompt_tokens": res.get("prompt_tokens", 0),
                "completion_tokens": res.get("completion_tokens", 0),
                "outfits_count": outfits_cnt,
                "top_score": first_outfit.get("final_score", 0.0),
                "top_harmony": first_outfit.get("harmony_score", 0.0),
                "comment": res.get("comment", "")[:100] + "...",
            }
            results.append(sc_summary)

            print(f"   ⏱️ 결과 (실행 순번 #{idx}): 총 {pipe_total:.2f}초 (Wall: {wall_duration:.2f}초 / LLM API: {llm_total:.2f}초 / 내부 연산: {internal_total:.2f}초)")
            print(f"      - QueryParser API    : {qp_l.get('llm_api', 0.0):.2f}초")
            print(f"      - Search Engine      : {se_l.get('total', 0.0):.2f}초")
            print(f"      - Harmonizer Vision  : {hm_l.get('vision_llm_api', 0.0):.2f}초")
            print(f"      - ResponseGenerator  : {rg_l.get('llm_api', 0.0):.2f}초")
            print(f"   🪙 토큰: Prompt {res.get('prompt_tokens', 0)} / Completion {res.get('completion_tokens', 0)}")
            print(f"   ✨ 추천 코디: {outfits_cnt}세트 도출 (1위 코디 점수: {first_outfit.get('final_score')}점)")

        except Exception as err:
            print(f"❌ [에러] 시나리오 {sc['name']} 실패: {err}")
            import traceback
            traceback.print_exc()

    # 4. 전체 결과 비교 테이블 출력
    print("\n\n" + "=" * 118)
    print(" 📊 [GPT-6 시나리오별 응답 시간 및 성능 벤치마크 최종 비교 리포트]")
    print("=" * 118)
    print(f"{'순번':<4} | {'시나리오':<10} | {'QueryParser':<12} | {'Harmonizer(후보)':<17} | {'ResponseGen':<12} | {'파서API':<7} | {'VisionAPI':<9} | {'응답API':<7} | {'내부연산':<7} | {'총응답시간':<9}")
    print("-" * 118)
    for r in results:
        harm_desc = f"{r['harmonizer_model']}({r['max_candidates']}개)"
        print(
            f"#{r['run_order']:<3} | "
            f"{r['name']:<10} | "
            f"{r['parser_model']:<12} | "
            f"{harm_desc:<17} | "
            f"{r['responder_model']:<12} | "
            f"{r['qp_llm']:6.2f}초 | "
            f"{r['hm_llm']:8.2f}초 | "
            f"{r['rg_llm']:6.2f}초 | "
            f"{r['internal_total']:6.2f}초 | "
            f"{r['pipe_total']:7.2f}초"
        )
    print("=" * 118)

    # 5. 베이스라인 대비 단축율 계산
    baseline = next((r for r in results if r["name"] == "Baseline"), None)
    if baseline and len(results) > 1:
        base_time = baseline["pipe_total"]
        print("\n📈 [Baseline 대비 응답 속도 개선율 (단축 효과)]")
        for r in results:
            diff = r["pipe_total"] - base_time
            ratio = ((base_time - r["pipe_total"]) / base_time * 100.0) if base_time > 0 else 0.0
            sign = "단축 ⬇️" if diff <= 0 else "증가 ⬆️"
            print(f"  - [#{r['run_order']}] {r['name']:<10}: {r['pipe_total']:6.2f}초 ({diff:+6.2f}초, {abs(ratio):5.1f}% {sign})")
        print("=" * 118)


if __name__ == "__main__":
    run_benchmark()
