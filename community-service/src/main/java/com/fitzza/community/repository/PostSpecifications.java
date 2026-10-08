package com.fitzza.community.repository;

import com.fitzza.community.domain.Post;
import com.fitzza.community.domain.PostCategory;
import com.fitzza.community.domain.PostType;
import jakarta.persistence.criteria.Predicate;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import org.springframework.data.jpa.domain.Specification;

public final class PostSpecifications {

    private static final char ESCAPE = '\\';

    private PostSpecifications() {
    }

    // 전달된 조건만 where 절에 넣는다. 삭제된 글은 항상 제외한다.
    public static Specification<Post> feed(PostCategory category, PostType postType, String keyword) {
        return (root, query, builder) -> {
            List<Predicate> predicates = new ArrayList<>();
            predicates.add(builder.isNull(root.get("deletedAt")));
            if (category != null) {
                predicates.add(builder.equal(root.get("category"), category));
            }
            if (postType != null) {
                predicates.add(builder.equal(root.get("postType"), postType));
            }
            if (keyword != null && !keyword.isBlank()) {
                String pattern = "%" + escapeLike(keyword.trim().toLowerCase(Locale.ROOT)) + "%";
                predicates.add(builder.or(
                        builder.like(builder.lower(root.<String>get("title")), pattern, ESCAPE),
                        builder.like(builder.lower(root.<String>get("content")), pattern, ESCAPE)));
            }
            return builder.and(predicates.toArray(new Predicate[0]));
        };
    }

    // 검색어의 %와 _가 와일드카드로 해석되지 않게 한다.
    static String escapeLike(String keyword) {
        return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
    }
}
