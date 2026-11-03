-- 운영에서 선택지 이미지의 S3 Presigned URL이 2000자를 넘는 경우가 많아 1000자로는 저장에 실패한다.
alter table vote_options
    alter column image_url type varchar(3000);
