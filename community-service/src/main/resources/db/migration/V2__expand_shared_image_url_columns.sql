-- S3 Presigned URL은 서명 파라미터에 따라 500자를 넘을 수 있다.
alter table posts
    alter column shared_image_url type text;

alter table post_shared_items
    alter column image_url type text;
