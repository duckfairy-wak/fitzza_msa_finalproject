-- order-service 로컬·QA 테스트용 COMPLETED 주문 시드
-- 전제:
--   1) infra/seed/user_service_seed.sql (user_id=1001)
--   2) product-service 기동 또는 product SQL 시드로 product_id=4695999 옵션 존재
-- option_id는 DB IDENTITY이므로 무신사 옵션 번호(source_option_id)로 조회한다.
-- 실행:
--   docker compose exec -T postgres psql -U fitzza -d fitzza < infra/seed/order_service_seed.sql

BEGIN;

-- 동일 시드 주문 재실행 시 기존 행 제거
DELETE FROM order_service.order_item
WHERE order_id IN (
  SELECT order_id FROM order_service.orders WHERE order_num = 'ORD-SEED-1001-4695999'
);
DELETE FROM order_service.orders WHERE order_num = 'ORD-SEED-1001-4695999';

WITH option_row AS (
  SELECT o.option_id
  FROM product_service.product_option o
  WHERE o.product_id = 4695999 AND o.source_option_id = 21092422
),
ins_order AS (
  INSERT INTO order_service.orders (
    order_num, user_id, total_price, order_status,
    recipient_name, recipient_phone, shipping_address,
    created_at, updated_at
  )
  SELECT
    'ORD-SEED-1001-4695999',
    1001,
    27890,
    'COMPLETED',
    '테스트유저',
    '01012345678',
    '서울시 강남구 테스트로 1',
    NOW(),
    NOW()
  FROM option_row
  RETURNING order_id
)
INSERT INTO order_service.order_item (order_id, option_id, order_qty, unit_price)
SELECT i.order_id, o.option_id, 1, 27890
FROM ins_order i
CROSS JOIN option_row o;

COMMIT;

-- 확인:
-- SELECT order_id, order_num, user_id, order_status, total_price
-- FROM order_service.orders WHERE order_num = 'ORD-SEED-1001-4695999';
-- SELECT oi.order_item_id, oi.option_id, oi.order_qty, oi.unit_price
-- FROM order_service.order_item oi
-- JOIN order_service.orders o ON o.order_id = oi.order_id
-- WHERE o.order_num = 'ORD-SEED-1001-4695999';
