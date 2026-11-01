"""Weekly selection, failed queries, process cleanup, and private publishing."""

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import quota
import install
publisher = quota


def result(used=25):
    return {'rateLimits': {
        'limitId': 'codex',
        'primary': {'usedPercent': 99, 'windowDurationMins': 300},
        'secondary': {'usedPercent': used, 'windowDurationMins': 10080},
    }}


class QuotaTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.path = self.directory / 'quota.json'

    def fake_codex(self, body):
        script = self.directory / 'codex'
        script.write_text('#!/usr/bin/python3\nimport json, os, sys, time\n' + body)
        script.chmod(0o700)
        return script

    def test_only_main_weekly_window_is_selected(self):
        self.assertEqual(quota.weekly_remaining(result()), 75)
        self.assertEqual(quota.weekly_remaining(result(100)), 0)
        self.assertEqual(quota.weekly_remaining(result(0)), 100)
        windows = result()['rateLimits']
        self.assertEqual(quota.weekly_remaining({'rateLimits': {'limitId': 'other'},
                                               'rateLimitsByLimitId': {'codex': windows}}), 75)
        del windows['secondary']
        self.assertIsNone(quota.weekly_remaining({'rateLimits': windows}))
        for value in (None, 'bad', True, float('nan'), float('inf')):
            self.assertIsNone(quota.weekly_remaining(result(value)))
        self.assertIsNone(quota.weekly_remaining({'rateLimits': {'limitId': 'other'}}))

    def test_query_reads_response_and_cleans_up_child(self):
        pidfile = self.directory / 'pid'
        script = self.fake_codex(
            f'open({str(pidfile)!r}, "w").write(str(os.getpid()))\n'
            'messages = [json.loads(sys.stdin.readline()) for _ in range(3)]\n'
            'assert [m["method"] for m in messages] == ["initialize", "initialized", "account/rateLimits/read"]\n'
            f'print(json.dumps({{"id": 2, "result": {result()!r}}}), flush=True)\n'
            'time.sleep(30)\n')
        self.assertEqual(quota.read_weekly(threading.Event(), codex_bin=script), 75)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pidfile.read_text()), 0)
        with patch.object(quota, 'account_identity', side_effect=[(1,), (2,)]):
            self.assertIsNone(quota.read_weekly(threading.Event(), codex_bin=script))

    def test_query_failure_timeout_and_cancellation_return_nothing(self):
        script = self.fake_codex('print(json.dumps({"id": 2, "error": {"message": "unavailable"}}), flush=True)\n')
        self.assertIsNone(quota.read_weekly(threading.Event(), codex_bin=script))
        pidfile = self.directory / 'pid'
        script = self.fake_codex(f'open({str(pidfile)!r}, "w").write(str(os.getpid()))\ntime.sleep(30)\n')
        self.assertIsNone(quota.read_weekly(threading.Event(), codex_bin=script, timeout=0.2))
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pidfile.read_text()), 0)
        stop = threading.Event()
        stop.set()
        with patch.object(quota.subprocess, 'Popen') as popen:
            self.assertIsNone(quota.read_weekly(stop))
            popen.assert_not_called()

    def test_success_then_failure_publishes_only_percentage_then_null(self):
        bus = Mock()
        write_state = quota.write_state_file
        with patch.object(publisher, 'write_state_file', side_effect=lambda data: write_state(data, self.path)):
            for value in (75, 0, None):
                publisher.publish(bus, value)
                expected = {'remaining_percent': value}
                self.assertEqual(json.loads(self.path.read_text()), expected)
                self.assertEqual(json.loads(bus.call_blocking.call_args.args[5][0]), expected)
                self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        original = self.path.read_bytes()
        with patch.object(quota.os, 'replace', side_effect=OSError('failed')):
            with self.assertRaises(OSError):
                quota.write_state_file('{"remaining_percent":10}', self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_startup_retries_end_on_success_or_after_one_minute(self):
        for readings, times, waits, timeouts in (
                ([75, None], [100, 100, 101, 160, 163], [59, 57], [2, 10]),
                ([None, 0, None], [100, 100, 101, 102, 103, 162, 165], [1, 59, 57], [2, 2, 10]),
                ([None, None, None], [100, 158, 160, 160, 170, 220, 230], [0, 50, 50], [2, 10, 10])):
            with self.subTest(readings=readings):
                stop = Mock()
                stop.is_set.side_effect = [False] * (2 * len(readings)) + [True]
                with patch.object(publisher.threading, 'Event', return_value=stop), \
                        patch.object(publisher.signal, 'signal'), \
                        patch.object(publisher.dbus, 'SessionBus'), \
                        patch.object(publisher, 'read_weekly', side_effect=readings) as read, \
                        patch.object(publisher, 'publish') as publish, \
                        patch.object(publisher.time, 'monotonic', side_effect=times):
                    publisher.main()
                self.assertEqual([call.args[1] for call in publish.call_args_list], [None, *readings, None])
                self.assertEqual([call.args[0] for call in stop.wait.call_args_list], waits)
                self.assertEqual([call.kwargs['timeout'] for call in read.call_args_list], timeouts)

    def test_install_and_uninstall_touch_only_application_registrations(self):
        root = self.directory / 'Applications/codex-quota'
        metadata = root / 'extensions' / install.UUID / 'metadata.json'
        metadata.parent.mkdir(parents=True)
        metadata.write_text('{"uuid":"codex-quota@wenbo-wei"}')
        untouched = self.directory / 'keep.txt'
        untouched.write_text('keep')
        with patch.object(install, 'ROOT', root), patch.object(install, 'USER_DIR', self.directory), \
                patch.object(install, 'run', return_value="['another@extension']") as run, \
                patch.object(install, 'print'), patch.object(sys, 'argv', ['install.py']):
            install.main()
            files = install.registration_files()
            self.assertTrue(all(path.is_file() and not path.is_symlink() for path in files))
            self.assertTrue(all(path.read_text() == content for path, content in files.items()))
            run.assert_any_call('gsettings', 'set', 'org.gnome.shell', 'enabled-extensions',
                                repr(['another@extension', install.UUID]))
            with patch.object(sys, 'argv', ['install.py', '--uninstall']):
                install.main()
            self.assertTrue(all(not path.exists() for path in files))
        self.assertEqual(untouched.read_text(), 'keep')
