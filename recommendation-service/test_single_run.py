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

TEST_QUERY = "결혼식 하객룩으로 입을 깔끔한 셋업이랑 셔츠, 로퍼 추천해줘. 예산은 30만원 이하로 부탁해."
USER_ID = 1

def main():
    print("=" * 80)
    print("✨ [실시간 테스트] QueryParser: 6.1-sol / ResponseGenerator: 6-sol (후보 5개 적용)")
    print("=" * 80)

    # 1. User-Service 신체 데이터
    user_client = UserServiceClient()
    try:
        user_body = user_client.get_user_body(USER_ID)
        print(f"✅ User-Service 신체 데이터 로드 성공: 키 {user_body.get('height')}cm, 몸무게 {user_body.get('weight')}kg, 발 {user_body.get('shoeSize')}mm")
    except Exception as e:
        print(f"⚠️ User-Service 연동 실패: {e}")
        user_body = None

    # 2. 코디네이터 초기화
    coordinator = FashionPipelineCoordinator()
    print("✅ 코디네이터 초기화 완료!")
    print(f"   - QueryParser 모델     : {coordinator.parser.model_name}")
    print(f"   - OutfitHarmonizer 모델: {coordinator.harmonizer.model_name} (검수 후보: {harmonizer_module.MAX_CANDIDATES_TO_REVIEW}개)")
    print(f"   - ResponseGenerator 모델: {coordinator.responder.model_name}")

    print("\n" + "#" * 80)
    print(f"📌 [테스트 질의]: \"{TEST_QUERY}\"")
    print("#" * 80)

    # 3. 파이프라인 구동
    result = coordinator.run(
        user_query=TEST_QUERY,
        user_id=str(USER_ID),
        user_body=user_body,
    )

    # 4. 세부 프로파일링 리포트 출력
    latencies = result.get("latencies", {})
    print_latency_report(latencies, result)

    # 5. 응답 코멘트 출력
    print("\n💬 [AI 추천 코멘트 (Response Generator: gpt-6.1-sol)]")
    print("-" * 70)
    print(result.get("comment", "(응답 없음)"))
    print("-" * 70)

    # 6. 추천 코디 세트 점수 및 구성
    outfits = result.get("outfits", [])
    print(f"\n✨ 최종 확정된 코디 세트 ({len(outfits)}개):")
    for idx, outfit in enumerate(outfits, 1):
        print(f"\n  [코디 세트 {idx}] 총가격: {outfit.get('total_price', 0):,}원 | 최종 점수: {outfit.get('final_score')}점 | Vision 조화도: {outfit.get('harmony_score')}점")
        print(f"    - 심사평: {outfit.get('verdict')}")
        for item in outfit.get("items", []):
            print(f"      * [{item.get('category')} / {item.get('subcategory')}] {item.get('brand_name')} {item.get('product_name')} ({item.get('price', 0):,}원)")

if __name__ == "__main__":
    main()
