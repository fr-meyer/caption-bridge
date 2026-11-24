"""Temporary-file software checks, not native Windows/runtime acceptance."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

DEFAULT_MODULE = Path(__file__).with_name("run_offline.py")
MODULE_PATH = Path(os.environ.get("CAPTION_SOURCE_READER_MODULE", str(DEFAULT_MODULE)))
SPEC = importlib.util.spec_from_file_location("source_reader_under_test", MODULE_PATH)
READER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READER)


class SourcePathTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.base = Path(self.scratch.name)
        self.root, self.outside = self.base / "root", self.base / "outside"
        (self.root / "app").mkdir(parents=True)
        self.outside.mkdir()
        (self.root / "app/example.py").write_bytes(b"print('public fixture')\n")
        (self.outside / "example.py").write_bytes(b"outside test bytes, never source")

    def alias_app(self, broken=False):
        (self.root / "app").rename(self.root / "original-app")
        try:
            (self.root / "app").symlink_to(
                self.base / "missing" if broken else self.outside, target_is_directory=True,
            )
        except OSError:
            self.skipTest("Temporary symlink unavailable; no privilege change requested")

    def assert_no_payload_read(self, expected, operation):
        with patch.object(Path, "read_bytes", side_effect=AssertionError("payload_read")) as paths, \
             patch.object(os, "fdopen", side_effect=AssertionError("payload_read")) as descriptors:
            with self.assertRaisesRegex(ValueError, expected):
                operation()
        paths.assert_not_called()
        descriptors.assert_not_called()

    def test_regular_and_deleted_source_values(self):
        self.assertEqual(READER.source_file_value(self.root, "app/example.py"),
                         b"file\0print('public fixture')\n")
        self.assertEqual(READER.source_file_value(self.root, "app/deleted.py"), b"missing")
        self.assertEqual(READER.source_file_value(self.root, "missing/child.py"), b"missing")

    def test_absolute_empty_and_parent_paths_rejected_before_reads(self):
        for name in [str(self.outside / "example.py"), "../outside/example.py", ""]:
            with self.subTest(name=name):
                self.assert_no_payload_read(
                    "source_path_outside_root", lambda: READER.source_file_value(self.root, name),
                )

    def test_ancestor_symlink_cannot_read_outside_root(self):
        self.alias_app()
        self.assert_no_payload_read(
            "source_ancestor_alias", lambda: READER.source_file_value(self.root, "app/example.py"),
        )

    def test_broken_ancestor_is_rejected_not_mislabeled_missing(self):
        self.alias_app(broken=True)
        self.assert_no_payload_read(
            "source_ancestor_alias", lambda: READER.source_file_value(self.root, "app/example.py"),
        )

    def test_nested_ancestor_symlink_cannot_read_outside_root(self):
        try:
            (self.root / "app/deep").symlink_to(self.outside, target_is_directory=True)
        except OSError:
            self.skipTest("Temporary symlink unavailable; no privilege change requested")
        self.assert_no_payload_read(
            "source_ancestor_alias",
            lambda: READER.source_file_value(self.root, "app/deep/example.py"),
        )

    def test_root_alias_rejected_before_reads(self):
        alias = self.base / "root-alias"
        try:
            alias.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest("Temporary symlink unavailable; no privilege change requested")
        self.assert_no_payload_read(
            "source_ancestor_alias", lambda: READER.source_file_value(alias, "app/example.py"),
        )

    def test_leaf_symlink_binds_only_link_text_not_target_bytes(self):
        leaf, target = self.root / "app/link.py", self.outside / "example.py"
        try:
            leaf.symlink_to(target)
        except OSError:
            self.skipTest("Temporary symlink unavailable; no privilege change requested")
        with patch.object(Path, "read_bytes", side_effect=AssertionError("payload_read")), \
             patch.object(os, "fdopen", side_effect=AssertionError("payload_read")):
            before = READER.source_file_value(self.root, "app/link.py")
            target.write_bytes(b"changed outside test bytes")
            self.assertEqual(READER.source_file_value(self.root, "app/link.py"), before)
        self.assertEqual(before, b"symlink\0" + os.fsencode(str(target)))

    def reparse_metadata(self, component):
        original = Path.lstat

        def lstat(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == component:
                return SimpleNamespace(st_mode=info.st_mode,
                                       st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
            return info

        return lstat

    def test_windows_reparse_root_ancestor_and_leaf_flags_fail_closed(self):
        # Model stat flags only. No native Windows/junction execution is claimed.
        for component in [self.root, self.root / "app", self.root / "app/example.py"]:
            with self.subTest(component=component.name), \
                 patch.object(Path, "lstat", self.reparse_metadata(component)):
                self.assert_no_payload_read(
                    "source_reparse_alias",
                    lambda: READER.source_file_value(self.root, "app/example.py"),
                )

    def test_windows_style_non_dir_fd_route_checks_components_before_read(self):
        with patch.object(os, "supports_dir_fd", set()):
            self.assertEqual(READER.source_file_value(self.root, "app/example.py"),
                             b"file\0print('public fixture')\n")
            with patch.object(Path, "lstat", self.reparse_metadata(self.root / "app")):
                self.assert_no_payload_read(
                    "source_reparse_alias",
                    lambda: READER.source_file_value(self.root, "app/example.py"),
                )

    def test_non_regular_leaf_rejected_without_open(self):
        (self.root / "app/directory.py").mkdir()
        self.assert_no_payload_read(
            "source_not_regular_file",
            lambda: READER.source_file_value(self.root, "app/directory.py"),
        )

    @unittest.skipUnless(os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW"),
                         "Descriptor-relative O_NOFOLLOW route unavailable")
    def test_posix_ancestor_swap_after_checks_still_cannot_read_target(self):
        original_open = os.open
        replaced = False

        def swap_then_open(path, *args, **kwargs):
            nonlocal replaced
            if Path(path) == self.root and not replaced:
                replaced = True
                self.alias_app()
            return original_open(path, *args, **kwargs)

        with patch.object(os, "open", swap_then_open), \
             patch.object(os, "supports_dir_fd", set(os.supports_dir_fd) | {swap_then_open}), \
             patch.object(os, "fdopen", side_effect=AssertionError("outside_payload_read")) as reads:
            with self.assertRaises(OSError):
                READER.source_file_value(self.root, "app/example.py")
        self.assertTrue(replaced)
        reads.assert_not_called()


@unittest.skipUnless(hasattr(READER, "software_source_identity"),
                     "Wired identity exists only in frozen integration; run private patched copy")
class WiredSourceIdentityTests(unittest.TestCase):
    setUp = SourcePathTests.setUp
    alias_app = SourcePathTests.alias_app
    assert_no_payload_read = SourcePathTests.assert_no_payload_read
    reparse_metadata = SourcePathTests.reparse_metadata

    def identity(self, names):
        def git(argv, **_kwargs):
            if "ls-files" in argv:
                stdout = b"\0".join(names) + b"\0"
            elif "rev-parse" in argv:
                stdout = b"a" * 40 + b"\n"
            else:
                stdout = b" M app/example.py\0"
            return subprocess.CompletedProcess(argv, 0, stdout=stdout)

        with patch.object(READER.subprocess, "run", git):
            return READER.software_source_identity(self.root)

    def test_wired_normal_and_missing_files_have_exact_existing_digest(self):
        names = [b"app/example.py", b"app/deleted.py"]
        values = {b"app/example.py": b"file\0print('public fixture')\n",
                  b"app/deleted.py": b"missing"}
        digest = hashlib.sha256()
        for name in sorted(names):
            digest.update(name + b"\0" + hashlib.sha256(values[name]).hexdigest().encode() + b"\n")
        result = self.identity(names)
        self.assertEqual(result["software_source_sha256"], digest.hexdigest())
        self.assertEqual(result["software_source_files"], 2)
        self.assertTrue(result["source_dirty"])
        self.assertEqual(result["source_head"], "a" * 40)
        (self.root / "app/example.py").write_bytes(b"changed public bytes")
        self.assertNotEqual(self.identity(names)["software_source_sha256"], digest.hexdigest())

    def test_wired_ancestor_symlink_fails_before_outside_read(self):
        self.alias_app()
        self.assert_no_payload_read("source_ancestor_alias", lambda: self.identity([b"app/example.py"]))

    def test_wired_windows_reparse_alias_fails_before_read(self):
        with patch.object(Path, "lstat", self.reparse_metadata(self.root / "app")):
            self.assert_no_payload_read("source_reparse_alias", lambda: self.identity([b"app/example.py"]))

    def test_wired_bundle_calls_safe_reader_for_each_source(self):
        with patch.object(READER, "source_file_value", wraps=READER.source_file_value) as reader:
            self.identity([b"app/example.py", b"app/deleted.py"])
        self.assertEqual([call.args[1] for call in reader.call_args_list],
                         ["app/deleted.py", "app/example.py"])
