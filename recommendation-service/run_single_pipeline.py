import sys
import os
import time
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

from app.clients.user_client import UserServiceClient
from app.services.coordinator import FashionPipelineCoordinator
import app.services.harmonizer as harmonizer_module
from run_pipeline_test import print_latency_report

DEFAULT_TEST_QUERY = (
    "주말 데이트용 미니멀 캐주얼룩 추천해줘. 가디건이나 자켓, 티셔츠, 와이드 팬츠, 스니커즈 조합으로 25만원 이하로 부탁해."
)
USER_ID = 1


def main():
    test_query = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEST_QUERY
    print("=" * 80)
    print("✨ [실시간 파이프라인 정밀 테스트 - 추출 내용 상세 출력]")
    print("=" * 80)

    # 1. User-Service 신체 데이터
    user_client = UserServiceClient()
    user_body = user_client.get_user_body(USER_ID) or None
    if user_body:
        print(f"✅ User-Service 신체 데이터 로드 성공: 키 {user_body.get('height')}cm, 몸무게 {user_body.get('weight')}kg, 발 {user_body.get('shoeSize')}mm")
    else:
        print("⚠️ User-Service 신체 정보를 가져오지 못했습니다. 신체 정보 없이 진행합니다.")

    # 2. 코디네이터 초기화
    os.environ.setdefault("ENABLE_DEV_MOCK_SIZE_DATA", "true")
    coordinator = FashionPipelineCoordinator()
    print("✅ 코디네이터 초기화 완료!")
    print(f"   - QueryParser 모델      : {coordinator.parser.model_name}")
    print(f"   - OutfitHarmonizer 모델 : {coordinator.harmonizer.model_name} (검수 후보: {harmonizer_module.MAX_CANDIDATES_TO_REVIEW}개, 중복 제한: <= {harmonizer_module.MAX_OVERLAP_ITEMS}개)")
    print(f"   - ResponseGenerator 모델: {coordinator.responder.model_name}")

    print("\n" + "#" * 80)
    print(f"📌 [테스트 질의]: \"{test_query}\"")
    print("#" * 80)

    # 3. 파이프라인 구동
    result = coordinator.run(
        user_query=test_query,
        user_id=str(USER_ID),
        user_body=user_body,
    )

    # 4. [추출 내용 1] QueryParser 의도 파싱 결과
    intent = result.get("intent", {})
    if hasattr(intent, "model_dump"):
        intent = intent.model_dump()

    print("\n" + "=" * 80)
    print("📋 [1단계: QueryParser 추출 내용]")
    print("=" * 80)
    print(f"  • 검색 유형 (search_type)   : {intent.get('search_type')}")
    print(f"  • TPO 요약 (tpo_summary)    : {intent.get('tpo_summary')}")
    print(f"  • 총 예산 (total_budget)     : {intent.get('total_budget'):,}원" if intent.get('total_budget') else "  • 총 예산 (total_budget)     : 제한 없음")
    print(f"  • 추천 계절 (season_pref)   : {intent.get('season_preferences')}")
    print(f"  • 추출된 슬롯 개수          : {len(intent.get('slots', []))}개")

    print("\n  [슬롯별 세부 추출 속성]")
    for idx, slot in enumerate(intent.get("slots", []), 1):
        if hasattr(slot, "model_dump"):
            slot = slot.model_dump()
        print(f"    [{idx}] 카테고리: {slot.get('category')} | 서브: {slot.get('subcategory')}")
        print(f"        - CLIP 영문 쿼리   : \"{slot.get('clip_query_en')}\"")
        budget_str = f"{slot.get('slot_budget'):,}원" if slot.get("slot_budget") else "없음"
        max_p_str = f"{slot.get('max_price'):,}원" if slot.get("max_price") else "없음"
        print(f"        - 슬롯 예산/최대가 : {budget_str} / {max_p_str}")
        print(f"        - 색상: {slot.get('color')} | 핏: {slot.get('fit_type')} | 두께감: {slot.get('thickness_type')} | 신축성: {slot.get('stretch_type')} | 촉감: {slot.get('touch_type')}")

    # 5. [추출 내용 2] 추천 코디 세트 상세 (SizeProfileResolver & OutfitHarmonizer)
    outfits = result.get("outfits", [])
    print("\n" + "=" * 80)
    print(f"✨ [2단계: OutfitHarmonizer 최종 선발 코디 세트 ({len(outfits)}개)]")
    print("=" * 80)

    pids_per_outfit = []
    for idx, outfit in enumerate(outfits, 1):
        pids = [str(item.get("product_id") or item.get("productId")) for item in outfit.get("items", [])]
        pids_per_outfit.append(set(pids))
        print(f"\n  ▶ [코디 세트 {idx}] 총가격: {outfit.get('total_price', 0):,}원 | 최종 점수: {outfit.get('final_score')}점 (Vision: {outfit.get('harmony_score')}점, 감점: -{outfit.get('budget_penalty')}점)")
        print(f"     * 심사평: {outfit.get('verdict')}")
        print(f"     * 스타일링 팁: {outfit.get('styling_tip')}")
        print("     * 착장 아이템 목록:")
        for item in outfit.get("items", []):
            pid = item.get("product_id") or item.get("productId")
            musinsa_url = f"https://www.musinsa.com/products/{pid}" if pid else "N/A"
            size_rec = item.get("size_recommendation", "N/A")
            fit_src = item.get("fit_source_type", "N/A")
            print(f"       - [{item.get('category')} / {item.get('subcategory')}] {item.get('brand_name')} {item.get('product_name')}")
            print(f"         가격: {item.get('price', 0):,}원 | 추천사이즈: {size_rec} (근거: {fit_src})")
            print(f"         무신사 링크: {musinsa_url}")

    # 중복 검증
    if len(pids_per_outfit) >= 2:
        overlap_pids = pids_per_outfit[0] & pids_per_outfit[1]
        print("\n" + "-" * 80)
        print(f"🔍 [다양성 필터 검증] 코디 1과 코디 2 사이의 중복 상품 수: {len(overlap_pids)}개 (중복 상품 ID: {list(overlap_pids) if overlap_pids else '없음 (0개 완전 분리)'})")
        print(f"   -> 허용 상한 (MAX_OVERLAP_ITEMS <= {harmonizer_module.MAX_OVERLAP_ITEMS}): {'✅ 만족' if len(overlap_pids) <= harmonizer_module.MAX_OVERLAP_ITEMS else '❌ 위반'}")
        print("-" * 80)

    # 6. 응답 코멘트 출력
    print("\n💬 [3단계: ResponseGenerator AI 최종 코멘트]")
    print("-" * 70)
    print(result.get("comment", "(응답 없음)"))
    print("-" * 70)

    # 7. 세부 프로파일링 리포트 출력
    latencies = result.get("latencies", {})
    print_latency_report(latencies, result)

if __name__ == "__main__":
    main()
