import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def _cipher_fernet(password: str):
    salt = int.from_bytes(password.encode(), byteorder='little') ^ 846546764546775454
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=str(salt).encode(), iterations=1000,
                     backend=default_backend()).derive(password.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plaintext: str, password: str):
    return _cipher_fernet(password).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str, password: str):
    return _cipher_fernet(password).decrypt(ciphertext.encode()).decode()


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
