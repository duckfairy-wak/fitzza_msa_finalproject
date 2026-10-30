-- V2__seed_mock_orders.sql
-- userId=1 사용자의 실시간 추천 및 사이즈 분석용 실제 무신사 3,000건 연동 Mock 구매 이력

-- 1. 주문 데이터 (orders)
-- 주문 1: 블레이저 자켓 + 슬랙스 셋업 코디 (2026-10-28)
-- 주문 2: 셔츠 + 스니커즈 캐주얼 코디 (2026-10-23)
-- 주문 3: 볼캡 모자 (2026-10-16)

INSERT INTO order_service.orders (
    order_id,
    order_num,
    order_status,
    recipient_name,
    recipient_phone,
    shipping_address,
    total_price,
    created_at,
    updated_at,
    user_id
) VALUES 
(
    1,
    'ORD-20261028-A10101',
    'COMPLETED',
    '김경민',
    '010-1234-5678',
    '서울특별시 강남구 테헤란로 152 7층',
    89490,
    '2026-10-28 14:20:00+09',
    '2026-10-28 14:25:00+09',
    1
),
(
    2,
    'ORD-20261023-B20202',
    'COMPLETED',
    '김경민',
    '010-1234-5678',
    '서울특별시 강남구 테헤란로 152 7층',
    91790,
    '2026-10-23 11:10:00+09',
    '2026-10-23 11:15:00+09',
    1
),
(
    3,
    'ORD-20261016-C30303',
    'COMPLETED',
    '김경민',
    '010-1234-5678',
    '서울특별시 강남구 테헤란로 152 7층',
    46750,
    '2026-10-16 16:30:00+09',
    '2026-10-16 16:35:00+09',
    1
)
ON CONFLICT (order_id) DO NOTHING;

-- 2. 주문 상세 항목 (order_item)
-- option_id: product_service.product_option의 실제 옵션 ID와 1:1 매핑
-- 5805: [SET UP] 베이식 세미 오버핏 셋업 수트 M사이즈 (블레이저 자켓) - 63,900원
-- 31: 라이트웨이트 테이퍼드 히든 밴딩 10부 슬랙스 31사이즈 - 25,590원
-- 14355: 스테디 셔츠 - 라이트 그레이 M사이즈 - 49,800원
-- 8790: 레더 코트 스니커즈 [화이트] 270사이즈 - 41,990원
-- 5214: B LOGO 볼캡 [카모 블랙] FREE사이즈 - 46,750원

INSERT INTO order_service.order_item (
    order_item_id,
    order_id,
    option_id,
    order_qty,
    unit_price
) VALUES 
(1, 1, 5805, 1, 63900),
(2, 1, 31, 1, 25590),
(3, 2, 14355, 1, 49800),
(4, 2, 8790, 1, 41990),
(5, 3, 5214, 1, 46750)
ON CONFLICT (order_item_id) DO NOTHING;

-- 3. Identity Sequence 동기화
SELECT setval('order_service.orders_order_id_seq', (SELECT COALESCE(MAX(order_id), 1) FROM order_service.orders));
SELECT setval('order_service.order_item_order_item_id_seq', (SELECT COALESCE(MAX(order_item_id), 1) FROM order_service.order_item));
