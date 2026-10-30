import os
import sys
import time
from typing import Any
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import app.services.harmonizer as harmonizer_module
from app.services.coordinator import FashionPipelineCoordinator
from app.clients.user_client import UserServiceClient

load_dotenv()

DEFAULT_TEST_QUERY = "결혼식 하객룩으로 입을 깔끔한 셋업이랑 셔츠, 로퍼 추천해줘. 예산은 30만원 이하로 부탁해."
DEFAULT_USER_ID = 1


def print_latency_report(latencies: dict[str, Any], result: dict[str, Any]):
    print("\n" + "=" * 80)
    print(" ⏱️  [Fitzza AI 파이프라인 정밀 지연 시간(Latency) 프로파일링 리포트] ")
    print("=" * 80)

    # 1. Query Parser
    qp = latencies.get("query_parser", {})
    qp_build = qp.get("prompt_build", 0.0)
    qp_llm = qp.get("llm_api", 0.0)
    qp_total = qp.get("total", 0.0)

    # 2. Search Engine
    se = latencies.get("search_engine", {})
    se_clip = se.get("clip_embedding", 0.0)
    se_qdrant = se.get("qdrant_search", 0.0)
    se_scoring = se.get("scoring_and_sort", 0.0)
    se_total = se.get("total", 0.0)

    # 3. Size Resolver
    sr = latencies.get("size_resolver", {})
    sr_resolve = sr.get("baseline_resolve", 0.0)
    sr_calc = sr.get("size_calc", 0.0)
    sr_total = sr.get("total", 0.0)

    # 4. Harmonizer
    hm = latencies.get("harmonizer", {})
    hm_combo = hm.get("cartesian_and_vector", 0.0)
    hm_s3 = hm.get("s3_presigned_url", 0.0)
    hm_llm = hm.get("vision_llm_api", 0.0)
    hm_total = hm.get("total", 0.0)

    # 5. Response Generator
    rg = latencies.get("response_generator", {})
    rg_build = rg.get("prompt_build", 0.0)
    rg_llm = rg.get("llm_api", 0.0)
    rg_total = rg.get("total", 0.0)

    total_pipeline = latencies.get("total_pipeline", 0.0)
    total_internal = qp_build + se_total + sr_total + hm_combo + hm_s3 + rg_build
    total_llm = qp_llm + hm_llm + rg_llm

    print(f" 1️⃣ [QueryParser (query_parser.py)]")
    print(f"    ├─ 프롬프트 조립 전처리       : {qp_build:7.4f}초")
    print(f"    ├─ LLM 의도 파싱 API 호출    : {qp_llm:7.4f}초")
    print(f"    └─ 소계                      : {qp_total:7.4f}초")

    print(f"\n 2️⃣ [FashionSearchEngine (search_engine.py)]")
    print(f"    ├─ Fashion-CLIP 텍스트 임베딩 : {se_clip:7.4f}초")
    print(f"    ├─ Qdrant 벡터 DB 검색       : {se_qdrant:7.4f}초")
    print(f"    ├─ 복합 가중치 스코어링 & 정렬: {se_scoring:7.4f}초")
    print(f"    └─ 소계                      : {se_total:7.4f}초")

    print(f"\n 3️⃣ [SizeProfileResolver (size_resolver.py)]")
    print(f"    ├─ 신체/선호 베이스라인 결정  : {sr_resolve:7.4f}초")
    print(f"    ├─ 상품 실측 대조 및 적합도 계산: {sr_calc:7.4f}초")
    print(f"    └─ 소계                      : {sr_total:7.4f}초")

    if result.get("type") == "coordination":
        print(f"\n 4️⃣ [OutfitHarmonizer (harmonizer.py)]")
        print(f"    ├─ 카테시안 조합 & 코사인 유사도: {hm_combo:7.4f}초")
        print(f"    ├─ S3 Presigned URL 서명 발급: {hm_s3:7.4f}초")
        print(f"    ├─ Vision LLM 심사 API 호출   : {hm_llm:7.4f}초")
        print(f"    └─ 소계                      : {hm_total:7.4f}초")

    print(f"\n 5️⃣ [ResponseGenerator (response_generator.py)]")
    print(f"    ├─ 응답 프롬프트 조립        : {rg_build:7.4f}초")
    print(f"    ├─ LLM 코멘트 생성 API 호출   : {rg_llm:7.4f}초")
    print(f"    └─ 소계                      : {rg_total:7.4f}초")

    print("-" * 80)
    llm_ratio = (total_llm / total_pipeline * 100.0) if total_pipeline > 0 else 0.0
    internal_ratio = (total_internal / total_pipeline * 100.0) if total_pipeline > 0 else 0.0
    print(f" 📊 [지연 시간 요약 및 점유율]")
    print(f"    - 순수 내부 연산 시간 (Internal) : {total_internal:7.4f}초 ({internal_ratio:5.1f}%)")
    print(f"    - 외부 OpenAI API 시간 (LLM/Vision): {total_llm:7.4f}초 ({llm_ratio:5.1f}%)")
    print(f"    ----------------------------------------------------------------------------")
    print(f"    🚀 전체 파이프라인 E2E 총 지연 시간 : {total_pipeline:7.4f}초")
    print(f"    🪙 총 소모 토큰 : Prompt {result.get('prompt_tokens', 0)} / Completion {result.get('completion_tokens', 0)}")
    print("=" * 80)


def main():
    print("=" * 80)
    print("✨ Fitzza AI 패션 추천 파이프라인 정밀 프로파일링 & E2E 테스트")
    print("=" * 80)

    # 1. 환경변수 검증
    if not os.getenv("OPENAI_API_KEY"):
        print("🚨 [에러] OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인해주세요.")
        return

    # 2. User-Service 클라이언트 및 신체 정보 연동 확인
    print("\n[1단계] User-Service (Spring Boot, 포트 8081) 연동 확인 중...")
    user_client = UserServiceClient()
    user_body = None
    try:
        user_body = user_client.get_user_body(DEFAULT_USER_ID)
        print(f"✅ User-Service 통신 성공! [user_id={DEFAULT_USER_ID}] 신체 프로필 로드 완료:")
        print(f"   - 키: {user_body.get('height')}cm, 몸무게: {user_body.get('weight')}kg, 발: {user_body.get('shoeSize')}mm")
        print(f"   - 선호 핏: {user_body.get('preferredFit')}, 선호 스타일: {user_body.get('preferredStyles')}")
    except Exception as e:
        print(f"⚠️ User-Service 연동 실패 (기본 Mock 모드로 대체 진행): {e}")

    # 3. 코디네이터 초기화
    print("\n[2단계] 파이프라인 코디네이터 로드 중 (CLIP 모델 & Qdrant 연결)...")
    try:
        coordinator = FashionPipelineCoordinator()
        print("✅ 코디네이터 준비 완료!")
        print(f"   - QueryParser 모델     : {coordinator.parser.model_name}")
        print(f"   - OutfitHarmonizer 모델: {coordinator.harmonizer.model_name} (검수 후보: {harmonizer_module.MAX_CANDIDATES_TO_REVIEW}개 유지)")
        print(f"   - ResponseGenerator 모델: {coordinator.responder.model_name}")
    except Exception as e:
        print(f"🚨 [에러] 코디네이터 초기화 실패: {e}")
        import traceback
        traceback.print_exc()
        return

    print("\n💡 [사용 안내]")
    print(f"   - 그냥 [Enter] 키를 누르면 기본 테스트 질의가 자동 실행됩니다:")
    print(f"     \"{DEFAULT_TEST_QUERY}\"")
    print("   - 종료하려면 'exit' 또는 'quit'을 입력하세요.\n")

    # 4. 질의 실행 루프
    once_mode = "--once" in sys.argv
    idx = 1
    while True:
        try:
            if once_mode:
                user_input = ""
            else:
                prompt_text = f"[{idx}] 질의 입력 (Enter = 기본 질의) ➔ "
                user_input = input(prompt_text).strip()

            if user_input.lower() in ["exit", "quit"]:
                print("\n👋 테스트 프로그램을 종료합니다.")
                break

            query = user_input if user_input else DEFAULT_TEST_QUERY

            print("\n" + "#" * 80)
            print(f"📌 [테스트 케이스 #{idx}] 질의: \"{query}\"")
            print("#" * 80)

            # 파이프라인 구동
            result = coordinator.run(
                user_query=query,
                user_id=str(DEFAULT_USER_ID),
                user_body=user_body,
            )

            # 세부 성능 프로파일링 리포트 출력
            latencies = result.get("latencies", {})
            print_latency_report(latencies, result)

            # 결과 요약 출력
            print("\n💬 [AI 추천 코멘트 (Response Generator)]")
            print("-" * 60)
            print(result.get("comment", "(응답 없음)"))
            print("-" * 60)

            if result.get("type") == "single":
                results = result.get("results", [])
                print(f"\n📦 단품 검색 결과 상위 {len(results)}개:")
                for r_idx, item in enumerate(results, 1):
                    subcat_display = f"[{item.get('subcategory')}]" if item.get('subcategory') else ""
                    size_rec = item.get("size_recommendation")
                    size_str = f"추천 사이즈: {size_rec.get('size_label')} (적합도: {size_rec.get('predicted_fit_score')}점)" if size_rec else "사이즈 정보 없음"
                    source_type = item.get("fit_source_type", "none")

                    color_display = item.get("color_raw") or item.get("color_normalized") or "색상 정보 없음"
                    print(
                        f"  {r_idx}. [{item.get('brand_name')}] "
                        f"{item.get('product_name')} (색상: {color_display}) {subcat_display} - "
                        f"{item.get('price', 0):,}원"
                    )
                    print(
                        f"     정규화 색상: {item.get('color_normalized')} | "
                        f"벡터 유사도: {item.get('similarity_score')}"
                    )
                    print(f"     📏 [사이즈 추천] {size_str} [소스: {source_type}]")
                    print(f"     🖼️ 이미지 URL : {item.get('image_url')}")
                    print(f"     🔗 상품 링크  : {item.get('product_url')}")

            elif result.get("type") == "coordination":
                outfits = result.get("outfits", [])
                print(f"\n✨ 최종 확정된 코디 세트 ({len(outfits)}개):")
                for o_idx, outfit in enumerate(outfits, 1):
                    print(
                        f"\n  [코디 세트 {o_idx}] "
                        f"(총가격: {outfit.get('total_price', 0):,}원 | "
                        f"최종 정렬 점수: {outfit.get('final_score')}점)"
                    )
                    print(
                        f"    - Vision 조화도 점수: {outfit.get('harmony_score')}점 / "
                        f"예산 초과 감점: -{outfit.get('budget_penalty')}점"
                    )
                    print(f"    - 에디터 심사평: {outfit.get('verdict')}")
                    print("    - 구성 상품 세부 내역:")
                    for item in outfit.get("items", []):
                        size_rec = item.get("size_recommendation")
                        source_type = item.get("fit_source_type", "none")
                        size_str = f"추천 사이즈: {size_rec.get('size_label')} (적합도: {size_rec.get('predicted_fit_score')}점, 근거: {source_type})" if size_rec else "사이즈 정보 없음"
                        color_display = item.get("color_raw") or item.get("color_normalized") or "색상 정보 없음"
                        print(
                            f"      * [{item.get('category')} / 서브: {item.get('subcategory')}] "
                            f"{item.get('brand_name')} {item.get('product_name')} "
                            f"(색상: {color_display} | {item.get('price', 0):,}원) | {size_str}"
                        )
                        print(f"        🖼️ 이미지 URL : {item.get('image_url')}")
                        print(f"        🔗 상품 링크  : {item.get('product_url')}")

            print("\n" + "=" * 80 + "\n")
            if once_mode:
                break
            idx += 1

        except KeyboardInterrupt:
            print("\n\n👋 사용자에 의해 강제 종료되었습니다.")
            break
        except Exception as error:
            print(f"❌ [테스트 실패] 질의 처리 중 오류 발생: {type(error).__name__}: {error}\n")
            import traceback
            traceback.print_exc()
            print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    main()