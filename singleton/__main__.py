import threading
import os
import base64
import random
import asyncio
import singleton
import aiopg.sa
import fast_json


def log_something(repeat=5):
    logger = singleton.Logger()
    if repeat > 0:
        log_something(repeat - 1)

    random.choice([
        logger.error, logger.warn,
        logger.info, logger.debug,
    ])(msg=base64.encodebytes(os.urandom(32)))


async def log_slug():
    logger2 = singleton.Logger()
    logger3 = singleton.Logger()
    assert logger2 is logger3
    threads = [threading.Thread(target=lambda: log_something()),
               threading.Thread(target=lambda: log_something()),
               threading.Thread(target=lambda: log_something())]
    for _ in map(threading.Thread.start, threads):
        logger2.debug('Thread started')
    for _ in map(threading.Thread.join, threads):
        logger3.info('Thread joined')


async def migrate_db(db: aiopg.sa.Engine):
    with open('db.sql') as sql:
        async with db.acquire() as conn:
            await conn.execute(sql.read())


async def check_logs(db: aiopg.sa.Engine):
    with open('db_dump.json', 'w') as dump_file:
        async with db.acquire() as conn:
            records = await conn.execute('select * from app_log;')
            logs = await records.fetchall()
            obj = [dict(log) for log in logs]
        fast_json.dump(obj, dump_file, indent=2)


async def main():
    async with singleton.Logger():
        db = await aiopg.sa.create_engine(dsn=os.getenv('DATABASE_URL'))
        await migrate_db(db)
        await log_slug()
        await asyncio.sleep(5)  # give at most 5 sec to logs sending
    await check_logs(db)
    db.close()
    await db.wait_closed()


if __name__ == '__main__':
    asyncio.run(main())
