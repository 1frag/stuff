import os


def paste():
    txt = os.popen('xsel -b').read()
    txt = txt.replace('\u2010\n', '').replace('\n', ' ')
    while '  ' in txt:
        txt = txt.replace('  ', ' ')
    return txt
