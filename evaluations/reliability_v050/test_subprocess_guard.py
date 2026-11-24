"""Pure policy/mocked-constructor tests, not native Windows execution."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, sentinel

DEFAULT_MODULE = Path(__file__).with_name("run_offline.py")
MODULE_PATH = Path(os.environ.get("CAPTION_PROCESS_GUARD_MODULE", str(DEFAULT_MODULE)))
SPEC = importlib.util.spec_from_file_location("process_guard_under_test", MODULE_PATH)
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


class SubprocessGuardTests(unittest.TestCase):
    def setUp(self):
        self.constructor = Mock(return_value=sentinel.process)
        denied = patch.object(GUARD, "DENIED", [])
        denied.start()
        self.addCleanup(denied.stop)

    def permitted(self, program, *, windows):
        return GUARD.permitted_subprocess_argv([program], windows=windows)

    def test_existing_exact_names_and_paths_remain_approved(self):
        for windows, programs in (
            (False, ["git", "node", "node.exe", "pwsh", "/usr/local/bin/node", Path("node")]),
            (True, ["git", "node", "node.exe", "pwsh", r"C:\tools\node.exe"]),
        ):
            for program in programs:
                with self.subTest(windows=windows, program=str(program)):
                    self.assertTrue(self.permitted(program, windows=windows))

    def test_windows_filename_case_equivalents_are_approved_without_rewriting_path(self):
        for program in ["GIT", "Node", "NODE.EXE", "node.EXE", "PwSh",
                        r"C:\Program Files\nodejs\node.EXE", "C:/tools/NODE.ExE"]:
            with self.subTest(program=program):
                self.assertTrue(self.permitted(program, windows=True))
                # Exercise the wrapper with modeled Windows name semantics only.
                permitted = GUARD.permitted_subprocess_argv
                argv = [program, "--version"]
                with patch.object(GUARD, "permitted_subprocess_argv",
                                  lambda args: permitted(args, windows=True)):
                    self.assertIs(GUARD.guarded_subprocess_popen(self.constructor, argv),
                                  sentinel.process)
                self.assertIs(self.constructor.call_args.args[0], argv)
        self.assertEqual(GUARD.DENIED, [])

    def test_posix_case_and_backslash_paths_are_not_reinterpreted_as_windows(self):
        for program in ["GIT", "Node", "NODE.EXE", "node.EXE", "PwSh",
                        "/usr/local/bin/NODE", r"C:\tools\node.exe", r"tools\node"]:
            with self.subTest(program=program):
                self.assertFalse(self.permitted(program, windows=False))

    def test_pathext_does_not_add_suffixes_or_wrappers_to_existing_allowlist(self):
        for pathext in [".EXE;.CMD;.BAT;.COM", ".CMD;.EXE", ".PY;.PS1"]:
            with patch.dict(os.environ, {"PATHEXT": pathext}):
                for program in ["node.cmd", "NODE.CMD", "node.bat", "node.com", "node.ps1",
                                "node.py", "node.exe.cmd", "git.exe", "pwsh.exe"]:
                    for windows in [False, True]:
                        with self.subTest(pathext=pathext, program=program, windows=windows):
                            self.assertFalse(self.permitted(program, windows=windows))
                self.assertTrue(self.permitted("node", windows=True))
                self.assertTrue(self.permitted("node.EXE", windows=True))

    def test_wrong_program_and_wrong_path_leaf_are_rejected(self):
        for windows, programs in (
            (False, ["python", "sh", "bash", "cmd.exe", "/tmp/node/python", "/tmp/node.exe.sh"]),
            (True, ["python.exe", "cmd.exe", "powershell.exe", r"C:\tools\node\python.exe",
                    r"C:\tools\node.exe.cmd", r"C:\tools\node.exe\cmd.exe"]),
        ):
            for program in programs:
                with self.subTest(windows=windows, program=program):
                    self.assertFalse(self.permitted(program, windows=windows))

    def test_shell_strings_empty_and_non_path_argv_are_rejected(self):
        for argv in ["node --version", "node && other", (), [], {}, None, [None], [b"node"],
                     [42], [""], [object()]]:
            for windows in [False, True]:
                with self.subTest(argv_type=type(argv).__name__, windows=windows):
                    self.assertFalse(GUARD.permitted_subprocess_argv(argv, windows=windows))

    def test_shell_metacharacters_and_deceptive_program_suffixes_are_rejected(self):
        for program in ["node;other", "node&other", "node|other", "node>file", "node<file",
                        "node\nother", "node\rother", "node\0", '"node"', "node.exe ",
                        "node.exe.", "node.exe:other", "node --version",
                        "pwſh", "gıt", "gİt", "ＮＯＤＥ"]:
            for windows in [False, True]:
                with self.subTest(program=repr(program), windows=windows):
                    self.assertFalse(self.permitted(program, windows=windows))

    def test_host_default_uses_host_filename_semantics(self):
        for program in ["git", "GIT", "node.EXE", r"C:\tools\node.EXE", "/usr/bin/node"]:
            with self.subTest(program=program):
                self.assertEqual(GUARD.permitted_subprocess_argv([program]),
                                 self.permitted(program, windows=os.name == "nt"))

    def test_approved_constructor_receives_exact_argv_and_non_shell_options(self):
        argv = ("node", "-e", "const value = 'literal;not a shell';")
        options = {"shell": False, "executable": None, "stdout": subprocess.PIPE}
        result = GUARD.guarded_subprocess_popen(self.constructor, argv, **options)
        self.assertIs(result, sentinel.process)
        self.constructor.assert_called_once_with(argv, **options)
        self.assertIs(self.constructor.call_args.args[0], argv)
        self.assertEqual(GUARD.DENIED, [])

    def test_ordinary_positional_constructor_options_remain_unchanged(self):
        args = (-1, None, None, None, None, None, True, False)
        argv = ["git", "--version"]
        self.assertIs(GUARD.guarded_subprocess_popen(self.constructor, argv, *args), sentinel.process)
        self.constructor.assert_called_once_with(argv, *args)

    def test_unapproved_constructor_is_never_started(self):
        for argv in [["python"], ["node.exe.cmd"], "node --version", [], [None]]:
            with self.subTest(argv_type=type(argv).__name__):
                with self.assertRaisesRegex(AssertionError, "^offline_external_io_denied$"):
                    GUARD.guarded_subprocess_popen(self.constructor, argv)
        self.constructor.assert_not_called()
        self.assertEqual(GUARD.DENIED, ["unapproved_process"] * 5)

    def test_shell_and_executable_keyword_overrides_are_denied_before_constructor(self):
        for options in [{"shell": True}, {"executable": "python"}, {"executable": "node"}]:
            with self.subTest(option=next(iter(options))):
                with self.assertRaisesRegex(AssertionError, "^offline_external_io_denied$"):
                    GUARD.guarded_subprocess_popen(self.constructor, ["node"], **options)
        self.constructor.assert_not_called()
        self.assertEqual(GUARD.DENIED, ["unapproved_process"] * 3)

    def test_positional_shell_and_executable_overrides_are_denied_before_constructor(self):
        for args in [(-1, "python"), (-1, None, None, None, None, None, True, True)]:
            with self.subTest(positional_count=len(args)):
                with self.assertRaisesRegex(AssertionError, "^offline_external_io_denied$"):
                    GUARD.guarded_subprocess_popen(self.constructor, ["node"], *args)
        self.constructor.assert_not_called()
        self.assertEqual(GUARD.DENIED, ["unapproved_process"] * 2)
