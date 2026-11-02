-- 투표 선택지 이미지도 S3 Presigned URL이라 서명 파라미터에 따라 500자를 넘을 수 있다.
alter table vote_options
    alter column image_url type varchar(1000);
