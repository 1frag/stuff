import gi
import keyboard
import os
import re
import requests
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build  # NoQA
from googletrans import Translator
from typing import List, Callable

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk  # NoQA
CURSOR_TYPE = List[str]  # [word, phonetic, translation]


class WorkFlow:
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
        self.no_end = False
        self.written = set()
        self.phonetic_reg = re.compile(r'class="transcribed_word">([^<]*)<')
        self.save_data = save_data

    def where(self):
        c = chr(ord(self.cursor[1]) + 2)
        return '{0}!{1}{2}:{3}{2}'.format(*self.cursor, c)

    def add(self, *args):  # args == [word, phonetic, translation]
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

    def get_phonetic(self, word):
        req = requests.post('https://tophonetics.com/',
                            data={'text_to_transcribe': word})
        phon = self.phonetic_reg.search(req.content.decode())
        return phon and phon[1]

    @staticmethod
    def get_translation(word):
        translator = Translator()
        return translator.translate(word, src='english', dest='russian').text

    def hook(self, keyboard_event):
        if not keyboard_event.event_type != 'down':
            return
        if keyboard_event.name == ';':  # add from clipboard
            word = self.handle_clipboard()
            if word in self.written:
                return
            phonetic = '[' + (self.get_phonetic(word) or '') + ']'
            translation = self.get_translation(word)
            self.add(word, phonetic, translation)
            print('', phonetic, translation, sep='\t', end='✓✓\n')
            self.no_end = False
        elif keyboard_event.name == '.':
            word = self.handle_clipboard()
            if word in self.written:
                return
            translation = self.get_translation(word)
            print('\t', translation, end='✓\n')
            self.no_end = False
        elif keyboard_event.name == '/':  # go back
            self.cursor[-1] = str(int(self.cursor[-1]) - 1)

    def run(self):
        clip, uc = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD), 1
        rm_hook = keyboard.hook(self.hook)

        def callback(*_):
            nonlocal clip, uc
            if (v := clip.wait_for_text()) not in self.written:
                p = '\033[0;3' + ((uc and '6') or '4') + 'm'
                if self.no_end:
                    p = '\n' + p
                print(p, v, sep='', end=' ', flush=True)
                self.no_end = True
                uc = 1 - uc

        clip.connect('owner-change', callback)
        try:
            Gtk.main()
            rm_hook()
        except KeyboardInterrupt:
            self.save_data(self.cursor)
