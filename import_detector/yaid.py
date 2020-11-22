""" When we have
 _________________     _______________
| one.py:         |   | two.py:      |
| import two, sys |   | import os    |
| two.func()      |   | os.listdir() |
|_________________|   |______________|
one.py depends on two.py, sys
two.py depends on os
Let imagine it in @graphql
"""

import ast
import collections
import logging
import os
import typing
import inspect
import rich.logging
import pathlib

logging.basicConfig(level='DEBUG', format='%(message)s', datefmt='[%X]', handlers=[rich.logging.RichHandler()])


class Const:
    WITH_BODY = ast.Module, ast.ClassDef, ast.FunctionDef, ast.If
    SKIP = ast.Return, ast.Assign, ast.Expr, ast.Raise, ast.Nonlocal, ast.Global
    WITH_BODY_AND_ELSE = ast.For, ast.While


class YetAnotherImportDetector:
    def __init__(self, path_to_mod):
        self._root = pathlib.Path(path_to_mod).resolve()
        self._deque = collections.deque()
        self._passed = set()

    def detect(self):
        self._deque.append(self._root)

        while len(self._deque):
            path: typing.Union[str, pathlib.Path] = self._deque.pop()
            if path in self._passed:
                continue

            self._passed.add(path)
            if isinstance(path, str) and path.startswith('$'):  # builtin, pyx, ...
                continue
            if (mod := fetch_ast(path)) is None:
                continue
            for elem in fetch_imports(mod):
                if isinstance(elem, ast.Import) or elem.level == 0:
                    # import a, b, c.d.e
                    self._deque.extend(resolve_direct_source(elem))
                else:
                    # from a import b, c, d
                    # from . import a, b
                    # from ..... import a, b
                    # from ...a.b.c import d, e
                    self._deque.extend(resolve_related_source(path, elem))
        return self._passed


def fetch_ast(
        path, *,
        on_open_error='log',
        on_parse_error='log',
) -> typing.Optional[ast.Module]:
    try:
        if not isinstance(path, (str, bytes, os.PathLike)):
            raise FileNotFoundError
        with open(path) as prog:
            return ast.parse(prog.read())
    except (FileNotFoundError, PermissionError) as e:
        if on_open_error != 'log':
            raise e
        logging.warning(f'{path} cannot be opened')
    except (SyntaxError, UnicodeDecodeError) as e:
        if on_parse_error != 'log':
            raise e
        logging.warning(f'{path} cannot be parsed')


def fetch_imports(mod: ast.Module):
    deque = collections.deque()
    deque.append(mod)

    while len(deque):
        elem = deque.pop()

        if isinstance(elem, (ast.ImportFrom, ast.Import)):
            yield elem

        for group_name in ('body', 'orelse', 'finalbody', 'handlers'):
            if hasattr(elem, group_name):
                deque.extend(getattr(elem, group_name))


def resolve_direct_source(elem: typing.Union[ast.Import, ast.ImportFrom]):
    temp = f'from {elem.module} import ' if hasattr(elem, 'level') else 'import '
    for alias in elem.names:
        if alias.name == '*':
            return resolve_direct_source(ast.parse(f'import {elem.module}').body[0])
        assert alias.name not in ('exc', 'mod')
        assert alias.name not in locals()

        try:
            exec(temp + alias.name)
        except ValueError as exc:
            logging.warning(f'{alias.name} cannot be imported')
        except (ImportError, ModuleNotFoundError) as exc:  # platform specific libs
            logging.warning(f'{exc.name} cannot be imported')
        else:
            mod = inspect.getmodule(eval(alias.name))
            if mod is not None:
                yield getattr(mod, '__file__', '$' + mod.__name__)


def resolve_related_source(base_path, elem: ast.ImportFrom):
    work_dir = pathlib.Path(base_path).parent
    for _ in range(1, elem.level):
        work_dir = work_dir.parent
    for part in (elem.module or '').split('.'):
        work_dir /= part

    for alias in elem.names:
        fl_name = alias.name + '.py'
        if not (work_dir / fl_name).exists():
            fl_name = '__init__.py'
        yield (work_dir / fl_name).resolve()


if __name__ == '__main__':
    for n in sorted(map(str, YetAnotherImportDetector('../read_flow/flow.py').detect())):
        print(n)
