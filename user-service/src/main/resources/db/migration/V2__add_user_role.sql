-- 사용자 역할(이슈 #225). 기존 사용자와 새 가입자는 모두 USER이고, 관리자는 운영에서 계정을 지정해 바꾼다.
alter table users add column role varchar(20) default 'USER' not null;
alter table users add constraint users_role_check check (role in ('USER', 'ADMIN'));
