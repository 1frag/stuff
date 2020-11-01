import json
import os
import dataclasses

from .flow import WorkFlow, Cursor


def save_data(cursor: Cursor):
    m, _ = os.path.split(__file__)
    meta = {}
    with open(m + '/meta.json') as meta['file']:
        meta['dict'] = json.load(meta['file'])
    meta['dict']['CURSOR'] = dataclasses.astuple(cursor)
    with open(m + '/meta.json', 'w') as meta['file']:
        json.dump(meta['dict'], meta['file'], indent=4, ensure_ascii=False)
    del meta
    print('\033[0m\nStopped.')


def prepare_data() -> tuple[str, Cursor, list[str]]:
    """ meta.json should looks like:
    {"SHEET_ID": "1234XX49aumSUVqYtG-5pThdQsT_test8R57INSUvDo0",
     "CURSOR": ["your_list_name", "A", 5]}
    """
    try:
        m, _ = os.path.split(__file__)
        meta = {}
        with open(m + '/meta.json') as meta['file']:
            meta['dict'] = json.load(meta['file'])
            sheet_id = meta['dict']['SHEET_ID']
            cursor = Cursor(*meta['dict']['CURSOR'])
        del meta
        return sheet_id, cursor, [m + '/credentials.json', m + '/credentials2.json']
    except (FileNotFoundError, KeyError):
        print('Meta data not provided')
        exit(1)


if __name__ == '__main__':
    sid, c, m = prepare_data()
    WorkFlow(sid, c, m, save_data).run()
