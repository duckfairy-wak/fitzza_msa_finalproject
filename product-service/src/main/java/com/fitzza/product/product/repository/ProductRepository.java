package com.fitzza.product.product.repository;

import com.fitzza.product.product.entity.ProductEntity;
import com.fitzza.product.product.entity.ProductStatus;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ProductRepository
        extends JpaRepository<ProductEntity, Long>, JpaSpecificationExecutor<ProductEntity> {

    @Override
    @EntityGraph(attributePaths = "brand")
    Page<ProductEntity> findAll(Specification<ProductEntity> specification, Pageable pageable);

    @EntityGraph(attributePaths = "brand")
    Optional<ProductEntity> findWithBrandByProductId(Long productId);

    @Query("select p from ProductEntity p join fetch p.brand where p.productId in :productIds")
    List<ProductEntity> findAllWithBrandByProductIdIn(@Param("productIds") Collection<Long> productIds);

    @Query("select p from ProductEntity p join fetch p.brand where p.status = :status order by random()")
    List<ProductEntity> findRandomWithBrandByStatus(@Param("status") ProductStatus status, Pageable pageable);

    @Query("""
            select distinct
                p.category1 as category1, p.category2 as category2, p.subcategory as subcategory
            from ProductEntity p
            where p.status <> :excludedStatus
            order by p.category1, p.category2, p.subcategory
            """)
    List<CategoryPathProjection> findDistinctCategoryPaths(@Param("excludedStatus") ProductStatus excludedStatus);

    /**
     * 대분류에 이름이 저장된 상품을 카테고리 테이블의 코드로 바꾼다. 이미 코드인 값은 어떤 카테고리 이름과도
     * 일치하지 않아 변경되지 않으므로 여러 번 실행해도 결과가 같다.
     */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("""
            update ProductEntity p
            set p.category1 = (
                select min(c.categoryCode) from CategoryEntity c
                where c.depth = 1 and c.categoryName = p.category1)
            where exists (
                select 1 from CategoryEntity c
                where c.depth = 1 and c.categoryName = p.category1)
            """)
    int replaceCategory1NameWithCode();

    /** 중분류 이름을 코드로 바꾼다. 같은 이름이 다른 대분류에 있어도 구분되도록 상위 코드가 일치하는 카테고리만 찾는다. 대분류를 먼저 변환한 뒤 실행해야 한다. */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("""
            update ProductEntity p
            set p.category2 = (
                select min(c.categoryCode) from CategoryEntity c
                where c.depth = 2 and c.categoryName = p.category2 and c.parentCode = p.category1)
            where p.category2 is not null and exists (
                select 1 from CategoryEntity c
                where c.depth = 2 and c.categoryName = p.category2 and c.parentCode = p.category1)
            """)
    int replaceCategory2NameWithCode();

    /** 소분류 이름을 코드로 바꾼다. 중분류를 먼저 변환한 뒤 실행해야 한다. */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("""
            update ProductEntity p
            set p.subcategory = (
                select min(c.categoryCode) from CategoryEntity c
                where c.depth = 3 and c.categoryName = p.subcategory and c.parentCode = p.category2)
            where p.subcategory is not null and exists (
                select 1 from CategoryEntity c
                where c.depth = 3 and c.categoryName = p.subcategory and c.parentCode = p.category2)
            """)
    int replaceSubcategoryNameWithCode();

    /** 카테고리 테이블에 없는 값(변환되지 않은 이름 등)이 저장된 상품 수. */
    @Query("""
            select count(p) from ProductEntity p
            where p.category1 not in (select c.categoryCode from CategoryEntity c)
               or (p.category2 is not null and p.category2 not in (select c.categoryCode from CategoryEntity c))
               or (p.subcategory is not null and p.subcategory not in (select c.categoryCode from CategoryEntity c))
            """)
    long countWithUnknownCategoryCode();

    @Query("select p.sourceProductId from ProductEntity p where p.source = :source and p.sourceProductId is not null")
    Set<Long> findSourceProductIds(@Param("source") String source);

    boolean existsByProductIdAndStatusNot(Long productId, ProductStatus status);
}
