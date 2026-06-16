create database fence;
create user fence_user with encrypted password 'fence-pass';
grant all privileges on database fence to fence_user;
