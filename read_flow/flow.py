from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build  # NoQA
from googletrans import Translator
from typing import Callable, Literal, Optional
import click
import dataclasses
import gi
import google.oauth2.credentials
import json
import keyboard
import os
import re
import requests
import rich.console
import rich.segment
import rich.table
import threading
import traceback

from . import utils

rich.table.Segment = type('Segment', (rich.segment.Segment,), {})
rich.table.Segment.line = classmethod(lambda cls: cls('\n\r'))

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk  # NoQA


@dataclasses.dataclass
class Cursor:
    sheet_name: str
    column: str
    row: int

    def where(self, op: Literal['get', 'update']):
        c = chr(ord(self.column) + 2)
        pattern = '{0}!{1}{2}:{3}{2}'
        if op == 'get':
            pattern = pattern.replace('{2}', '')
        return pattern.format(*dataclasses.astuple(self), c)


class WorkFlow:
    def goto(self, op: Literal['up', 'down']):
        self.cursor.row += 1 if (op == 'down') else -1
        self.output.update()

    def turn(self, op: Literal['on', 'off']):
        self.state['disable'] = (op == 'off')

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
            cursor: Cursor,
            path_to_creds: list[str],
            save_data: Callable[[Cursor], None]
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
        self.window = None
        self.output: Optional[Output] = None
        self.reload_from_net()

    def reload_from_net(self):
        print(os.popen('clear').read(), 'reloading...', sep='')
        self.output = Output(self.get_from_net(), self.cursor)
        self.output.update()

    def get_from_net(self):
        return self.sheet.values().get(
            spreadsheetId=self.sheet_id,
            range=self.cursor.where('get')
        ).execute()['values']

    def update_on_net(self, *args):  # args == [word, phonetic, translation]
        result = (self.sheet.values()
                  .update(spreadsheetId=self.sheet_id,
                          range=self.cursor.where('update'),
                          valueInputOption='RAW',
                          body={'values': [args]})
                  ).execute()
        self.cursor.row += 1
        return result

    def fill_empty_on_net(self):
        print('fill empty cmd...')
        data: list[list[str]] = self.get_from_net()
        self.log_file.write(json.dumps(data, indent=4, ensure_ascii=False))

        for row in data:
            if len(row) == 1:
                row.extend(self.info_on_word(row[0]))
                self.log_file.write(f'updating {row[0]}\n')
            if len(row) and not (row[1].startswith('[') and row[1].endswith(']')):
                row[1] = f'[{row[1]}]'
        self.sheet.values() \
            .update(spreadsheetId=self.sheet_id,
                    range=self.cursor.where('get'),
                    valueInputOption='RAW',
                    body={'values': data}) \
            .execute()
        self.reload_from_net()

    def set_workspace(self):
        for i in range(5, 0, -1):
            os.popen(f'echo {i} && sleep 1').read()
        self.window = utils.current_window()
        print('[+] Done')

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
                'start': lambda: self.turn('on'),
                'stop': lambda: self.turn('off'),
                'fill_empty': self.fill_empty_on_net,
                'reload': self.reload_from_net,
                'last_one': lambda: print(self.output.data[-1][0]),
                'set_workspace': self.set_workspace,
            }, self)
        except KeyboardInterrupt:
            self.save_data(self.cursor)


def listen(key_to_act, parent: 'WorkFlow'):
    set_at_cmd_reg = re.compile(r'set_at (\d+)')

    def complex_cmd():
        nonlocal cmd
        if match := set_at_cmd_reg.match(cmd):
            parent.cursor.row = match.group(1)
            parent.output.update()
            return
        print(f'`{cmd}` is not a command\r\nAvailable commands: ' +
              ', '.join(key_to_act) + '\r\n')

    while (c := click.getchar()) or True:
        if c in ['\x1b', '/']:  # esc or /
            parent.turn('off')
            cmd = utils.read_cmd()
            parent.turn('on')
            key_to_act.get(cmd, complex_cmd)()
        if c == '\x1b[A':  # up
            parent.goto('up')
        if c == '\x1b[B':  # down
            parent.goto('down')


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
        self.parent.output.new_word(utils.paste())


class WriteOnHook:
    def __init__(self, key_to_act: dict, parent: 'WorkFlow'):
        self.key_to_act = key_to_act
        self.parent = parent

    def start(self):
        keyboard.on_release(self.hook)

    def hook(self, evt):
        if self.parent.state['disable']:
            return
        if self.parent.window is not None:
            if utils.current_window() != self.parent.window:
                return
        self.key_to_act.get(evt.name, lambda: None)()


class Output:
    IncorrectUsage = type('IncorrectUsage', (Exception,), {})

    def __init__(self, data: list[list[str]], cursor: Cursor):
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
            style = 'blue bold' if row_id == self.cursor.row else None
            table.add_row(*self._render_row(row_id), style=style)
        self.console.clear()
        self.console.print(table, markup=False)

    def _render_row(self, row_id):
        if len(row := self.data[row_id]) != 3:
            return row
        if row[1] and row[1].startswith('['):
            row[1] = '\\' + row[1]
        return row
