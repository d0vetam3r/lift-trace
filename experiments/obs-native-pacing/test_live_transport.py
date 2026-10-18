# SPDX-License-Identifier: MIT
"""Focused native-observer tests; no OBS, UI, real controller or production data.

Set LIFT_NATIVE_TEST_NODE to an existing Node executable for the child-process
integration checks. Windows shared-memory checks use fresh random channel names.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import secrets
import shutil
import struct
import sys
import threading
import time
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
from live_bridge import SharedPublisher, NativePipeline, pack_snapshot, validate_channel, PACKET_BYTES, SETTING_FIELDS
from server import Bridge

TEST_NODE = os.environ.get('LIFT_NATIVE_TEST_NODE') or shutil.which('node')

SETTINGS = dict(zip(SETTING_FIELDS, (270, 70, 401, 432, 290, 5/3, 7/9, 12, 1, 0, 300, 50, .38)))
SETTINGS.update(inputMode='native', side='1P', heightMode='auto', inputBodyEnabled=False,
                shortInputEnabled=True, showGuides=True, background='black')


def sample():
    now = time.time_ns() / 1_000_000
    return {'type': 'snapshot', 'epochMs': now, 'settings': dict(SETTINGS),
            'events': [{'lane': 1, 'direction': 0, 'start': now - 50.125, 'end': now - 10.25},
                       {'lane': 0, 'direction': -1, 'start': now - 20.5, 'end': None}]}


def packet(snapshot=None):
    return pack_snapshot(snapshot or sample(), session=17, sequence=23,
                         qpc_ns=123456789, epoch_ms=1800000000123.5)


def wait_for(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('Condition did not become true before the test deadline')


@contextmanager
def absent_data_directory():
    # These Bridge tests only read missing settings, never save them. A fresh
    # nonexistent path avoids creating/deleting any filesystem test payload.
    path = HERE / 'artifacts' / ('absent-test-data-' + secrets.token_hex(12))
    assert not path.exists()
    yield path
    assert not path.exists(), 'A read-only transport test unexpectedly wrote settings'


class FakeNative:
    supported = False
    def scan(self): return []
    def poll(self, _device): raise AssertionError('No physical controller polling is allowed in this test')


class FakeAutomation:
    def close(self): pass


class PacketTests(unittest.TestCase):
    def test_layout_raw_doubles_flags_and_bound(self):
        snapshot = sample()
        encoded = packet(snapshot)
        self.assertEqual(len(encoded), 98472)
        self.assertEqual(struct.unpack_from('<8sIIQQQdII', encoded),
                         (b'LIFTNV01', 1, 98472, 17, 23, 123456789, 1800000000123.5, 1, 2))
        self.assertEqual(struct.unpack_from('<13dII', encoded, 56),
                         tuple(SETTINGS[key] for key in SETTING_FIELDS) + (26, 0))
        for index, event in enumerate(snapshot['events']):
            self.assertEqual(struct.unpack_from('<iidd', encoded, 168 + index*24),
                             (event['lane'], event['direction'], event['start'],
                              -1 if event['end'] is None else event['end']))
        full = sample()
        full['events'] = [dict(snapshot['events'][0]) for _ in range(4096)]
        self.assertEqual(len(packet(full)), PACKET_BYTES)
        full['events'].append(dict(snapshot['events'][0]))
        with self.assertRaises(ValueError): packet(full)

    def test_malformed_and_nonfinite_input_is_rejected(self):
        for mutate in (
            lambda x: x.update(type='wrong'),
            lambda x: x.update(events={}),
            lambda x: x['settings'].update(noteHeight=float('nan')),
            lambda x: x['settings'].update(greenNumber=float('inf')),
            lambda x: x['events'][0].update(start=True),
            lambda x: x['events'][0].update(start=-1),
            lambda x: x['events'][0].update(lane=8),
            lambda x: x['events'][0].update(direction=2),
            lambda x: x['events'][0].update(end=1),
        ):
            value = sample()
            mutate(value)
            with self.assertRaises(ValueError): packet(value)
        for channel in ('', '../other', 'a/b', 'Global\\name', 'x'*49, '한글'):
            with self.assertRaises(ValueError): validate_channel(channel)
        self.assertEqual(validate_channel('safe_test-1'), 'safe_test-1')

    def test_existing_bridge_queue_overflow_resynchronizes_state(self):
        with absent_data_directory() as directory:
            bridge = Bridge(Path(directory), native=FakeNative(), automation=FakeAutomation())
            bridge.settings = dict(SETTINGS)
            bridge.latest = {'type': 'input', 'time': 1000, 'buttons': [True], 'axes': [0]}
            channel = bridge.subscribe()
            while not channel.empty(): channel.get_nowait()
            while not channel.full(): channel.put_nowait({'type': 'key', 'lane': 1, 'down': True, 'time': 1})
            bridge.broadcast({'type': 'status', 'marker': 'after-overflow'})
            restored = []
            while not channel.empty(): restored.append(channel.get_nowait())
            self.assertEqual([event['type'] for event in restored],
                             ['reset', 'status', 'settings', 'demo', 'input', 'status'])
            self.assertEqual(restored[2]['settings'], SETTINGS)
            self.assertEqual(restored[4], bridge.latest)
            self.assertEqual(restored[-1]['marker'], 'after-overflow')
            bridge.unsubscribe(channel)
            bridge.close()


@unittest.skipUnless(os.name == 'nt', 'Windows named memory and mutexes')
class WindowsPublisherTests(unittest.TestCase):
    def publisher(self):
        value = SharedPublisher('test_' + secrets.token_hex(12))
        self.addCleanup(value.close)
        return value

    def test_duplicate_producer_rejected_and_invalidation_clears(self):
        value = self.publisher()
        self.assertTrue(value.publish(sample()))
        before = ctypes.string_at(value._view, PACKET_BYTES)
        with self.assertRaises(RuntimeError): SharedPublisher(value.channel)
        self.assertEqual(ctypes.string_at(value._view, PACKET_BYTES), before)
        self.assertTrue(value.publish(sample()))
        self.assertEqual(struct.unpack_from('<II', ctypes.string_at(value._view, PACKET_BYTES), 48), (1, 2))
        value.invalidate()
        self.assertEqual(struct.unpack_from('<II', ctypes.string_at(value._view, PACKET_BYTES), 48), (0, 0))
        self.assertTrue(value.publish(sample()))

    def test_mutex_contention_skips_without_blocking_then_recovers(self):
        value = self.publisher()
        acquired, release = threading.Event(), threading.Event()
        failures = []
        def hold():
            try:
                self.assertEqual(value._api.WaitForSingleObject(value._mutex, 0), 0)
                acquired.set()
                release.wait(3)
                self.assertTrue(value._api.ReleaseMutex(value._mutex))
            except BaseException as exc:
                failures.append(exc)
                acquired.set()
        thread = threading.Thread(target=hold)
        thread.start()
        try:
            self.assertTrue(acquired.wait(1))
            self.assertFalse(failures)
            start = time.monotonic()
            self.assertFalse(value.publish(sample()))
            self.assertLess(time.monotonic() - start, .25)
        finally:
            release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(failures)
        self.assertTrue(value.publish(sample()))

    def test_abandoned_writer_lock_is_recovered_by_full_packet_replacement(self):
        value = self.publisher()
        results = []
        def abandon():
            results.append(value._api.WaitForSingleObject(value._mutex, 0))
            # The deliberately owned test thread exits without ReleaseMutex.
        thread = threading.Thread(target=abandon)
        thread.start()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [0])
        self.assertTrue(value.publish(sample()))
        self.assertEqual(ctypes.string_at(value._view, 8), b'LIFTNV01')

    def test_consumer_retained_mapping_does_not_block_new_producer_session(self):
        value = self.publisher()
        self.assertTrue(value.publish(sample()))
        old_session = value.session
        api = value._api
        api.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        api.OpenFileMappingW.restype = wintypes.HANDLE
        api.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        api.OpenMutexW.restype = wintypes.HANDLE
        retained_mutex = api.OpenMutexW(0x00100001, False,
                                       'Local\\LiftTraceNative-' + value.channel + '-mutex')
        self.assertTrue(retained_mutex)
        retained = api.OpenFileMappingW(0x0004, False, 'Local\\LiftTraceNative-' + value.channel)
        self.assertTrue(retained)
        view = api.MapViewOfFile(retained, 0x0004, 0, 0, PACKET_BYTES)
        self.assertTrue(view)
        try:
            value.close()
            self.assertEqual(struct.unpack_from('<II', ctypes.string_at(view, PACKET_BYTES), 48), (0, 0))
            replacement = SharedPublisher(value.channel)
            try:
                self.assertNotEqual(replacement.session, old_session)
                self.assertTrue(replacement.publish(sample()))
                data = ctypes.string_at(view, PACKET_BYTES)
                self.assertEqual(struct.unpack_from('<Q', data, 16)[0], replacement.session)
                self.assertEqual(struct.unpack_from('<II', data, 48), (1, 2))
                self.assertEqual(api.WaitForSingleObject(retained_mutex, 0), 0)
                self.assertTrue(api.ReleaseMutex(retained_mutex))
            finally:
                replacement.close()
        finally:
            api.UnmapViewOfFile(view)
            api.CloseHandle(retained)
            api.CloseHandle(retained_mutex)

    def test_stale_node_snapshot_is_rejected(self):
        value = self.publisher()
        stale = sample()
        stale['epochMs'] -= 2000
        with self.assertRaises(ValueError): value.publish(stale)


@unittest.skipUnless(TEST_NODE, 'Node is unavailable; install it or set LIFT_NATIVE_TEST_NODE')
class PipelineTests(unittest.TestCase):
    def test_publisher_exception_invalidates_and_removes_owned_workers(self):
        class FailingPublisher:
            def __init__(self, _channel):
                self.invalidations, self.closed = 0, False
            def publish(self, _snapshot): raise ValueError('Injected rejected snapshot')
            def invalidate(self): self.invalidations += 1
            def close(self): self.closed = True
        with absent_data_directory() as directory:
            bridge = Bridge(directory, native=FakeNative(), automation=FakeAutomation())
            bridge.settings = dict(SETTINGS)
            pipeline = NativePipeline(bridge, Path(TEST_NODE), 'test_' + secrets.token_hex(12),
                                      publisher_factory=FailingPublisher)
            try:
                pipeline.start()
                publisher = pipeline.publisher
                wait_for(lambda: pipeline.failure is not None)
                wait_for(lambda: pipeline.process.poll() is not None)
                self.assertEqual(pipeline.failure, 'node-snapshot-unavailable')
                self.assertGreater(publisher.invalidations, 0)
                self.assertEqual(len(bridge.clients), 0)
            finally:
                pipeline.close()
                bridge.close()
            self.assertTrue(publisher.closed)
            self.assertTrue(all(not thread.is_alive() for thread in pipeline._threads))

    def test_real_node_observer_and_eof_failure_leave_bridge_usable(self):
        class FakePublisher:
            def __init__(self, _channel):
                self.snapshots, self.invalidations, self.closed = [], 0, False
            def publish(self, snapshot):
                self.snapshots.append(copy.deepcopy(snapshot))
                return True
            def invalidate(self): self.invalidations += 1
            def close(self): self.closed = True
        with absent_data_directory() as directory:
            bridge = Bridge(Path(directory), native=FakeNative(), automation=FakeAutomation())
            bridge.settings = {**SETTINGS, 'inputMode': 'demo'}
            pipeline = NativePipeline(bridge, Path(TEST_NODE),
                                      'test_' + secrets.token_hex(12), publisher_factory=FakePublisher)
            try:
                pipeline.start()
                publisher = pipeline.publisher
                wait_for(lambda: publisher.snapshots)
                timestamp = time.time_ns() / 1_000_000
                bridge.broadcast({'type': 'key', 'lane': 7, 'down': True, 'time': timestamp})
                wait_for(lambda: any(any(event['lane'] == 7 and event['start'] == timestamp
                                         for event in snapshot['events']) for snapshot in publisher.snapshots))
                pipeline.process.stdin.close()  # Owned child's EOF, not a system input.
                wait_for(lambda: pipeline.failure is not None)
                self.assertGreater(publisher.invalidations, 0)
                independent = bridge.subscribe()
                try:
                    while not independent.empty(): independent.get_nowait()
                    bridge.broadcast({'type': 'reset'})
                    self.assertEqual(independent.get_nowait(), {'type': 'reset'})
                finally:
                    bridge.unsubscribe(independent)
            finally:
                pipeline.close()
                bridge.close()
            self.assertIsNotNone(pipeline.process.poll())
            self.assertTrue(publisher.closed)
            self.assertTrue(all(not thread.is_alive() for thread in pipeline._threads))
            self.assertEqual(len(bridge.clients), 0)


@unittest.skipUnless(os.environ.get('LIFT_NATIVE_TEST_GEOMETRY_DLL'),
                     'Set LIFT_NATIVE_TEST_GEOMETRY_DLL to test the independently compiled C protocol')
class CProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = ctypes.CDLL(os.environ['LIFT_NATIVE_TEST_GEOMETRY_DLL'])
        cls.library.lift_test_packet_valid.argtypes = [ctypes.c_void_p]
        cls.library.lift_test_packet_valid.restype = ctypes.c_int
        cls.library.lift_test_packet_fresh.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        cls.library.lift_test_packet_fresh.restype = ctypes.c_int
        cls.library.lift_test_animation.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_double)]
        cls.library.lift_test_animation.restype = ctypes.c_int

    def valid(self, encoded):
        buffer = ctypes.create_string_buffer(bytes(encoded), PACKET_BYTES)
        return bool(self.library.lift_test_packet_valid(buffer))

    def test_python_packet_matches_c_abi_and_closes_without_mutating_intervals(self):
        original = sample()
        encoded = packet(original)
        self.assertTrue(self.valid(encoded))
        closed = bytearray(encoded)
        struct.pack_into('<II', closed, 48, 0, 0)
        self.assertTrue(self.valid(closed))
        self.assertEqual(closed[168:], encoded[168:])

    def test_c_rejects_header_flags_nonfinite_and_invalid_event_intervals(self):
        for offset, format_, value in (
            (0, '<8s', b'BADMAGIC'), (8, '<I', 2), (12, '<I', PACKET_BYTES-1),
            (16, '<Q', 0), (24, '<Q', 0), (32, '<Q', 0), (40, '<d', float('nan')),
            (48, '<I', 2), (52, '<I', 4097), (56, '<d', float('inf')),
            (160, '<I', 64), (164, '<I', 1), (168, '<i', 8),
            (172, '<i', 1), (176, '<d', float('nan')), (184, '<d', 1),
        ):
            with self.subTest(offset=offset, value=value):
                altered = bytearray(packet())
                struct.pack_into(format_, altered, offset, value)
                self.assertFalse(self.valid(altered))
        duplicate = sample()
        duplicate['events'] = [dict(duplicate['events'][1]), dict(duplicate['events'][1])]
        self.assertFalse(self.valid(packet(duplicate)))

    def test_c_heartbeat_timeout_and_future_clock_boundaries(self):
        qpc = 10_000_000_000
        encoded = pack_snapshot(sample(), session=1, sequence=1, qpc_ns=qpc, epoch_ms=100000)
        buffer = ctypes.create_string_buffer(encoded, PACKET_BYTES)
        for offset, expected in ((0, True), (1_000_000_000, True), (1_000_000_001, False),
                                 (-250_000_000, True), (-250_000_001, False)):
            self.assertEqual(bool(self.library.lift_test_packet_fresh(buffer, qpc + offset)), expected)

    def test_c_frame_time_conversion_keeps_wall_epoch_and_rejects_far_clock(self):
        qpc, epoch = 10_000_000_000, 1800000000123.5
        encoded = pack_snapshot(sample(), session=1, sequence=1, qpc_ns=qpc, epoch_ms=epoch)
        buffer = ctypes.create_string_buffer(encoded, PACKET_BYTES)
        result = ctypes.c_double()
        for offset in (-16_666_667, 0, 16_666_667):
            self.assertTrue(self.library.lift_test_animation(buffer, qpc+offset, ctypes.byref(result)))
            self.assertAlmostEqual(result.value, epoch + offset/1_000_000, places=3)
        for offset in (-5_000_000_001, 5_000_000_001):
            self.assertFalse(self.library.lift_test_animation(buffer, qpc+offset, ctypes.byref(result)))


if __name__ == '__main__':
    unittest.main()
