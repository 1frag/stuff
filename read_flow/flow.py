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
        try:
            self.output.fill_props(None, translation)
        except Output.IncorrectUsage:
            print('Attempt to fill props failed')

    def write_result(self, word=None):
        word = word or utils.paste()
        phonetic, translation = self.info_on_word(word)
        self.update_on_net(word, phonetic, translation)
        try:
            self.output.fill_props(phonetic, translation)
        except Output.IncorrectUsage:
            print('Attempt to fill props failed')

    def __init__(
            self,
            sheet_id: str,
            cursor: CURSOR_TYPE,
            path_to_creds: list[str],
            save_data: Callable[[CURSOR_TYPE], None]
    ):
        self.log_file = open('log.txt', 'w')
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
        self.output = None
        self.reload_from_net()

    def reload_from_net(self):
        print('reloading...')
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

    def fill_empty_on_net(self):
        print('fill empty cmd...')
        data: list[list[str]] = self.get_from_net()
        import json
        self.log_file.write(json.dumps(data, indent=4, ensure_ascii=False))

        for row in data:
            if len(row) == 1:
                row.extend(self.info_on_word(row[0]))
                self.log_file.write(f'updating {row[0]}\n')
            if len(row) and not (row[1].startswith('[') and row[1].endswith(']')):
                row[1] = f'[{row[1]}]'
        self.sheet.values() \
            .update(spreadsheetId=self.sheet_id,
                    range=self.where(get=True),
                    valueInputOption='RAW',
                    body={'values': data}) \
            .execute()
        self.reload_from_net()

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
            try:
                yield Translator().translate(
                    word, src='english', dest='russian'
                ).text
            except AttributeError:
                import traceback
                self.log_file.write(traceback.format_exc())
                yield ''

    def run(self):
        try:
            WriteOnCopy(self).start()
            WriteOnHook({
                't': self.translate_only,
                'w': self.write_result,
            }, self).start()
            listen({
                'start': lambda: self.turn(on=True),
                'stop': lambda: self.turn(off=True),
                'fill_empty': self.fill_empty_on_net,
                'reload': self.reload_from_net,
                'last_one': lambda: print(self.output.data[-1][0]),
            }, self)
        except KeyboardInterrupt:
            self.save_data(self.cursor)


def listen(key_to_act, parent: 'WorkFlow'):
    def not_found_cmd():
        nonlocal cmd
        print(f'`{cmd}` is not a command\r\nAvailable commands: ' +
              ', '.join(key_to_act) + '\r\n')

    while (c := click.getchar()) or True:
        if c in ['\x1b', '/']:  # esc or /
            # move cursor to last line, input
            parent.turn(off=True)
            cmd = input('\033[' + os.popen('tput lines').read() + ';0H$ ')
            parent.turn(on=True)
            key_to_act.get(cmd, not_found_cmd)()
        if c == '\x1b[A':  # up
            parent.goto(up=True)
        if c == '\x1b[B':  # down
            parent.goto(down=True)
        if c == 'q':
            return


class WriteOnCopy(threading.Thread):
    def __init__(self, parent: 'WorkFlow'):
        super().__init__(target=self.target, daemon=True)
        self.clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.parent = parent

    def target(self):
        self.clip.connect('owner-change', self.callback)
        Gtk.main()

    def callback(self, *_):
        if self.parent.state['disable']:
            return
        self.parent.output.new_word(self.clip.wait_for_text())


class WriteOnHook:
    def __init__(self, key_to_act: dict, parent: 'WorkFlow'):
        self.key_to_act = key_to_act
        self.parent = parent

    def start(self):
        keyboard.on_release(self.hook)

    def hook(self, evt):
        if self.parent.state['disable']:
            return
        self.key_to_act.get(evt.name, lambda: None)()


class Output:
    IncorrectUsage = type('IncorrectUsage', (Exception,), {})

    def __init__(self, data: list[list[str]], cursor: CURSOR_TYPE):
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
            print(self.data[-3:], sep='\r\n', end='\r\n')
            raise self.IncorrectUsage()
        self.data[-1].extend((phonetic, translation))
        self.update()

    def update(self):
        table = rich.table.Table(show_lines=True)
        for title in self.data[0]:
            table.add_column(title, style="dim", overflow='fold', width=12)
        for row_id in range(1, len(self.data)):
            style = 'blue bold' if row_id == self.cursor[-1] else None
            table.add_row(*self._render_row(row_id), style=style)
        self.console.clear()
        self.console.print(table, markup=False)

    def _render_row(self, row_id):
        if len(row := self.data[row_id]) != 3:
            return row
        if row[1] and row[1].startswith('['):
            row[1] = '\\' + row[1]
        return row
