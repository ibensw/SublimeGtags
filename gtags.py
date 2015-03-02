#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import platform
import pprint
import re
import shlex
import subprocess
import unittest
import sublime

PP = pprint.PrettyPrinter(indent=4)

TAGS_RE = re.compile(
    '(?P<symbol>[^\s]+)\s+'
    '(?P<linenum>[^\s]+)\s+'
    '(?P<path>[^\s]+)\s+'
    '(?P<signature>.*)'
)

ENV_PATH = os.environ['PATH']
IS_WINDOWS = platform.system() == 'Windows'


def find_tags_root(current, previous=None):
    current = os.path.normpath(current)
    if not os.path.isdir(current):
        return None

    parent = os.path.dirname(current)
    if parent == previous:
        return None

    if 'GTAGS' in os.listdir(current):
        return current

    return find_tags_root(parent, current)


class TagSubprocess(object):
    def __init__(self, **kwargs):
        self.default_kwargs = kwargs
        if IS_WINDOWS:
            self.default_kwargs['shell'] = True

    def create(self, command, **kwargs):
        final_kwargs = self.default_kwargs
        final_kwargs.update(kwargs)
        if int(sublime.version()) >= 3000:
            if isinstance(command,str):
                command = shlex.split(command)
        else:
            if isinstance(command, basestring):
                command = shlex.split(command.encode('utf-8'))

        return subprocess.Popen(command, **final_kwargs)

    def stdout(self, command, **kwargs):
        process = self.create(command, stdout=subprocess.PIPE, **kwargs)
        return process.communicate()[0]

    def call(self, command, **kwargs):
        process = self.create(command, stderr=subprocess.PIPE, **kwargs)
        _, stderr = process.communicate()
        return process.returncode, stderr


class TagFile(object):
    def _expand_path(self, path):
        path = os.path.expandvars(os.path.expanduser(path))
        if IS_WINDOWS:
            path = path.encode('utf-8')
        return path

    def __init__(self, root_dir=None, extra_paths=[]):
        self.__env = {'PATH': ENV_PATH}
        self.__root = root_dir

        if root_dir is not None:
            self.__env['GTAGSROOT'] = self._expand_path(root_dir)

        if extra_paths:
            self.__env['GTAGSLIBPATH'] = os.pathsep.join(
                map(self._expand_path, extra_paths))

        self.subprocess = TagSubprocess(env=self.__env)

    def start_with(self, prefix):
        if int(sublime.version()) >= 3000:
            return self.subprocess.stdout('global -c %s' % prefix).decode("utf-8").splitlines()
        else:
            return self.subprocess.stdout('global -c %s' % prefix).splitlines()

    def _match(self, pattern, options):
        if int(sublime.version()) >= 3000:
            lines = self.subprocess.stdout(
            'global %s %s' % (options, pattern)).decode("utf-8").splitlines()
        else:
            lines = self.subprocess.stdout(
            'global %s %s' % (options, pattern)).splitlines()
        

        matches = []
        for search_obj in (t for t in (TAGS_RE.search(l) for l in lines) if t):
            matches.append(search_obj.groupdict())
        return matches

    def match(self, pattern, reference=False):
        return self._match(pattern, '-ax' + ('r' if reference else ''))

    def rebuild(self):
        retcode, stderr = self.subprocess.call('gtags -v', cwd=self.__root)
        success = retcode == 0
        if not success:
            print(stderr)
        return success

    def open_files_symbols(self):
        files=" ".join(['"'+x.file_name()+'"' for x in sublime.active_window().views() if os.path.isfile(x.file_name())])

        out=self.subprocess.stdout('global -q -f %s' % files)
        if int(sublime.version()) >= 3000:
            out = out.decode("utf-8")
        return [line.split(" ",2)[0] for line in out.splitlines()]

    def _find_includes(self, filename):
        includes = set([])
        if not os.path.isfile(filename):
            return includes
        with open(filename, 'r') as fp:
            for line in fp:
                line = line.lstrip();
                if line.startswith("#include"):
                    quoted = re.search('^\s*#include\s+"(.*)"', line)
                    if quoted:
                        includes.add(quoted.group(1));
        return includes

    def _makefullpath(self, basepaths, filename):
        for path in basepaths:
            if os.path.isfile(path+"/"+filename):
                return path+"/"+filename
        return None

    def _find_all_includes(self, basepaths, filename):
        todo=set([filename])
        done=set([])

        while len(todo) > 0:
            progress = todo.pop()
            done.add(progress)
            includes = self._find_includes(progress)
            for i in includes:
                j=self._makefullpath(basepaths,i)
                if j and j not in todo and j not in done:
                    todo.add(j)
        return done

    def current_include_path(self, filename):
        basepaths=[]
        if not sublime.active_window().project_data():
            basepaths.append(os.path.dirname(filename))
        else:
            projectpath = os.path.dirname(sublime.active_window().project_file_name())
            for folder in sublime.active_window().project_data()['folders']:
                basepaths.append(os.path.normpath(os.path.join(projectpath, folder['path'])))
        files = self._find_all_includes(basepaths, filename)
        out=self.subprocess.stdout("global -f '%s'" % "' '".join(files))
        if int(sublime.version()) >= 3000:
            out = out.decode("utf-8")
        return [line.split(" ",2)[0] for line in out.splitlines()]

class GTagsTest(unittest.TestCase):
    def test_start_with(self):
        f = TagFile('$HOME/repos/work/val/e4/proto1/')
        assert len(f.start_with("Exp_Set")) == 4

    def test_match(pattern):
        f = TagFile('$HOME/repos/work/val/e4/proto1/')
        matches = f.match("ExpAddData")
        assert len(matches) == 4
        assert matches[0]["path"] == "/Users/tabi/Dropbox/repos/work/val/e4/proto1/include/ExpData.h"
        assert matches[0]["linenum"] == '1463'

    def test_start_with2(self):
        f = TagFile()
        assert len(f.start_with("Exp_Set")) == 0

    def test_reference(self):
        f = TagFile('$HOME/repos/work/val/e4/proto1/')
        refs = f.match("Exp_IsSkipProgress", reference=True)
        assert len(refs) == 22
        assert refs[0]["path"] == "/Users/tabi/Dropbox/repos/work/val/e4/proto1/include/ExpPrivate.h"
        assert refs[0]["linenum"] == '1270'

    def test_extra_paths(self):
        f = TagFile("$HOME/tmp/sample", ["$HOME/repos/work/val/e4/proto1/", "~/pkg/llvm-trunk/tools/clang/"])
        matches = f.match("InitHeaderSearch")
        assert len(matches) == 1
        assert matches[0]["path"] == "/Users/tabi/pkg/llvm-trunk/tools/clang/lib/Frontend/InitHeaderSearch.cpp"
        assert matches[0]["linenum"] == '44'


if __name__ == '__main__':
    unittest.main()
