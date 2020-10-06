drop table if exists app_log;
create table app_log (
    id serial primary key,
    level varchar(16) default 'INFO',
    msg text not null,
    created_at timestamp default now(),
    context text[]
);
