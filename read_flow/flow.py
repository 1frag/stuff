from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build  # NoQA
from googletrans import Translator
from typing import Callable
import click
import gi
import google.oauth2.credentials
import keyboard
import os
import re
import requests
import rich.console
import rich.segment
import rich.table
import threading

from . import utils

rich.table.Segment = type('Segment', (rich.segment.Segment,), {})
rich.table.Segment.line = classmethod(lambda cls: cls('\n\r'))

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk  # NoQA

CURSOR_TYPE = list[str]  # [word, phonetic, translation]


class WorkFlow:
    def goto(self, up=False, down=False):
        assert up ^ down
        self.cursor[-1] += 1 if (down or not up) else -1
        self.output.update()

    def turn(self, on=False, off=False):
        assert on ^ off
        self.state['disable'] = (off or not on)

    def translate_only(self, word=None):
        word = word or utils.paste()
        translation = list(self.info_on_word(word, False))[0]
        self.output.fill_props(None, translation)

    def write_result(self, word=None):
        word = word or utils.paste()
        phonetic, translation = self.info_on_word(word)
        self.update_on_net(word, phonetic, translation)
        self.output.fill_props(phonetic, translation)

    def __init__(
            self,
            sheet_id: str,
            cursor: CURSOR_TYPE,
            path_to_creds: list[str],
            save_data: Callable[[CURSOR_TYPE], None]
    ):
        self.flow = InstalledAppFlow.from_client_secrets_file(
            path_to_creds[0], ['https://www.googleapis.com/auth/spreadsheets']
        )
        self.creds = google.oauth2.credentials.Credentials.from_authorized_user_file(
            path_to_creds[1]
        )
        self.service = build('sheets', 'v4', credentials=self.creds)
        self.sheet = self.service.spreadsheets()
        self.cursor = cursor
        self.sheet_id = sheet_id
        self.phonetic_reg = re.compile(r'class="transcribed_word">([^<]*)<')
        self.save_data = save_data
        self.disable = True
        self.state = {'disable': False}
        self.output = Output(self.get_from_net(), self.cursor)
        self.output.update()

    def where(self, get=False, update=False):
        assert get ^ update
        c = chr(ord(self.cursor[1]) + 2)
        pattern = '{0}!{1}{2}:{3}{2}'
        if get or not update:
            pattern = pattern.replace('{2}', '')
        return pattern.format(*self.cursor, c)

    def get_from_net(self):
        return self.sheet.values().get(
            spreadsheetId=self.sheet_id,
            range=self.where(get=True)
        ).execute()['values']

    def update_on_net(self, *args):  # args == [word, phonetic, translation]
        result = (self.sheet.values()
                  .update(spreadsheetId=self.sheet_id,
                          range=self.where(update=True),
                          valueInputOption='RAW',
                          body={'values': [args]})
                  ).execute()
        self.cursor[-1] += 1
        return result

    @staticmethod
    def handle_clipboard():
        txt = os.popen('xsel -b').read()
        txt = txt.replace('-\n', '').replace('\n', ' ')
        while '  ' in txt:
            txt = txt.replace('  ', ' ')
        return txt

    def info_on_word(
            self,
            word: str,
            need_phonetic: bool = True,
            need_translation: bool = True,
    ):
        if need_phonetic:
            req = requests.post('https://tophonetics.com/',
                                data={'text_to_transcribe': word})
            phons = self.phonetic_reg.findall(req.content.decode())
            yield '[' + ' '.join(phons or ['']) + ']'

        if need_translation:
            yield Translator().translate(word, src='english', dest='russian').text

    def run(self):
        try:
            WriteOnCopy(self.output, self.state).start()
            WriteOnHook({
                't': self.translate_only,
                'w': self.write_result,
            }, self.state).start()
            listen({
                'start': lambda: self.turn(on=True),
                'stop': lambda: self.turn(off=True),
            }, self.goto)
        except KeyboardInterrupt:
            self.save_data(self.cursor)


def listen(key_to_act, goto):
    while (c := click.getchar()) or True:
        if c in ['\x1b', '/']:  # esc or /
            # move cursor to last line, input
            cmd = input('\033[' + os.popen('tput lines').read() + ';0H')
            key_to_act.get(cmd, lambda: None)()
        if c == '\x1b[A':  # up
            goto(up=True)
        if c == '\x1b[B':  # down
            goto(down=True)
        if c == 'q':
            return


class WriteOnCopy(threading.Thread):
    def __init__(self, output: 'Output', state: dict):
        super().__init__(target=self.target, daemon=True)
        self.clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.output = output
        self.state = state

    def target(self):
        self.clip.connect('owner-change', self.callback)
        Gtk.main()

    def callback(self, *_):
        if self.state['disable']:
            return
        self.output.new_word(self.clip.wait_for_text())


class WriteOnHook:
    def __init__(self, key_to_act: dict, state: dict):
        self.key_to_act = key_to_act
        self.state = state

    def start(self):
        keyboard.on_release(self.hook)

    def hook(self, evt):
        if self.state['disable']:
            return
        self.key_to_act.get(evt.name, lambda: None)()


class Output:
    IncorrectUsage = type('IncorrectUsage', (Exception,), {})

    def __init__(self, data: list[list], cursor: CURSOR_TYPE):
        if len(data) == 0:
            raise self.IncorrectUsage()
        self.data = data
        self.console = rich.console.Console()
        self.cursor = cursor

    def new_word(self, word):
        if len(self.data[-1]) == 1:
            self.data[-1:] = []
        self.data.append([])
        self.data[-1].append(word)
        self.update()

    def fill_props(self, phonetic, translation):
        if len(self.data[-1]) != 1:
            raise self.IncorrectUsage()
        self.data[-1].extend((phonetic, translation))
        self.update()

    def update(self):
        table = rich.table.Table()
        for title in self.data[0]:
            table.add_column(title, style="dim", width=12)
        for row_id in range(1, len(self.data)):
            style = 'blue bold' if row_id == self.cursor[-1] else None
            table.add_row(*self.data[row_id], style=style)
        self.console.clear()
        self.console.print(table, end='xx\r\n')
