from __future__ import annotations

# 무신사 현재 상위 카테고리 코드
CATEGORY_CONFIG = {
    "상의": {
        "source_category": "001",
        "total_quota": 900,
        "season_quota": {"봄": 225, "여름": 225, "가을": 225, "겨울": 225},
    },
    "하의": {
        "source_category": "003",
        "total_quota": 750,
        "season_quota": {"봄": 188, "여름": 187, "가을": 188, "겨울": 187},
    },
    "신발": {
        "source_category": "103",
        "total_quota": 600,
        "season_quota": {"봄": 150, "여름": 150, "가을": 150, "겨울": 150},
        "season_balance_required": False,
    },
    "아우터": {
        "source_category": "002",
        "total_quota": 450,
        "season_quota": {"봄": 113, "여름": 112, "가을": 113, "겨울": 112},
    },
    "모자": {
        "source_category": "120",
        "total_quota": 300,
        "season_quota": {"봄": 75, "여름": 75, "가을": 75, "겨울": 75},
        "season_balance_required": False,
    },
}

TOTAL_TARGET = sum(config["total_quota"] for config in CATEGORY_CONFIG.values())

# 무신사 남성 필터.
# 카테고리 화면의 '남' 필터에 해당하며 공용 상품도 포함될 수 있다.
GENDER_FILTER = "M"

# 후보군 편향을 줄이기 위해 서로 다른 정렬을 섞는다.
DISCOVERY_SORT_CODES = [
    "POPULAR",
    "NEW",
    "REVIEW",
    "LOW_PRICE",
    "HIGH_PRICE",
]

DEFAULT_PAGE_SIZE = 20
DEFAULT_PAGES_PER_SORT = 1

# 무리한 요청을 피하기 위한 요청 간 대기 시간
REQUEST_DELAY_SECONDS = 0.8
