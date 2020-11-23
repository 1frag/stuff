import json
import os
import sys
import dataclasses
import pathlib

from .flow import WorkFlow, Cursor, GoogleSheet


def save_cursor(cursor: Cursor):
    m, _ = os.path.split(__file__)
    meta = {}
    with open(m + '/meta.json') as meta['file']:
        meta['dict'] = json.load(meta['file'])
    meta['dict']['CURSOR'] = dataclasses.astuple(cursor)
    with open(m + '/meta.json', 'w') as meta['file']:
        json.dump(meta['dict'], meta['file'], indent=4, ensure_ascii=False)
    del meta
    print('\033[0m\nStopped.')


def get_cursor() -> Cursor:
    """ meta.json should looks like:
    {"CURSOR": ["your_list_name", "A", 5]}
    """
    try:
        meta = {}
        with open(pathlib.Path(__file__).parent / 'meta.json') as meta['file']:
            meta['dict'] = json.load(meta['file'])
            cursor = Cursor(*meta['dict']['CURSOR'])
        del meta
        return cursor
    except (FileNotFoundError, KeyError):
        print('Meta data not provided')
        exit(1)


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == 'sign':
        GoogleSheet.generate_signed_files(sys.argv[2], sys.argv[3])
        exit(0)
    if len(sys.argv) == 4 and sys.argv[1] == 'learn':
        f, t = map(int, sys.argv[2:])
        a = GoogleSheet().get(f'A{f}:A{t}')
        c = GoogleSheet().get(f'C{f}:C{t}')
        assert len(a) == len(c)
        with open('out.txt', 'w') as out:
            for ai, ci in zip(a, c):
                if len(ai) and len(ci):
                    out.write(f'{ai[0]}\t{ci[0]}\n')
        exit(0)
    WorkFlow(get_cursor(), save_cursor).run()
