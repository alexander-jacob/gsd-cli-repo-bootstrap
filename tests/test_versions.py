"""Offline GSD version and installation checks against isolated files."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gsd_cli.versions import VersionError, check_installation, format_result, parse_version


def install_gsd(config_dir, version='1.20.1'):
    bundle = config_dir / 'gsd-core'
    (bundle / 'workflows').mkdir(parents=True, exist_ok=True)
    (bundle / 'bin').mkdir(exist_ok=True)
    (bundle / 'VERSION').write_text(version + '\n')
    (bundle / 'workflows/update.md').write_text('fixture marker\n')
    (bundle / 'bin/gsd-tools.cjs').write_text('throw new Error("must never execute");\n')
    return bundle


class VersionTests(unittest.TestCase):
    def test_numeric_release_precedence(self):
        self.assertLess(parse_version('1.9.99'), parse_version('1.20.1'))
        self.assertLess(parse_version('1.20.1'), parse_version('1.20.2'))
        self.assertLess(parse_version('1.99.99'), parse_version('2.0.0'))
        self.assertEqual(parse_version('1.20.1+build.001'), parse_version('1.20.1+other'))

    def test_semver_prerelease_precedence(self):
        order = ['1.0.0-alpha', '1.0.0-alpha.1', '1.0.0-alpha.beta', '1.0.0-beta',
                 '1.0.0-beta.2', '1.0.0-beta.11', '1.0.0-rc.1', '1.0.0']
        for earlier, later in zip(order, order[1:]):
            with self.subTest(earlier=earlier):
                self.assertLess(parse_version(earlier), parse_version(later))
        self.assertLess(parse_version('1.20.1-rc.2'), parse_version('1.20.1'))
        self.assertGreater(parse_version('1.21.0-rc.1'), parse_version('1.20.1'))

    def test_invalid_semver_rejected(self):
        for value in ('', 'v1.20.1', '1.20', '01.20.1', '1.020.1', '1.20.01',
                      '1.20.1-01', '1.20.1-a..b', '1.20.1+', '1.20.1-rc_1',
                      '1.20.1 trailing', '1.20.1\n', None, True, 1201):
            with self.subTest(value=value), self.assertRaises(VersionError):
                parse_version(value)


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.project = self.base / 'project'
        self.project.mkdir()
        self.home = self.base / 'home'
        self.home.mkdir()

    def check(self, runtime='codex', minimum='1.20.1', env=None):
        return check_installation(self.project, runtime, minimum, env=env or {}, home=self.home)

    def test_equal_newer_older_and_prerelease(self):
        for version, ok in [('1.20.1', True), ('1.21.0', True), ('1.18.0', False),
                            ('1.20.1-rc.1', False), ('1.20.1+build', True)]:
            with self.subTest(version=version):
                bundle = install_gsd(self.home / '.codex', version)
                result = self.check()
                self.assertEqual(result.ok, ok)
                self.assertEqual(result.installed, version)
                report = format_result(result)
                for item in ('codex', version, '1.20.1', str(bundle), 'PASS' if ok else 'FAIL'):
                    self.assertIn(item, report)

    def test_missing_runtime_never_borrows_other_runtime(self):
        install_gsd(self.home / '.claude', '9.0.0')
        result = self.check()
        self.assertFalse(result.ok)
        self.assertEqual(result.directory, self.home / '.codex/gsd-core')
        self.assertIsNone(result.installed)

    def test_local_installation_over_global_even_when_old(self):
        install_gsd(self.home / '.codex', '9.0.0')
        local = install_gsd(self.project / '.codex', '1.18.0')
        result = self.check()
        self.assertFalse(result.ok)
        self.assertEqual(result.directory, local)

    def test_explicit_override_wins_and_invalid_override_cannot_fall_back(self):
        install_gsd(self.home / '.codex', '9.0.0')
        install_gsd(self.project / '.codex', '9.0.0')
        bundle = install_gsd(self.base / 'override', '1.18.0')
        result = self.check(env={'CODEX_HOME': str(bundle.parent)})
        self.assertFalse(result.ok)
        self.assertEqual(result.directory, bundle)
        result = self.check(env={'CODEX_HOME': str(self.base / 'missing')})
        self.assertFalse(result.ok)
        self.assertEqual(result.directory, self.base / 'missing/gsd-core')

    def test_relative_and_home_overrides_are_runtime_specific(self):
        relative = install_gsd(self.project / 'relative')
        other = install_gsd(self.home / 'other', '1.18.0')
        result = self.check(env={'CODEX_HOME': 'relative', 'CLAUDE_CONFIG_DIR': str(other.parent)})
        self.assertTrue(result.ok)
        self.assertEqual(result.directory, relative)
        result = self.check('claude', env={'CLAUDE_CONFIG_DIR': '~/other', 'CODEX_HOME': 'relative'})
        self.assertFalse(result.ok)
        self.assertEqual(result.directory, other)

    def test_incomplete_local_installation_cannot_borrow_global_version(self):
        install_gsd(self.home / '.codex', '9.0.0')
        bundle = install_gsd(self.project / '.codex')
        for missing in ('VERSION', 'workflows/update.md', 'bin/gsd-tools.cjs'):
            install_gsd(self.project / '.codex')
            (bundle / missing).unlink()
            result = self.check()
            self.assertFalse(result.ok)
            self.assertEqual(result.directory, bundle)
            self.assertIn(missing, result.message)

    def test_broken_local_symlink_is_not_ignored(self):
        install_gsd(self.home / '.codex', '9.0.0')
        (self.project / '.codex').mkdir()
        (self.project / '.codex/gsd-core').symlink_to(self.base / 'absent', target_is_directory=True)
        result = self.check()
        self.assertFalse(result.ok)
        self.assertEqual(result.directory, self.project / '.codex/gsd-core')

    def test_malformed_oversized_and_non_utf8_version_block(self):
        bundle = install_gsd(self.home / '.codex')
        for raw in (b'unknown', b'1.20', b'1.20.1 ' + b' ' * 5000, b'\xff'):
            with self.subTest(raw=raw[:20]):
                (bundle / 'VERSION').write_bytes(raw)
                result = self.check()
                self.assertFalse(result.ok)
                self.assertIn('VERSION', result.message)

    def test_version_read_failure_is_diagnostic(self):
        install_gsd(self.home / '.codex')
        # A real permission error is platform/uid dependent; emulate only open.
        with mock.patch('gsd_cli.versions.os.open', side_effect=PermissionError('permission denied')):
            result = self.check()
        self.assertFalse(result.ok)
        self.assertIn('permission denied', result.message)

    def test_fifo_version_does_not_block(self):
        bundle = install_gsd(self.home / '.codex')
        (bundle / 'VERSION').unlink()
        os.mkfifo(bundle / 'VERSION')
        self.assertFalse(self.check().ok)

    def test_non_gsd_runtime_and_invalid_minimum_are_errors(self):
        with self.assertRaises(VersionError):
            self.check('opencode')
        with self.assertRaises(VersionError):
            self.check(minimum='1.2')
