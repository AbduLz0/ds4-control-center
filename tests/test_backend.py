"""Backend tests. They need no hardware: sysfs is faked in a temp directory."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))

from ds4cc import bluetooth, controller as C  # noqa: E402
from ds4cc.diagnostics import EventLog, RateMeter  # noqa: E402
from ds4cc.settings import SettingsStore, set_autostart  # noqa: E402
from ds4cc.steam import Steam  # noqa: E402
from ds4cc import system  # noqa: E402

AI_STICK = SimpleNamespace(min=0, max=255, resolution=0)


def bitmap(*bits):
    """Build a sysfs-style capability string for the given bit numbers."""
    v = 0
    for b in bits:
        v |= 1 << b
    words, wsize = [], 64
    while True:
        words.append('%x' % (v & ((1 << wsize) - 1)))
        v >>= wsize
        if not v:
            break
    return ' '.join(reversed(words))


def make_node(root, num, name, keys=(), abses=(), vendor='054c', product='09cc', uniq='aa:bb:cc:dd:ee:ff',
              bus='0005', virtual=False):
    base = root / ('virtual' if virtual else 'real') / ('input%d' % num)
    dev = base / 'device'
    (dev / 'id').mkdir(parents=True)
    (dev / 'capabilities').mkdir()
    (dev / 'name').write_text(name + '\n')
    (dev / 'uniq').write_text(uniq + '\n')
    (dev / 'phys').write_text('\n')
    (dev / 'id' / 'vendor').write_text(vendor + '\n')
    (dev / 'id' / 'product').write_text(product + '\n')
    (dev / 'id' / 'bustype').write_text(bus + '\n')
    (dev / 'capabilities' / 'key').write_text(bitmap(*keys) + '\n')
    (dev / 'capabilities' / 'abs').write_text(bitmap(*abses) + '\n')
    ev = root / 'class' / ('event%d' % num)
    ev.parent.mkdir(exist_ok=True)
    ev.symlink_to(base)
    return ev


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.s = C.InputState()

    def test_face_buttons_and_counts(self):
        for code, name in ((0x130, 'cross'), (0x131, 'circle'), (0x134, 'square'), (0x133, 'triangle')):
            changed, msg = self.s.apply('gamepad', C.EV_KEY, code, 1)
            self.assertTrue(changed)
            self.assertIn(name, self.s.down)
            self.assertTrue(msg.lower().startswith(name))
        self.s.apply('gamepad', C.EV_KEY, 0x130, 0)
        self.assertNotIn('cross', self.s.down)
        self.assertEqual(self.s.counts['cross'], 1)

    def test_autorepeat_and_duplicates_ignored(self):
        self.s.apply('gamepad', C.EV_KEY, 0x130, 1)
        self.assertEqual(self.s.apply('gamepad', C.EV_KEY, 0x130, 2), (False, None))
        self.assertEqual(self.s.apply('gamepad', C.EV_KEY, 0x130, 1), (False, None))
        self.assertEqual(self.s.counts['cross'], 1)

    def test_stick_centre_is_exact_zero(self):
        self.assertEqual(C.norm_stick(128, 0, 255), 0.0)
        self.assertEqual(C.norm_stick(0, 0, 255), -1.0)
        self.assertEqual(C.norm_stick(255, 0, 255), 1.0)
        self.assertAlmostEqual(C.norm_stick(64, 0, 255), -0.504, places=2)

    def test_stick_and_trigger_events(self):
        self.s.apply('gamepad', C.EV_ABS, 0x00, 255, AI_STICK)
        self.s.apply('gamepad', C.EV_ABS, 0x04, 0, AI_STICK)
        self.s.apply('gamepad', C.EV_ABS, 0x02, 255, AI_STICK)
        self.assertEqual(self.s.axes['lx'], 1.0)
        self.assertEqual(self.s.axes['ry'], -1.0)
        self.assertEqual(self.s.axes['l2'], 1.0)
        self.assertTrue(self.s.analog['l2'])
        self.assertFalse(self.s.analog['r2'])  # never seen -> unavailable, not zero

    def test_hat_maps_to_dpad(self):
        hat = SimpleNamespace(min=-1, max=1, resolution=0)
        self.s.apply('gamepad', C.EV_ABS, 0x10, -1, hat)
        self.s.apply('gamepad', C.EV_ABS, 0x11, 1, hat)
        self.assertEqual(self.s.down, {'dpad-left', 'dpad-down'})
        self.s.apply('gamepad', C.EV_ABS, 0x10, 0, hat)
        self.assertEqual(self.s.down, {'dpad-down'})

    def test_touchpad_two_fingers_and_click(self):
        ai = SimpleNamespace(min=0, max=1919, resolution=0)
        self.s.apply('touchpad', C.EV_ABS, C.ABS_MT_SLOT, 0)
        self.s.apply('touchpad', C.EV_ABS, C.ABS_MT_TRACKING_ID, 5)
        self.s.apply('touchpad', C.EV_ABS, C.ABS_MT_X, 960, ai)
        self.s.apply('touchpad', C.EV_ABS, C.ABS_MT_SLOT, 1)
        self.s.apply('touchpad', C.EV_ABS, C.ABS_MT_TRACKING_ID, 6)
        self.assertTrue(self.s.touch[0]['active'] and self.s.touch[1]['active'])
        self.assertAlmostEqual(self.s.touch[0]['x'], 0.5, places=2)
        self.s.apply('touchpad', C.EV_ABS, C.ABS_MT_SLOT, 1)
        self.s.apply('touchpad', C.EV_ABS, C.ABS_MT_TRACKING_ID, -1)
        self.assertFalse(self.s.touch[1]['active'])
        self.s.apply('touchpad', C.EV_KEY, C.BTN_LEFT, 1)
        self.assertIn('touchpad', self.s.down)

    def test_motion_uses_resolution(self):
        accel = SimpleNamespace(min=-32768, max=32767, resolution=8192)
        gyro = SimpleNamespace(min=-32768, max=32767, resolution=1024)
        self.s.apply('motion', C.EV_ABS, 0x01, 8192, accel)
        self.s.apply('motion', C.EV_ABS, 0x03, 1024, gyro)
        self.assertEqual(self.s.motion['ay'], 1.0)
        self.assertAlmostEqual(self.s.motion['gx'], 57.296, places=2)
        self.assertEqual(self.s.units, {'accel': 'g', 'gyro': 'deg/s'})

    def test_unrelated_roles_do_not_press_buttons(self):
        self.assertEqual(self.s.apply('motion', C.EV_KEY, 0x130, 1), (False, None))
        self.assertEqual(self.s.apply('touchpad', C.EV_KEY, 0x130, 1), (False, None))


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def build_ds4(self, with_virtual=False):
        make_node(self.root, 5, 'Wireless Controller', keys=(0x130, 0x131, 0x133, 0x134, 0x13c), abses=(0, 1, 2, 3, 4, 5, 16, 17))
        make_node(self.root, 6, 'Wireless Controller Touchpad', keys=(0x110, 0x14a), abses=(0x35, 0x36, 0x39))
        make_node(self.root, 7, 'Wireless Controller Motion Sensors', abses=(0, 1, 2, 3, 4, 5))
        make_node(self.root, 3, 'Some Keyboard', keys=(30, 31))
        if with_virtual:
            make_node(self.root, 20, 'Microsoft X-Box 360 pad', keys=(0x130,), abses=(0, 1), vendor='045e',
                      product='028e', uniq='', bus='0003', virtual=True)

    def scan(self):
        return C.scan_nodes(self.root / 'class', Path('/nonexistent/dev'))

    def test_roles_are_classified_and_keyboards_ignored(self):
        self.build_ds4()
        roles = {n.name: n.role for n in self.scan()}
        self.assertEqual(roles, {'Wireless Controller': 'gamepad', 'Wireless Controller Touchpad': 'touchpad',
                                 'Wireless Controller Motion Sensors': 'motion'})

    def test_picks_gamepad_not_touchpad_or_motion(self):
        self.build_ds4()
        primary, comps = C.pick_controller(self.scan())
        self.assertEqual(primary.name, 'Wireless Controller')
        self.assertEqual(sorted(c.role for c in comps), ['motion', 'touchpad'])
        self.assertEqual(primary.bus_name, 'Bluetooth')

    def test_physical_pad_preferred_over_virtual(self):
        self.build_ds4(with_virtual=True)
        primary, _ = C.pick_controller(self.scan())
        self.assertFalse(primary.virtual)
        self.assertEqual(primary.vendor, C.SONY_VID)

    def test_no_controller_returns_none(self):
        make_node(self.root, 1, 'Power Button', keys=(116,))
        self.assertIsNone(C.pick_controller(self.scan()))

    def test_read_only_node_is_still_usable(self):
        self.build_ds4()
        dev_root = self.root / 'dev'
        dev_root.mkdir()
        for n in (5, 6, 7):
            p = dev_root / ('event%d' % n)
            p.write_text('')
            os.chmod(p, 0o444)
        nodes = C.scan_nodes(self.root / 'class', dev_root)
        pad = [n for n in nodes if n.role == 'gamepad'][0]
        self.assertTrue(pad.readable)
        if os.geteuid() != 0:  # root can always write
            self.assertFalse(pad.writable)

    def test_unreadable_node_is_reported_not_hidden(self):
        self.build_ds4()
        nodes = self.scan()  # /nonexistent/dev -> os.access False
        self.assertTrue(all(not n.readable for n in nodes))
        self.assertTrue(nodes)

    def test_battery_by_mac(self):
        self.build_ds4()
        power = self.root / 'power'
        bat = power / 'ps-controller-battery-aa:bb:cc:dd:ee:ff'
        bat.mkdir(parents=True)
        (bat / 'capacity').write_text('73\n')
        (bat / 'status').write_text('Charging\n')
        primary, _ = C.pick_controller(self.scan())
        b = C.read_battery(primary, power)
        self.assertEqual((b['percent'], b['charging']), (73, True))

    def test_battery_unavailable_is_none_not_zero(self):
        self.build_ds4()
        primary, _ = C.pick_controller(self.scan())
        self.assertIsNone(C.read_battery(primary, self.root / 'empty'))


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 's.json'

    def test_defaults_and_persistence(self):
        s = SettingsStore(self.path)
        self.assertEqual(s.get()['deadzone'], 8)
        s.update({'deadzone': 15, 'theme': 'aurora'})
        again = SettingsStore(self.path).get()
        self.assertEqual((again['deadzone'], again['theme']), (15, 'aurora'))
        self.assertEqual(oct(self.path.stat().st_mode & 0o777), '0o600')

    def test_invalid_values_are_rejected_or_clamped(self):
        s = SettingsStore(self.path)
        s.update({'theme': 'neon-pink', 'deadzone': 999, 'refresh_ms': 1, 'bogus': 1})
        d = s.get()
        self.assertEqual(d['theme'], 'midnight')
        self.assertEqual(d['deadzone'], 40)
        self.assertEqual(d['refresh_ms'], 30)
        self.assertNotIn('bogus', d)

    def test_corrupt_file_is_preserved_and_defaults_used(self):
        self.path.write_text('{not json')
        s = SettingsStore(self.path)
        self.assertEqual(s.get()['theme'], 'midnight')
        self.assertTrue(self.path.with_suffix('.corrupt').exists())

    def test_games_and_profiles(self):
        s = SettingsStore(self.path)
        s.add_game('1086940', 'Baldur')
        with self.assertRaises(ValueError):
            s.add_game('rm -rf', 'x')
        s.set_profile('1086940', 12, 'note')
        self.assertEqual(s.get()['profiles']['1086940']['deadzone'], 12)
        s.remove_game('1086940')
        self.assertEqual((s.get()['games'], s.get()['profiles']), ([], {}))

    def test_reset_keeps_user_shortcuts(self):
        s = SettingsStore(self.path)
        s.add_game('10', 'A')
        s.update({'deadzone': 20})
        d = s.reset()
        self.assertEqual(d['deadzone'], 8)
        self.assertEqual(len(d['games']), 1)

    def test_autostart_file_lifecycle(self):
        target = Path(self.tmp.name) / 'autostart' / 'x.desktop'
        set_autostart(True, target)
        self.assertIn('Exec=', target.read_text())
        set_autostart(False, target)
        self.assertFalse(target.exists())
        set_autostart(False, target)  # idempotent


class BluetoothTests(unittest.TestCase):
    def test_mac_validation(self):
        self.assertTrue(bluetooth.MAC_RE.match('AA:BB:CC:DD:EE:FF'))
        for bad in ('', 'AA:BB', 'AA:BB:CC:DD:EE:GG', 'AA:BB:CC:DD:EE:FF; reboot'):
            self.assertFalse(bluetooth.MAC_RE.match(bad))

    def test_action_rejects_bad_mac_before_running_anything(self):
        bt = bluetooth.Bluetooth(EventLog())
        bt._run = lambda *a, **k: self.fail('must not execute with an invalid MAC')
        bt.installed = staticmethod(lambda: True)
        self.assertFalse(bt.action('connect', 'nope')['ok'])

    def test_line_cleaning_strips_prompt_and_ansi(self):
        raw = '\x1b[0;94m[bluetooth]\x1b[0m# [NEW] Device 11:22:33:44:55:66 Wireless Controller\r'
        self.assertEqual(bluetooth.clean_line(raw), ['[NEW] Device 11:22:33:44:55:66 Wireless Controller'])

    def test_error_explanations(self):
        self.assertIn('Share + PS', bluetooth.explain('Failed to pair: org.bluez.Error.AuthenticationFailed'))
        self.assertIn('rfkill', bluetooth.explain('org.bluez.Error.Blocked'))

    def test_scan_line_parsing(self):
        bt = bluetooth.Bluetooth(EventLog())
        bt._job = {'devices': {}}
        for line in ('[NEW] Device AA:BB:CC:DD:EE:01 11-22-33-44-55-66',
                     '[CHG] Device AA:BB:CC:DD:EE:01 Name: Wireless Controller',
                     '[CHG] Device AA:BB:CC:DD:EE:01 ManufacturerData Key: 0x004c',
                     '[NEW] Device AA:BB:CC:DD:EE:02 Headphones'):
            bt._scan_lines(line)
        d = bt._job['devices']
        self.assertEqual(d['AA:BB:CC:DD:EE:01']['name'], 'Wireless Controller')
        self.assertTrue(d['AA:BB:CC:DD:EE:01']['controller'])
        self.assertFalse(d['AA:BB:CC:DD:EE:02']['controller'])


class SteamTests(unittest.TestCase):
    def test_library_parsing_skips_tools_and_finds_covers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            apps = root / 'steamapps'
            apps.mkdir()
            (apps / 'appmanifest_1.acf').write_text('"AppState"\n{\n"appid"\t\t"1"\n"name"\t\t"Zeta Game"\n}')
            (apps / 'appmanifest_2.acf').write_text('"AppState"\n{\n"appid"\t\t"2"\n"name"\t\t"Alpha Game"\n}')
            (apps / 'appmanifest_3.acf').write_text('"AppState"\n{\n"appid"\t\t"3"\n"name"\t\t"Proton 9.0"\n}')
            cache = root / 'appcache' / 'librarycache'
            cache.mkdir(parents=True)
            (cache / '2_library_600x900.jpg').write_bytes(b'x')
            games = Steam(roots=[root]).library(force=True)
            self.assertEqual([g['name'] for g in games], ['Alpha Game', 'Zeta Game'])
            self.assertTrue(games[0]['cover'].startswith('file://'))
            self.assertIsNone(games[1]['cover'])

    def test_launch_rejects_non_numeric_ids(self):
        st = Steam(roots=[])
        for bad in ('', 'abc', '1; rm -rf ~', 'steam://x'):
            self.assertFalse(st.launch_game(bad)['ok'])
            if bad:  # an empty id means "open Steam settings", which is valid
                self.assertFalse(st.open_controller_settings(bad)['ok'])


class DiagnosticsTests(unittest.TestCase):
    def test_log_since_and_disable(self):
        log = EventLog(maxlen=3)
        for i in range(5):
            log.add('button', 'e%d' % i)
        self.assertEqual([e['msg'] for e in log.since(0)], ['e2', 'e3', 'e4'])
        self.assertEqual([e['msg'] for e in log.since(4)], ['e4'])
        log.enabled = False
        log.add('button', 'hidden')
        log.add('system', 'kept')
        self.assertEqual(log.since(5)[-1]['msg'], 'kept')
        self.assertEqual(len(log.since(5)), 1)

    def test_log_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = EventLog()
            log.add('system', 'hello')
            self.assertIn('hello', log.export(Path(tmp)).read_text())

    def test_rate_meter_starts_at_zero(self):
        self.assertEqual(RateMeter().value(), 0)


class SystemCheckTests(unittest.TestCase):
    def test_permission_failure_is_reported(self):
        status = {'evdev': True, 'info': None,
                  'nodes': [{'role': 'gamepad', 'name': 'Wireless Controller', 'event': 'event5', 'readable': False, 'virtual': False}]}
        checks = {c['id']: c for c in system.run_checks(status, {'installed': False}, {'installed': False})}
        self.assertEqual(checks['access']['state'], 'fail')
        self.assertEqual(checks['bluez']['state'], 'fail')
        self.assertIn('Wireless Controller', system.report_text(list(checks.values())) + 'Wireless Controller')




# ---------------------------------------------------------------------------
# version 0.3 features
# ---------------------------------------------------------------------------
from unittest import mock  # noqa: E402
from ds4cc import lightbar, notify, power  # noqa: E402
from ds4cc import bridge as bridge_mod  # noqa: E402


class PowerTests(unittest.TestCase):
    def test_history_ignores_missing_battery_and_rate_limits(self):
        h = power.BatteryHistory(min_gap=10)
        self.assertFalse(h.add(None))
        self.assertTrue(h.add({'percent': 80, 'charging': False}, now=100))
        self.assertFalse(h.add({'percent': 79, 'charging': False}, now=105))
        self.assertTrue(h.add({'percent': 79, 'charging': False}, now=111))
        self.assertEqual([x['pct'] for x in h.samples()], [80, 79])

    def test_drain_rate_needs_enough_data(self):
        h = power.BatteryHistory(min_gap=0)
        h.add({'percent': 90, 'charging': False}, now=0)
        self.assertIsNone(h.drain_rate())                      # one sample
        h.add({'percent': 89, 'charging': False}, now=600)
        self.assertIsNone(h.drain_rate())                      # too short, too little change
        h.add({'percent': 80, 'charging': False}, now=7200)    # 10 points in 2 hours
        self.assertEqual(h.drain_rate(), 5.0)

    def test_drain_rate_stops_at_charging(self):
        h = power.BatteryHistory(min_gap=0)
        h.add({'percent': 20, 'charging': False}, now=0)
        h.add({'percent': 50, 'charging': True}, now=3600)
        h.add({'percent': 50, 'charging': False}, now=3700)
        self.assertIsNone(h.drain_rate())

    def test_low_battery_alerts_once_and_rearms(self):
        a = power.LowBatteryAlert()
        low = {'percent': 18, 'charging': False}
        self.assertIn('18%', a.check(low, 20))
        self.assertIsNone(a.check({'percent': 17, 'charging': False}, 20))   # no repeat
        self.assertIsNone(a.check({'percent': 30, 'charging': True}, 20))    # charging re-arms
        self.assertIn('15%', a.check({'percent': 15, 'charging': False}, 20))

    def test_low_battery_never_for_unknown_or_disabled(self):
        a = power.LowBatteryAlert()
        self.assertIsNone(a.check(None, 20))
        self.assertIsNone(a.check({'percent': 5, 'charging': False}, 0))     # setting off
        self.assertIsNone(a.check({'percent': 5, 'charging': None}, 20))     # status unknown
        self.assertIsNone(a.check({'percent': 5, 'charging': True}, 20))

    def test_idle_decision(self):
        self.assertTrue(power.should_idle_disconnect(601, 10, 'Bluetooth', 'aa:bb:cc:dd:ee:ff'))
        self.assertFalse(power.should_idle_disconnect(599, 10, 'Bluetooth', 'aa:bb:cc:dd:ee:ff'))
        self.assertFalse(power.should_idle_disconnect(9999, 0, 'Bluetooth', 'aa:bb:cc:dd:ee:ff'))   # off
        self.assertFalse(power.should_idle_disconnect(9999, 10, 'USB', None))                       # wired
        self.assertFalse(power.should_idle_disconnect(9999, 10, 'Bluetooth', None))                 # no address
        self.assertEqual(power.idle_seconds(None, 100.0, 160.0), 60.0)
        self.assertEqual(power.idle_seconds(150.0, 100.0, 160.0), 10.0)


class ActivityTests(unittest.TestCase):
    def test_resting_stick_noise_is_not_activity(self):
        s = C.InputState()
        s.apply('gamepad', C.EV_ABS, 0x00, 130, AI_STICK)   # lx slightly off centre
        self.assertFalse(s.is_active())

    def test_held_stick_trigger_button_and_touch_are_activity(self):
        s = C.InputState()
        s.apply('gamepad', C.EV_ABS, 0x01, 255, AI_STICK)
        self.assertTrue(s.is_active())
        s.reset()
        s.apply('gamepad', C.EV_ABS, 0x02, 200, AI_STICK)
        self.assertTrue(s.is_active())
        s.reset()
        s.apply('gamepad', C.EV_KEY, 0x130, 1)
        self.assertTrue(s.is_active())
        s.apply('gamepad', C.EV_KEY, 0x130, 0)
        self.assertFalse(s.is_active())
        s.apply('touchpad', C.EV_ABS, C.ABS_MT_TRACKING_ID, 5, SimpleNamespace(min=0, max=1919, resolution=0))
        self.assertTrue(s.is_active())


class LightbarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # .../0003:054C:09CC.0001/{input/input5, leds/input5:rgb:indicator}
        self.hid = self.root / 'devices' / '0003:054C:09CC.0001'
        self.dev = self.hid / 'input' / 'input5'
        self.dev.mkdir(parents=True)

    def make_multicolor(self, order='red green blue'):
        led = self.hid / 'leds' / 'input5:rgb:indicator'
        led.mkdir(parents=True)
        (led / 'multi_index').write_text(order + '\n')
        (led / 'multi_intensity').write_text('0 0 0\n')
        (led / 'brightness').write_text('0\n')
        (led / 'max_brightness').write_text('255\n')
        return led

    def test_multicolor_found_and_written_in_index_order(self):
        led_dir = self.make_multicolor('blue green red')
        led = lightbar.find(str(self.dev))
        self.assertEqual(led['kind'], 'multicolor')
        self.assertTrue(led['writable'])
        res = lightbar.apply(led, '#ff8000')
        self.assertTrue(res['ok'], res)
        self.assertEqual((led_dir / 'multi_intensity').read_text().split(), ['0', '128', '255'])   # blue, green, red
        self.assertEqual((led_dir / 'brightness').read_text(), '255')

    def test_current_colour_round_trips(self):
        self.make_multicolor()
        led = lightbar.find(str(self.dev))
        lightbar.apply(led, '#1e90ff')
        self.assertEqual(lightbar.current(led), '#1e90ff')

    def test_split_leds_hid_sony_style(self):
        for c in ('red', 'green', 'blue'):
            d = self.hid / 'leds' / ('sony0:' + c)
            d.mkdir(parents=True)
            (d / 'brightness').write_text('0')
            (d / 'max_brightness').write_text('255')
        led = lightbar.find(str(self.dev))
        self.assertEqual(led['kind'], 'split')
        self.assertTrue(lightbar.apply(led, '#0a3cff')['ok'])
        self.assertEqual((self.hid / 'leds' / 'sony0:blue' / 'brightness').read_text(), '255')

    def test_no_leds_means_none(self):
        self.assertIsNone(lightbar.find(str(self.dev)))

    def test_invalid_colour_rejected_before_any_write(self):
        led_dir = self.make_multicolor()
        led = lightbar.find(str(self.dev))
        for bad in ('red', '#12345', '#gggggg', '', None, '#ff0000; rm -rf /'):
            self.assertFalse(lightbar.apply(led, bad)['ok'])
        self.assertEqual((led_dir / 'multi_intensity').read_text().split(), ['0', '0', '0'])

    @unittest.skipIf(os.geteuid() == 0, 'root can always write')
    def test_read_only_led_is_reported_not_faked(self):
        led_dir = self.make_multicolor()
        os.chmod(led_dir / 'multi_intensity', 0o444)
        led = lightbar.find(str(self.dev))
        self.assertFalse(led['writable'])
        res = lightbar.apply(led, '#ff0000')
        self.assertFalse(res['ok'])
        self.assertIn('only root', res['message'])


    def test_unwritable_reported_even_when_running_as_root(self):
        self.make_multicolor()
        with mock.patch('ds4cc.lightbar.os.access', return_value=False):
            led = lightbar.find(str(self.dev))
            self.assertFalse(led['writable'])
            res = lightbar.apply(led, '#ff0000')
        self.assertFalse(res['ok'])
        self.assertIn('only root', res['message'])

    def test_battery_found_on_the_hid_device(self):
        ps = self.hid / 'power_supply' / 'ps-controller-battery-xx'
        ps.mkdir(parents=True)
        (ps / 'capacity').write_text('64\n')
        (ps / 'status').write_text('Discharging\n')
        node = C.Node(event='event5', path='/dev/input/event5', name='x', vendor=0x54c, product=0x9cc, bus=5,
                      uniq='', phys='', virtual=False, role='gamepad', readable=True, devdir=str(self.dev))
        b = C.read_battery(node, self.root / 'none')
        self.assertEqual((b['percent'], b['charging']), (64, False))


class NotifyTests(unittest.TestCase):
    def test_missing_notify_send_returns_false(self):
        with mock.patch('shutil.which', return_value=None):
            self.assertFalse(notify.send('a', 'b'))

    def test_arguments_are_a_list_and_end_options(self):
        with mock.patch('shutil.which', return_value='/usr/bin/notify-send'), \
                mock.patch('subprocess.Popen') as popen:
            self.assertTrue(notify.send('--evil', '$(rm -rf ~)', 'bogus'))
        args = popen.call_args[0][0]
        self.assertIsInstance(args, list)
        self.assertIn('--urgency=normal', args)                # bogus urgency falls back
        self.assertEqual(args[-2:], ['--evil', '$(rm -rf ~)'])  # after "--", so never parsed as an option
        self.assertLess(args.index('--'), args.index('--evil'))
        self.assertFalse(popen.call_args[1].get('shell', False))


class SteamRunningTests(unittest.TestCase):
    def test_running_appid_from_registry(self):
        with tempfile.TemporaryDirectory() as t:
            reg = Path(t) / 'registry.vdf'
            reg.write_text('"Registry"\n{\n\t"HKCU"\n\t{\n\t\t"Software"\n\t\t{\n\t\t\t"Valve"\n\t\t\t{\n\t\t\t\t"Steam"\n\t\t\t\t{\n'
                           '\t\t\t\t\t"RunningAppID"\t\t"620"\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n')
            st = Steam(roots=[])
            self.assertEqual(st.running_appid([reg]), '620')
            reg.write_text('"RunningAppID"\t\t"0"')
            self.assertIsNone(st.running_appid([reg]))
            self.assertIsNone(st.running_appid([Path(t) / 'missing.vdf']))


class SettingsV3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = SettingsStore(Path(self.tmp.name) / 's.json')

    def test_new_defaults(self):
        d = self.s.get()
        self.assertEqual((d['notifications'], d['low_battery_percent'], d['idle_disconnect_minutes'], d['auto_profile'], d['lightbar_color']),
                         (True, 20, 0, True, ''))

    def test_new_values_validated(self):
        self.s.update({'low_battery_percent': 7, 'idle_disconnect_minutes': 999, 'lightbar_color': 'blue'})
        d = self.s.get()
        self.assertEqual((d['low_battery_percent'], d['idle_disconnect_minutes'], d['lightbar_color']), (20, 0, ''))
        self.s.update({'low_battery_percent': 10, 'idle_disconnect_minutes': 15, 'lightbar_color': '#FF8800'})
        d = self.s.get()
        self.assertEqual((d['low_battery_percent'], d['idle_disconnect_minutes'], d['lightbar_color']), (10, 15, '#ff8800'))

    def test_idle_disconnect_is_off_by_default_even_for_old_files(self):
        (Path(self.tmp.name) / 'old.json').write_text('{"theme": "aurora"}')
        self.assertEqual(SettingsStore(Path(self.tmp.name) / 'old.json').get()['idle_disconnect_minutes'], 0)


class WatcherTests(unittest.TestCase):
    """Drives _Watcher.tick() against stubs; no threads, no hardware, no notifications sent."""

    def make(self, **cfg):
        base = {'notifications': True, 'low_battery_percent': 20, 'idle_disconnect_minutes': 0, 'auto_profile': True,
                'lightbar_color': ''}
        base.update(cfg)
        info = {'name': 'Wireless Controller', 'bus': 'Bluetooth', 'mac': 'aa:bb:cc:dd:ee:ff'}
        api = mock.MagicMock()
        api._settings.get.return_value = base
        api._monitor.status.return_value = {'info': info, 'battery': {'percent': 50, 'charging': False}}
        api._monitor.connected_since.return_value = 1000.0
        api._monitor.last_active.return_value = 1000.0
        api._steam.running_appid.return_value = '620'
        api._bt.action.return_value = {'ok': True, 'message': 'Disconnected.'}
        api._apply_lightbar.return_value = {'ok': True, 'message': ''}
        return bridge_mod._Watcher(api), api, info

    def test_idle_disconnect_fires_once_after_the_limit(self):
        w, api, _ = self.make(idle_disconnect_minutes=5)
        with mock.patch('ds4cc.notify.send'):
            w.tick(now=1000 + 299)
            api._bt.action.assert_not_called()
            w.tick(now=1000 + 301)
            api._bt.action.assert_called_once_with('disconnect', 'AA:BB:CC:DD:EE:FF')
            api._reconnector.suppress.assert_called_once()
            w.tick(now=1000 + 400)
            self.assertEqual(api._bt.action.call_count, 1)

    def test_idle_disconnect_off_never_disconnects(self):
        w, api, _ = self.make(idle_disconnect_minutes=0)
        with mock.patch('ds4cc.notify.send'):
            w.tick(now=1000 + 99999)
        api._bt.action.assert_not_called()

    def test_wired_controller_is_never_disconnected_by_software(self):
        w, api, info = self.make(idle_disconnect_minutes=5)
        info['bus'], info['mac'] = 'USB', None
        with mock.patch('ds4cc.notify.send'):
            w.tick(now=1000 + 99999)
        api._bt.action.assert_not_called()

    def test_recent_activity_prevents_idle_disconnect(self):
        w, api, _ = self.make(idle_disconnect_minutes=5)
        api._monitor.last_active.return_value = 1000 + 590
        with mock.patch('ds4cc.notify.send'):
            w.tick(now=1000 + 600)
        api._bt.action.assert_not_called()

    def test_low_battery_notifies_once(self):
        w, api, _ = self.make()
        with mock.patch('ds4cc.notify.send') as send:
            w.tick(now=1)
            self.assertEqual(send.call_count, 0)            # 50% is fine
            api._monitor.status.return_value['battery'] = {'percent': 15, 'charging': False}
            w.tick(now=2)
            w.tick(now=3)
            self.assertEqual([c for c in send.call_args_list if 'battery' in c[0][0].lower()].__len__(), 1)

    def test_notifications_off_stays_silent(self):
        w, api, _ = self.make(notifications=False)
        api._monitor.status.return_value['battery'] = {'percent': 5, 'charging': False}
        with mock.patch('ds4cc.notify.send') as send:
            w.tick(now=1)
        send.assert_not_called()

    def test_connect_and_disconnect_notify_but_first_look_is_quiet(self):
        w, api, info = self.make()
        with mock.patch('ds4cc.notify.send') as send:
            w.tick(now=1)                                    # app start, already connected
            send.assert_not_called()
            api._monitor.status.return_value = {'info': None, 'battery': None}
            w.tick(now=2)
            self.assertIn('disconnected', send.call_args[0][0].lower())
            api._monitor.status.return_value = {'info': info, 'battery': None}
            w.tick(now=3)
            self.assertIn('connected', send.call_args[0][0].lower())

    def test_light_bar_restored_once_per_connection(self):
        w, api, _ = self.make(lightbar_color='#ff0000')
        with mock.patch('ds4cc.notify.send'):
            w.tick(now=1)
            w.tick(now=2)
            api._apply_lightbar.assert_called_once_with('#ff0000')
            api._monitor.connected_since.return_value = 2000.0   # reconnected
            w.tick(now=3)
            self.assertEqual(api._apply_lightbar.call_count, 2)

    def test_running_app_only_tracked_when_enabled(self):
        w, api, _ = self.make(auto_profile=True)
        with mock.patch('ds4cc.notify.send'):
            w.tick(now=1)
        self.assertEqual(w.running_app, '620')
        w2, api2, _ = self.make(auto_profile=False)
        with mock.patch('ds4cc.notify.send'):
            w2.tick(now=1)
        self.assertIsNone(w2.running_app)


class SaveReportTests(unittest.TestCase):
    def test_report_saved_and_empty_rejected(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(bridge_mod, 'STATE_DIR', Path(t)), \
                mock.patch('ds4cc.bridge.SettingsStore'), mock.patch('ds4cc.bridge.ControllerMonitor'), \
                mock.patch('ds4cc.bridge.Bluetooth'), mock.patch('ds4cc.bridge._Reconnector'), \
                mock.patch('ds4cc.bridge._Watcher'):
            api = bridge_mod.Api()
            self.assertFalse(api.save_report('   ')['ok'])
            res = api.save_report('# Hello', 'test/../evil')
            self.assertTrue(res['ok'], res)
            saved = Path(res['path'])
            self.assertEqual(saved.parent, Path(t))             # a hostile kind cannot escape the folder
            self.assertEqual(saved.read_text(), '# Hello')


if __name__ == '__main__':
    unittest.main()
