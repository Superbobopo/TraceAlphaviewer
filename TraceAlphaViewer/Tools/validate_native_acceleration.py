"""Verifie le repli Python et l'integrite du lot compile avant tout import."""
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_acceleration as native


class NativeAccelerationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.base = self.root / 'bin/python-acceleration'
        self.build_id = 'a' * 64
        self.directory = self.base / self.build_id
        entries = {}
        for name in native.MODULES:
            relative = Path(*name.split('.'))
            source = self.root / relative.with_suffix('.py')
            binary = self.directory / relative.with_suffix(native.interpreter_tag()['extension'])
            source.parent.mkdir(parents=True, exist_ok=True)
            binary.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(name, encoding='utf-8')
            binary.write_bytes(name.encode('ascii'))
            entries[name] = {'source_sha256': native.file_digest(source),
                             'binary_sha256': native.file_digest(binary)}
        self.manifest = {'version': 1, 'build_id': self.build_id,
                         'interpreter': native.interpreter_tag(),
                         'compiler': {'cython': native.CYTHON_VERSION, 'zig': native.ZIG_VERSION,
                                      'directives': native.DIRECTIVES}, 'modules': entries}
        self.write_manifest()
        (self.base / 'active.json').write_text(json.dumps({'build_id': self.build_id}))
        native.acceleration_status.cache_clear()
        self.addCleanup(native.acceleration_status.cache_clear)

    def write_manifest(self):
        (self.directory / 'manifest.json').write_text(json.dumps(self.manifest))

    def test_valid_and_packaging(self):
        self.assertEqual(native.inspect_build(self.root)['mode'], 'native')
        binaries, data = native.bundled_files(self.root)
        self.assertEqual(len(binaries), len(native.MODULES))
        self.assertEqual(len(data), 2)

    def test_changed_source_and_frozen_bundle(self):
        (self.root / 'Models/state.py').write_text('change')
        self.assertEqual(native.inspect_build(self.root)['mode'], 'python')
        paths = ['source']
        with patch.dict(os.environ, TRACE_ALPHA_ACCELERATION='auto'):
            native.enable_package('Models', paths, self.root)
        self.assertEqual(paths, ['source'])
        self.assertEqual(native.inspect_build(self.root, verify_sources=False)['mode'], 'native')
        with self.assertRaises(RuntimeError):
            native.bundled_files(self.root)

    def test_corrupt_binary(self):
        (self.directory / Path('Models/state').with_suffix(native.interpreter_tag()['extension'])).write_bytes(b'changed')
        self.assertEqual(native.inspect_build(self.root)['mode'], 'python')

    def test_incompatible_or_partial_manifest(self):
        for key, value in [('interpreter', {}), ('compiler', {}), ('modules', {}),
                           ('build_id', 'b' * 64), ('version', 0)]:
            with self.subTest(key=key):
                original = self.manifest[key]
                self.manifest[key] = value
                self.write_manifest()
                self.assertEqual(native.inspect_build(self.root)['mode'], 'python')
                self.manifest[key] = original

    def test_missing_and_malformed_pointer(self):
        pointer = self.base / 'active.json'
        for content in ('{', '[]', 'null', '{"build_id":"../../elsewhere"}'):
            pointer.write_text(content)
            self.assertEqual(native.inspect_build(self.root)['mode'], 'python')
        pointer.unlink()
        self.assertEqual(native.bundled_files(self.root), ([], []))

    def test_malformed_manifest(self):
        for value in (None, [], {'modules': []}):
            (self.directory / 'manifest.json').write_text(json.dumps(value))
            self.assertEqual(native.inspect_build(self.root)['mode'], 'python')

    def test_explicit_python_and_package_path(self):
        with patch.dict(os.environ, TRACE_ALPHA_ACCELERATION='python'):
            paths = ['source']
            native.enable_package('Models', paths, self.root)
            self.assertEqual(paths, ['source'])
        native.acceleration_status.cache_clear()
        with patch.dict(os.environ, TRACE_ALPHA_ACCELERATION='auto'):
            paths = ['source']
            native.enable_package('Models', paths, self.root)
            native.enable_package('Models', paths, self.root)
            self.assertEqual(paths, [str(self.directory / 'Models'), 'source'])


if __name__ == '__main__':
    unittest.main()
