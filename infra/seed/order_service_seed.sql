-- order-service 로컬·QA 테스트용 COMPLETED 주문 시드
-- 전제:
--   1) infra/seed/user_service_seed.sql (user_id=1001)
--   2) product-service 기동 또는 product SQL 시드로 product_id=4695999 옵션 존재
-- option_id는 DB IDENTITY이므로 무신사 옵션 번호(source_option_id)로 조회한다.
-- 재실행 시 order_id·order_item_id를 보존한다(리뷰·설문이 참조하는 ID 유지).
-- 실행:
--   docker compose exec -T postgres psql -U fitzza -d fitzza < infra/seed/order_service_seed.sql

BEGIN;

-- 옵션이 있을 때만 주문을 upsert (order_num 유니크로 order_id 보존)
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
FROM product_service.product_option po
WHERE po.product_id = 4695999 AND po.source_option_id = 21092422
ON CONFLICT (order_num) DO UPDATE SET
  user_id = EXCLUDED.user_id,
  total_price = EXCLUDED.total_price,
  order_status = EXCLUDED.order_status,
  recipient_name = EXCLUDED.recipient_name,
  recipient_phone = EXCLUDED.recipient_phone,
  shipping_address = EXCLUDED.shipping_address,
  updated_at = EXCLUDED.updated_at;

-- 기존 order_item이 있으면 갱신만(order_item_id 유지), 없으면 삽입
UPDATE order_service.order_item oi
SET
  order_qty = 1,
  unit_price = 27890,
  option_id = po.option_id
FROM order_service.orders o
JOIN product_service.product_option po
  ON po.product_id = 4695999 AND po.source_option_id = 21092422
WHERE o.order_num = 'ORD-SEED-1001-4695999'
  AND oi.order_id = o.order_id;

INSERT INTO order_service.order_item (order_id, option_id, order_qty, unit_price)
SELECT o.order_id, po.option_id, 1, 27890
FROM order_service.orders o
JOIN product_service.product_option po
  ON po.product_id = 4695999 AND po.source_option_id = 21092422
WHERE o.order_num = 'ORD-SEED-1001-4695999'
  AND NOT EXISTS (
    SELECT 1
    FROM order_service.order_item oi
    WHERE oi.order_id = o.order_id
  );

COMMIT;

-- 확인:
-- SELECT order_id, order_num, user_id, order_status, total_price
-- FROM order_service.orders WHERE order_num = 'ORD-SEED-1001-4695999';
-- SELECT oi.order_item_id, oi.option_id, oi.order_qty, oi.unit_price
-- FROM order_service.order_item oi
-- JOIN order_service.orders o ON o.order_id = oi.order_id
-- WHERE o.order_num = 'ORD-SEED-1001-4695999';
