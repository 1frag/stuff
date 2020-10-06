import os
import traceback
import functools
import janus
import asyncio
import aiopg.sa


class Logger:
    __instance = None

    def __new__(cls, *args, **kwargs):
        if Logger.__instance is None:
            cls.__instance = super().__new__(cls, *args, **kwargs)
            cls._call_once()
        return Logger.__instance

    @classmethod
    def _call_once(cls):
        cls.__instance._dsn = os.getenv('DATABASE_URL')
        cls.__instance._queue = None
        cls.__instance._db = None
        cls.__instance._wait = None
        cls.__instance.is_active = False

    def log(self, msg, *, level):
        self._queue.sync_q.put_nowait({
            'level': level,
            'msg': msg,
            'context': [
                f'{f.filename}:{f.lineno} {f.line}'
                for f in traceback.extract_stack()
            ]
        })

    error = functools.partialmethod(log, level='ERROR')
    warn = functools.partialmethod(log, level='WARN')
    info = functools.partialmethod(log, level='INFO')
    debug = functools.partialmethod(log, level='DEBUG')

    def __aiter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.is_active = False
        await self._queue.async_q.put(None)
        await self._wait
        self._db.close()
        await self._db.wait_closed()

    async def __aenter__(self):
        self.is_active = True
        self._queue = janus.Queue()
        self._db = await aiopg.sa.create_engine(dsn=self._dsn)
        self._wait = asyncio.ensure_future(self.routine())

    async def routine(self):
        while self.is_active:
            if (record := await self._queue.async_q.get()) is None:
                continue
            async with self._db.acquire() as conn:
                await conn.execute('''
                    insert into app_log (level, msg, context)
                    values (%s, %s, %s);
                ''', (record['level'], record['msg'], record['context']))
