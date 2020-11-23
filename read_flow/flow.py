from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googletrans import Translator
from typing import Callable, Literal
import click
import dataclasses
import gi
import google.oauth2.credentials
import pathlib
import json
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
        Output().update()

    def turn(self, op: Literal['on', 'off']):
        self.state['disable'] = (op == 'off')

    @staticmethod
    def translate_only(word=None):
        word = word or utils.paste()
        translation = Informator(word).translation().get_one()
        try:
            Output().fill_props(None, translation)
        except Output.IncorrectUsage:
            Output().print('Attempt to fill props failed')

    def write_result(self, word=None):
        word = word or utils.paste()
        phonetic, translation = Informator(word).phonetic().translation().get_all()
        self.g_sheet.update(self.cursor.where('update'), (word, phonetic, translation))
        self.cursor.row += 1
        try:
            Output().fill_props(phonetic, translation)
        except Output.IncorrectUsage:
            Output().print('Attempt to fill props failed')

    def __init__(
            self, cursor: Cursor, save_data: Callable[[Cursor], None]
    ):
        self.g_sheet = GoogleSheet()
        self.cursor = cursor
        self.save_data = save_data
        self.disable = True
        self.state = {'disable': False}
        self.window = None
        self.reload_from_net()

    def fill_empty_on_net(self):
        print('fill empty cmd...')
        data: list[list[str]] = self.g_sheet.get(self.cursor.where('get'))
        Output().log_file.write(json.dumps(data, indent=4, ensure_ascii=False))

        for row in data:
            if len(row) == 1:
                row.extend(Informator(row[0]).phonetic().translation().get_all())
                Output().log_file.write(f'updating {row[0]}\n')
            if len(row) and not (row[1].startswith('[') and row[1].endswith(']')):
                row[1] = f'[{row[1]}]'

        self.g_sheet.update(self.cursor.where('get'), data)
        self.cursor.row += 1
        self.reload_from_net()

    def reload_from_net(self):
        Output().print(os.popen('clear').read(), 'reloading...', sep='')
        Output().set_params(self.g_sheet.get(self.cursor.where('get')), self.cursor)
        Output().update()

    def set_workspace(self):
        for i in range(5, 0, -1):
            os.popen(f'echo {i} && sleep 1').read()
        self.window = utils.current_window()
        print('[+] Done')

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
                'last_one': lambda: Output().print(Output().data[-1][0]),
                'set_workspace': self.set_workspace,
            }, self)
        except KeyboardInterrupt:
            self.save_data(self.cursor)


class GoogleSheet:
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

    def __init__(self):
        c1, c2, self.sheet_id = self._decrypting()
        self.flow = InstalledAppFlow.from_client_config(c1, self.SCOPES)
        self.creds = google.oauth2.credentials.Credentials.from_authorized_user_info(c2)
        self.service = build('sheets', 'v4', credentials=self.creds)
        self.sheet = self.service.spreadsheets()

    def get(self, requested_range):
        return self.sheet.values().get(
            spreadsheetId=self.sheet_id,
            range=requested_range,
        ).execute()['values']

    def update(self, requested_range, body):
        result = (self.sheet.values()
                  .update(spreadsheetId=self.sheet_id,
                          range=requested_range,
                          valueInputOption='RAW',
                          body={'values': [body]})
                  ).execute()
        return result

    @classmethod
    def generate_signed_files(cls, path_to_cred, sheet_id):
        """
        To get :path_to_cred, please, visit
        https://developers.google.com/sheets/api/quickstart/python#step_1_turn_on_the
        """
        tokens = []
        with open(path_to_cred) as c1:
            tokens.append(json.load(c1))
        flow = InstalledAppFlow.from_client_secrets_file(path_to_cred, cls.SCOPES)
        tokens.append(json.loads(flow.run_console().to_json()))
        sign = utils.encrypt(json.dumps({'tokens': tokens, 'sheet_id': sheet_id}), os.getenv('RF_TOKEN'))
        with open('signed.pwd', 'w') as signed:
            i = 0
            while i <= len(sign):
                signed.write(sign[i:i+80] + '\n')
                i += 80

    @staticmethod
    def _decrypting():
        with open(pathlib.Path(__file__).parent / 'signed.pwd') as signed:
            sign = signed.read().replace('\n', '')
        payload = json.loads(utils.decrypt(sign, os.getenv('RF_TOKEN')))
        return payload['tokens'] + [payload['sheet_id']]


class Informator:
    phonetic_reg = re.compile(r'class="transcribed_word">([^<]*)<')

    def __init__(self, word):
        self.word = word
        self._result = []
        self.get_all = lambda: self._result
        self.get_one = lambda: self._result[0]

    def phonetic(self):
        req = requests.post('https://tophonetics.com/', data={'text_to_transcribe': self.word})
        phonetics = self.phonetic_reg.findall(req.content.decode())
        self._result.append('[' + ' '.join(phonetics or ['']) + ']')
        return self

    def translation(self):
        for _ in range(10):  # library sometimes raise exceptions, we have to repeat request
            try:
                self._result.append(Translator().translate(self.word, src='english', dest='russian').text)
                return self
            except (AttributeError, TypeError):
                pass
        self._result.append(None)
        return self


def listen(key_to_act, parent: 'WorkFlow'):
    set_at_cmd_reg = re.compile(r'set_at (\d+)')

    def complex_cmd():
        nonlocal cmd
        if match := set_at_cmd_reg.match(cmd):
            parent.cursor.row = match.group(1)
            Output().update()
        else:
            Output().print(f'`{cmd}` is not a command\r\nAvailable commands: ' + ', '.join(key_to_act) + '\r\n')

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
        self.clip = Gtk.Clipboard().get(Gdk.SELECTION_CLIPBOARD)
        self.parent = parent

    def target(self):
        self.clip.connect('owner-change', self.callback)
        Gtk.main()

    def callback(self, *_):
        if self.parent.state['disable']:
            return
        Output().new_word(utils.paste())


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
    print = print
    __instance: 'Output' = None
    data, console, cursor = None, None, None
    log_file = open('log.txt', 'w')

    def __new__(cls, *args, **kwargs):
        if Output.__instance is None:
            cls.__instance = super().__new__(cls, *args, **kwargs)
        return Output.__instance

    def set_params(self, data: list[list[str]], cursor: Cursor):
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
