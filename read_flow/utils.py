import os


def paste():
    txt = os.popen('xsel -b').read()
    txt = txt.replace('\u2010\n', '').replace('\n', ' ')
    while '  ' in txt:
        txt = txt.replace('  ', ' ')
    return txt


def current_window():
    return os.popen(
        'cat /proc/$(xdotool getwindowpid $(xdotool getwindowfocus))/comm'
    ).read()


def read_cmd():
    """ move cursor to last line, input """
    return input('\033[' + os.popen('tput lines').read() + ';0H$ ')
