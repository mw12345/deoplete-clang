import os
import re
import sys

from deoplete.sources.base import Base

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
from clang_data import ClangData
from helper import get_var
from helper import load_external_module

load_external_module('clang')
import clang.cindex as cl

from logging import getLogger
logger = getLogger(__name__)

# Profiler
from profiler import timeit
# PyVmMonitor_dir = '/Applications/PyVmMonitor.app/Contents/MacOS/public_api'
# sys.path.append(PyVmMonitor_dir)
# import pyvmmonitor
# @pyvmmonitor.profile_method()


class Source(Base):

    def __init__(self, vim):
        Base.__init__(self, vim)

        self.name = 'clang'
        self.mark = '[clang]'
        self.filetypes = ['c', 'cpp', 'objc', 'objcpp']
        self.rank = 500
        # TODO(zchee): not need "r'[a-zA-Z_]\w*::\w*'" in C language
        self.input_pattern = (r'[^. \t0-9]\.\w*|'
                              r'[^. \t0-9]->\w*|'
                              r'[a-zA-Z_]\w*::\w*')

        self.library_path = \
            get_var(self.vim, 'deoplete#sources#clang#libclang_path')
        self.clang_header = \
            os.path.abspath(get_var(self.vim, 'deoplete#sources#clang#clang_header'))
        self.completion_flags = \
            get_var(self.vim, "deoplete#sources#clang#flags")

        clang_complete_database = \
            get_var(self.vim, 'deoplete#sources#clang#clang_complete_database')
        if clang_complete_database != None:
            self.compilation_database = cl.CompilationDatabase.fromDirectory(
                    clang_complete_database)
        else:
            self.compilation_database = None

        cl.Config.set_library_file(str(self.library_path))
        cl.Config.set_compatibility_check(False)

        self.index = cl.Index.create()
        self.tu_data = dict()

        if get_var(self.vim, 'deoplete#debug'):
            log_file = get_var(self.vim, 'deoplete#sources#clang#debug#log_file')
            self.set_debug(os.path.expanduser(log_file))

    # @timeit(logger, 'simple', [0.00003000, 0.00015000])
    def get_complete_position(self, context):
        m = re.search(r'\w*$', context['input'])
        return m.start() if m else -1

    @timeit(logger, 'simple', [0.02000000, 0.05000000])
    def gather_candidates(self, context):
        # faster than self.vim.current.window.cursor[0]
        line = self.vim.eval("line('.')")
        col = (context['complete_position']+1)
        buf = self.vim.current.buffer
        # args = self.get_compile_params(buf.name)
        args = dict().fromkeys(['args', 'cwd'], [])
        args['args'] = self.completion_flags

        directory = buf.name.rsplit('/', 1)
        args['args'].append('-I'+directory[0])
        args['args'].append('-I'+os.path.join(directory[0], 'include'))

        complete = \
            self.get_completion(
                buf.name, line, col,
                self.get_current_buffer(buf),
                args['args']
            )

        try:
            # return [x for x in map(self.parse_candidates, complete.results)]
            return list(map(self.parse_candidates, complete.results))
        except Exception:
            return []

    # @timeit(logger, 'simple', [0.20000000, 0.30000000])
    def get_current_buffer(self, b):
        return [(b.name, "\n".join(b[:]) + "\n")]

    def get_compilation_database(self, fileName):
        last_query = dict().fromkeys(['args', 'cwd'], "")
        if self.compilation_database:
            cmds = cl.CompilationDatabase.getCompileCommands(filename)
            if cmds != None:
                cwd = cmds[0].directory
                args = []
                skip_next = 1 # Skip compiler invocation
                for arg in cmds[0].arguments:
                    if skip_next:
                        skip_next = 0;
                        continue
                    if arg == '-c':
                        continue
                    if arg == fileName or \
                        os.path.realpath(os.path.join(cwd, arg)) == fileName:
                        continue
                    if arg == '-o':
                        skip_next = 1;
                        continue
                    if arg.startswith('-I'):
                        includePath = arg[2:]
                        if not os.path.isabs(includePath):
                            includePath = os.path.normpath(os.path.join(cwd, includePath))
                        args.append('-I'+includePath)
                        continue
                    args.append(arg)
                last_query = { 'args': args, 'cwd': cwd }
        query = last_query
        return { 'args': list(query['args']), 'cwd': query['cwd']}

    def get_compile_params(self, fileName):
        params = self.get_compilation_database(os.path.abspath(fileName))
        args = params['args']
        headers = os.listdir(self.clang_header)
        directory = self.clang_header
        for path in headers:
            try:
                # files = os.listdir(path)
                # if len(files) >= 1:
                #     files = sorted(files)
                #     subDir = files[-1]
                # else:
                #     subDir = '.'
                # path = path + "/" + subDir + "/include/"
                arg = "-I" + path
                args.append("-I" + directory + path)

            except Exception:
                pass

        return { 'args' : args, 'cwd' : params['cwd'] }

    # @timeit(logger, 'simple', [0.00000200, 0.00000400])
    def get_translation_unit(self, fname, args, buf_data):
        # cl.TranslationUnit
        # PARSE_NONE = 0
        # PARSE_DETAILED_PROCESSING_RECORD = 1
        # PARSE_INCOMPLETE = 2
        # PARSE_PRECOMPILED_PREAMBLE = 4
        # PARSE_CACHE_COMPLETION_RESULTS = 8
        # PARSE_SKIP_FUNCTION_BODIES = 64
        # PARSE_INCLUDE_BRIEF_COMMENTS_IN_CODE_COMPLETION = 128
        flags = 4
        tu = self.index.parse(fname, args, buf_data, flags)

        self.tu_data[fname] = tu
        tu.reparse(buf_data)

        return tu

    # @timeit(logger, 'simple', [0.01500000, 0.02500000])
    def get_completion(self, fname, line, column, buf_data, args):
        if self.tu_data.get(fname) != None:
            tu = self.tu_data.get(fname)
        else:
            tu = self.get_translation_unit(fname, args, buf_data)

        return tu.codeComplete(fname, line, column, buf_data,
                               include_macros=False,
                               include_code_patterns=False,
                               include_brief_comments=False)

    # @timeit(logger, 'verbose', [0.00000500, 0.00002000])
    def parse_candidates(self, result):
        completion = dict().fromkeys(['word', 'abbr', 'kind', 'info'], "")
        completion['dup'] = 1
        _type = ""
        word = ""
        abbr = ""
        kind = ""
        info = ""

        for chunk in result.string:
            chunk_spelling = chunk.spelling

            if chunk.isKindInformative() or chunk.isKindPlaceHolder() or \
                    chunk_spelling == cl.CompletionChunk.Kind("Comma") or \
                    chunk_spelling == None:
                continue

            elif chunk.isKindResultType():
                _type += chunk_spelling
                continue

            elif chunk.isKindTypedText():
                abbr += chunk_spelling

            word += chunk_spelling
            info += chunk_spelling

        completion['word'] = word
        completion['abbr'] = abbr
        completion['info'] = info

        if result.cursorKind in ClangData.kinds:
            completion['kind'] = ' '.join(
                [ClangData.kinds[result.cursorKind], _type, kind])
        else:
            completion['kind'] = ' '.join(
                [str(result.cursorKind), _type, kind])

        return completion

    def set_debug(self, path):
        from logging import FileHandler, Formatter, DEBUG
        hdlr = FileHandler(os.path.expanduser(path))
        logger.addHandler(hdlr)
        datefmt = '%Y/%m/%d %H:%M:%S'
        fmt = Formatter(
            "%(levelname)s %(asctime)s %(message)s", datefmt=datefmt)
        hdlr.setFormatter(fmt)
        logger.setLevel(DEBUG)
