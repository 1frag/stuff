import gi
import keyboard
import os
import re
import requests
import rich.console
import rich.table
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build  # NoQA
from googletrans import Translator
from typing import List, Callable

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk  # NoQA

CURSOR_TYPE = List[str]  # [word, phonetic, translation]


class Hooker:
    def __init__(self):
        self.triggers = {}
        self.do = self.triggers.get

    def on(self, x):
        def deco(func):
            self.triggers[x] = func
            return func

        return deco


class WorkFlow:
    hotkeys = {
        'c': 'print where is the [c]ursor now',
        'n': 'go cursor to [n]ext item',
        'p': 'go cursor to [p]review item',
        'r': '[r]esume handling',
        's': '[s]top handling',
        'u': 'print c[u]rrent state',
        't': 'only print [t]ranslate',
        'w': '[w]rite down word (phonetic + translate) at sheets and print them',
        'h': 'print [h]elp',
    }
    hook = Hooker()

    @hook.on('c')
    def print_cursor(self):
        print('\n', 'You are at', self.where())

    @hook.on('n')
    def next_item(self):
        self.cursor[-1] = str(int(self.cursor[-1]) + 1)

    @hook.on('p')
    def prev_item(self):
        self.cursor[-1] = str(int(self.cursor[-1]) - 1)

    @hook.on('s')
    def stop(self):
        self.disable = True

    @hook.on('t')
    def translate_only(self):
        word = self.handle_clipboard()
        translation = list(self.info_on_word(word, False))[0]
        self.output.fill_props(None, translation)

    @hook.on('w')
    def write_result(self):
        word = self.handle_clipboard()
        phonetic, translation = self.info_on_word(word)
        self.add_to_net(word, phonetic, translation)
        self.output.fill_props(phonetic, translation)

    @hook.on('h')
    def help(self):
        print('Help called:')
        print('\n'.join(map(lambda x: '{0} - {1}'.format(*x),
                            self.hotkeys.items())))

    @hook.on('u')
    def print_current_state(self):
        if self.disable:
            print('Disabled')
        else:
            print('Enabled')

    @hook.on('r')
    def _(self):
        pass

    assert sorted(hook.triggers.keys()) == sorted(hotkeys.keys())

    def __init__(
            self,
            sheet_id: str,
            cursor: CURSOR_TYPE,
            path_to_cred: str,
            save_data: Callable[[CURSOR_TYPE], None]
    ):
        self.flow = InstalledAppFlow.from_client_secrets_file(
            path_to_cred, ['https://www.googleapis.com/auth/spreadsheets']
        )
        self.creds = self.flow.run_local_server(port=0)
        self.service = build('sheets', 'v4', credentials=self.creds)
        self.sheet = self.service.spreadsheets()
        self.cursor = cursor
        self.sheet_id = sheet_id
        self.phonetic_reg = re.compile(r'class="transcribed_word">([^<]*)<')
        self.save_data = save_data
        self.disable = True
        self.output = Output([
            ['Word', 'Transcription', 'Translation'],
            ['acquire', '[əˈkwaɪə]', 'приобретать'],
        ])  # todo: get previews

    def where(self):
        c = chr(ord(self.cursor[1]) + 2)
        return '{0}!{1}{2}:{3}{2}'.format(*self.cursor, c)

    def add_to_net(self, *args):  # args == [word, phonetic, translation]
        result = (self.sheet.values()
                  .update(spreadsheetId=self.sheet_id,
                          range=self.where(),
                          valueInputOption='RAW',
                          body={'values': [args]})
                  ).execute()
        self.cursor[-1] = str(int(self.cursor[-1]) + 1)
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

    def prepare_hook(self, keyboard_event):
        if not keyboard_event.event_type != 'down':
            return
        if self.disable and keyboard_event.name == 'r':
            self.disable = bool(input('Confirm here: ') == 'no')
        if not self.disable:
            if func := self.hook.do(keyboard_event.name):
                func(self)

    def run(self):
        clip, uc = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD), 1
        rm_hook = keyboard.hook(self.prepare_hook)

        def callback(*_):
            nonlocal clip, uc
            self.output.new_word(clip.wait_for_text())

        clip.connect('owner-change', callback)
        try:
            Gtk.main()
            rm_hook()
        except KeyboardInterrupt:
            self.save_data(self.cursor)


class Output:
    IncorrectUsage = type('IncorrectUsage', (Exception,), {})

    def __init__(self, data: list[list]):
        if len(data) == 0:
            raise self.IncorrectUsage
        self.data = data
        self.console = rich.console.Console()

    def new_word(self, word):
        if len(self.data[-1]) != 1:
            self.data.append([])
        self.data[-1].append(word)
        self.update()

    def fill_props(self, phonetic, translation):
        if len(self.data[-1]) != 1:
            raise self.IncorrectUsage
        self.data[-1].extend((phonetic, translation))
        self.update()

    def update(self):
        table = rich.table.Table()
        for title in self.data[0]:
            table.add_column(title, style="dim", width=12)
        for row in self.data[1:]:
            table.add_row(*row)
        self.console.clear()
        self.console.print(table)
