# 서비스별 테이블 관계도

[원본 ERD](entity-relationship-diagram.mmd)를 서비스별로 나눈 ERD입니다. 각 테이블 아래에 원본의 전체 컬럼, 데이터 타입, PK·FK·UK 표시와 설명을 포함하고, 관계선에는 자식 테이블의 참조 컬럼을 표시했습니다. 외부 참조 테이블도 전체 컬럼을 표시합니다.

| 중심 서비스 | 관계도 | 소유 테이블 |
| --- | --- | --- |
| 사용자 | [user-service.mmd](user-service.mmd) | users, user_body, user_preferences |
| 상품 | [product-service.mmd](product-service.mmd) | brand, category, product, product_option, option_measurement, product_image, product_size_guide, wishlist, worldcup_history |
| 주문 / 장바구니 | [order-service.mmd](order-service.mmd) | orders, order_item, cart |
| 리뷰 / 사이즈 설문 | [review-service.mmd](review-service.mmd) | reviews, size_surveys |
| 추천 | [recommendation-service.mmd](recommendation-service.mmd) | recommendation_request, recommendation_slot, slot_candidate, outfit_combo, recommendation_message, combo_candidate |
| 알림 | [notification-service.mmd](notification-service.mmd) | notification_channel, notification_logs |
| 커뮤니티 | [community-service.mmd](community-service.mmd) | posts, post_shared_items, comments, post_likes, comment_likes, vote_options, votes |
| 가상 피팅 | [vton-service.mmd](vton-service.mmd) | fitting_job |

각 관계도는 중심 서비스의 내부 관계와 해당 서비스에 직접 연결되는 외부 테이블만 포함합니다. 중심 서비스의 소유 테이블과 외부 테이블의 소유 서비스는 소스 주석에 명시했습니다. 컬럼 정의는 중심 서비스 테이블을 먼저, 외부 테이블을 뒤에 배치했습니다. 서비스 간 관계는 양쪽 서비스의 뷰에 중복 표시됩니다.

관계 차수와 실선·점선은 원본 그대로 유지했습니다. `||`는 정확히 하나, `o|`는 0 또는 하나, `o{`는 0개 이상, `|{`는 하나 이상입니다. Mermaid의 실선은 식별 관계, 점선은 비식별 관계를 나타내며, 실제 DB의 FK 유무를 보장하지 않습니다. 서비스 간 연결은 논리적인 ID 참조이며 다른 서비스의 스키마 직접 조회를 의미하지 않습니다.

원본에 없는 관계는 추가하지 않았습니다. `category`는 독립 테이블로 표시하고, `reviews.order_item_id`의 UK와 원본의 1:N 관계선 간 불일치는 원본 표기를 유지했습니다. `wishlist.item_id` 등의 다형 참조 대상이나 댓글의 자기 참조도 원본에 관계선이 없어 추가하지 않았습니다.

미구현·미사용 표시는 원본 기준입니다. `user_preferences`, 추천 영역, `fitting_job`은 미구현이며 `notification_channel`은 미사용으로 표시되어 있습니다. 현재 구현이나 마이그레이션 상태를 확정하는 문서는 아닙니다.

## PNG images

- [community-service](images/community-service.png)
- [notification-service](images/notification-service.png)
- [order-service](images/order-service.png)
- [product-service](images/product-service.png)
- [recommendation-service](images/recommendation-service.png)
- [review-service](images/review-service.png)
- [user-service](images/user-service.png)
- [vton-service](images/vton-service.png)

Rendered with Mermaid CLI 12.0.0 using `--size 4800 -s 2 -b white`.

## SVG images

- [community-service](images/community-service.svg)
- [notification-service](images/notification-service.svg)
- [order-service](images/order-service.svg)
- [product-service](images/product-service.svg)
- [recommendation-service](images/recommendation-service.svg)
- [review-service](images/review-service.svg)
- [user-service](images/user-service.svg)
- [vton-service](images/vton-service.svg)

Rendered with Mermaid CLI 12.0.0 using `-b white`.
