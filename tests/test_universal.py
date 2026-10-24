"""Tests for the version 1.4 features: universal games, virtual pad and key mapping.

No hardware and no /dev/uinput access is needed. The mapping engines are pure
and the few runtime paths that touch uinput are patched.
"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))

from ds4cc import controller as C  # noqa: E402
from ds4cc import games as G  # noqa: E402
from ds4cc import input_map as IM  # noqa: E402
from ds4cc import virtual_pad as VP  # noqa: E402
from ds4cc.diagnostics import EventLog  # noqa: E402
from ds4cc import bridge as bridge_mod  # noqa: E402
from ds4cc.settings import SettingsStore  # noqa: E402


class Recorder:
    def __init__(self):
        self.events = []

    def key(self, name, down):
        self.events.append(('key', name, down))

    def mouse(self, name, down):
        self.events.append(('mouse', name, down))

    def wheel(self, delta):
        self.events.append(('wheel', delta))

    def move(self, dx, dy):
        self.events.append(('move', dx, dy))


def engine(mapping=None):
    rec = Recorder()
    eng = IM.MappingEngine(mapping or IM.default_mapping(), rec.key, rec.mouse, rec.wheel, rec.move)
    return eng, rec


class MappingConfigTests(unittest.TestCase):
    def test_shooter_preset_is_the_ready_wasd_and_mouse_preset(self):
        mapping = IM.default_mapping()
        self.assertEqual(mapping['preset'], 'shooter')
        self.assertEqual(mapping['left_stick'], 'wasd')
        self.assertEqual(mapping['right_stick'], 'mouse')
        self.assertEqual(mapping['bindings']['cross'], 'KEY_SPACE')
        self.assertEqual(mapping['bindings']['r2'], 'BTN_LEFT')
        self.assertEqual(mapping['bindings']['l2'], 'BTN_RIGHT')

    def test_all_presets_have_a_binding_or_intentional_blank(self):
        for preset in IM.PRESET_ORDER:
            data = IM.preset_mapping(preset)
            self.assertEqual(set(data['bindings']), set(IM.BUTTONS))
            self.assertIn(data['left_stick'], IM.STICK_MODES)
            self.assertIn(data['right_stick'], IM.STICK_MODES)

    def test_invalid_bindings_and_numbers_are_made_safe(self):
        cleaned = IM.clean_mapping({
            'preset': 'custom',
            'bindings': {'cross': 'KEY_SPACE', 'circle': 'RUN_THIS', 'square': 'KEY_LEFTCTRL'},
            'deadzone': 99, 'sensitivity': float('nan'), 'exponent': -4,
            'invert_y': 'yes', 'grab': True, 'trigger_threshold': 0,
        })
        self.assertEqual(cleaned['bindings']['cross'], 'KEY_SPACE')
        self.assertEqual(cleaned['bindings']['circle'], '')
        self.assertEqual(cleaned['deadzone'], 0.6)
        self.assertEqual(cleaned['sensitivity'], 1.0)
        self.assertEqual(cleaned['exponent'], 0.5)
        self.assertFalse(cleaned['invert_y'])
        self.assertTrue(cleaned['grab'])
        self.assertEqual(cleaned['trigger_threshold'], 0.05)

    def test_left_stick_cannot_be_mouse_look(self):
        cleaned = IM.clean_mapping({'left_stick': 'mouse'})
        self.assertEqual(cleaned['left_stick'], 'wasd')
        self.assertEqual(IM.clean_mapping({'right_stick': 'mouse'})['right_stick'], 'mouse')

    def test_missing_bindings_fall_back_to_the_preset(self):
        cleaned = IM.clean_mapping({'preset': 'shooter', 'bindings': {'cross': 'KEY_F'}})
        self.assertEqual(cleaned['bindings']['cross'], 'KEY_F')
        self.assertEqual(cleaned['bindings']['circle'], 'KEY_LEFTCTRL')
        self.assertEqual(cleaned['left_stick'], 'wasd')

    def test_preset_public_shape(self):
        presets = {p['id']: p for p in IM.public_presets()}
        self.assertEqual(set(presets), set(IM.PRESET_ORDER))
        self.assertIn('WASD', presets['shooter']['label'])
        self.assertIn('bindings', presets['shooter'])


class MappingEngineTests(unittest.TestCase):
    def test_button_press_and_release(self):
        eng, rec = engine()
        eng.set_button('cross', True)
        eng.set_button('cross', True)   # duplicate ignored
        eng.set_button('cross', False)
        self.assertEqual(rec.events, [('key', 'KEY_SPACE', True), ('key', 'KEY_SPACE', False)])

    def test_two_buttons_on_one_key_hold_until_both_release(self):
        mapping = IM.default_mapping()
        mapping['preset'] = 'custom'
        mapping['bindings'] = dict(mapping['bindings'])
        mapping['bindings']['cross'] = 'KEY_SPACE'
        mapping['bindings']['circle'] = 'KEY_SPACE'
        eng, rec = engine(mapping)
        eng.set_button('cross', True)
        eng.set_button('circle', True)
        eng.set_button('cross', False)
        self.assertEqual(rec.events, [('key', 'KEY_SPACE', True)])
        eng.set_button('circle', False)
        self.assertEqual(rec.events, [('key', 'KEY_SPACE', True), ('key', 'KEY_SPACE', False)])

    def test_left_stick_wasd_with_hysteresis(self):
        eng, rec = engine()
        eng.set_axis('lx', 0.5)
        self.assertIn(('key', 'KEY_D', True), rec.events)
        eng.set_axis('lx', 0.15)   # still inside the hold threshold
        self.assertNotIn(('key', 'KEY_D', False), rec.events)
        eng.set_axis('lx', 0.1)    # released
        self.assertIn(('key', 'KEY_D', False), rec.events)
        eng.set_axis('ly', 0.8)
        self.assertIn(('key', 'KEY_W', True), rec.events)
        eng.set_axis('ly', -0.8)
        self.assertIn(('key', 'KEY_S', True), rec.events)

    def test_arrows_and_ad_modes(self):
        mapping = IM.default_mapping()
        mapping['left_stick'] = 'arrows'
        eng, rec = engine(mapping)
        eng.set_axis('lx', -1)
        self.assertIn(('key', 'KEY_LEFT', True), rec.events)
        mapping['left_stick'] = 'ad'
        eng.set_mapping(mapping)
        rec.events = []
        eng.set_axis('ly', 1)
        self.assertEqual(rec.events, [])
        eng.set_axis('lx', 1)
        self.assertIn(('key', 'KEY_D', True), rec.events)

    def test_mouse_look_orientation_and_deadzone(self):
        eng, rec = engine()
        eng.set_axis('rx', 1.0)
        eng.tick(0.1)
        moves = [e for e in rec.events if e[0] == 'move']
        self.assertTrue(moves)
        self.assertGreater(moves[0][1], 100)
        self.assertEqual(moves[0][2], 0)
        rec.events = []
        eng.set_axis('rx', 0.1)
        eng.tick(0.1)
        self.assertEqual([e for e in rec.events if e[0] == 'move'], [])
        eng.set_axis('rx', 0.0)
        eng.set_axis('ry', 0.5)
        eng.tick(0.05)
        moves = [e for e in rec.events if e[0] == 'move']
        self.assertTrue(moves)
        self.assertLess(moves[0][2], 0)   # stick up looks up

    def test_invert_y(self):
        mapping = IM.default_mapping()
        mapping['invert_y'] = True
        eng, rec = engine(mapping)
        eng.set_axis('ry', 1.0)
        eng.tick(0.05)
        moves = [e for e in rec.events if e[0] == 'move']
        self.assertTrue(moves)
        self.assertGreater(moves[0][2], 0)

    def test_analog_and_digital_triggers(self):
        eng, rec = engine()
        eng.set_axis('l2', 0.5)
        self.assertIn(('mouse', 'BTN_RIGHT', True), rec.events)
        eng.set_axis('l2', 0.1)
        self.assertIn(('mouse', 'BTN_RIGHT', False), rec.events)
        eng2, rec2 = engine()
        eng2.set_button('l2', True)
        self.assertIn(('mouse', 'BTN_RIGHT', True), rec2.events)
        eng2.set_axis('l2', 0.0)   # analog now known and below threshold
        self.assertIn(('mouse', 'BTN_RIGHT', False), rec2.events)

    def test_wheel_fires_once_per_press(self):
        mapping = IM.default_mapping()
        mapping['preset'] = 'custom'
        mapping['bindings'] = dict(mapping['bindings'])
        mapping['bindings']['l1'] = 'WHEEL_UP'
        eng, rec = engine(mapping)
        eng.set_button('l1', True)
        eng.set_button('l1', True)
        eng.set_button('l1', False)
        self.assertEqual([e for e in rec.events if e[0] == 'wheel'], [('wheel', 1)])

    def test_reset_releases_everything(self):
        eng, rec = engine()
        eng.set_button('cross', True)
        eng.set_axis('lx', 1)
        eng.set_axis('l2', 1)
        eng.reset()
        self.assertIn(('key', 'KEY_SPACE', False), rec.events)
        self.assertIn(('key', 'KEY_D', False), rec.events)
        self.assertIn(('mouse', 'BTN_RIGHT', False), rec.events)
        self.assertEqual(eng.held(), [])

    def test_last_output_is_useful_for_the_ui(self):
        eng, _ = engine()
        eng.set_button('cross', True)
        self.assertIn('KEY_SPACE', eng.last_output)
        eng.set_button('cross', False)
        self.assertIn('up', eng.last_output)


class MappingRuntimeTests(unittest.TestCase):
    def test_reason_explains_missing_and_locked_uinput(self):
        with mock.patch('os.path.exists', return_value=False):
            self.assertIn('modprobe', IM.uinput_reason())
        with mock.patch('os.path.exists', return_value=True), mock.patch('os.access', return_value=False):
            reason = IM.uinput_reason()
            self.assertIn('/dev/uinput', reason)
            self.assertIn('enable-uinput.sh', reason)

    def test_mapper_refuses_to_start_without_permission(self):
        mapper = IM.InputMapper()
        with mock.patch('ds4cc.input_map.uinput_reason', return_value='no uinput here'):
            res = mapper.enable()
            self.assertFalse(res['ok'])
            self.assertIn('no uinput', res['message'])
            self.assertFalse(mapper.enabled)
            self.assertEqual(mapper.status()['state'], 'blocked')

    def test_mapper_starts_and_stops_with_a_fake_output(self):
        class FakeOutput:
            def __init__(self):
                self.events = []
                self.closed = False

            def open(self):
                pass

            def key(self, name, down):
                self.events.append(('key', name, down))

            def mouse_button(self, name, down):
                self.events.append(('mouse', name, down))

            def wheel(self, delta):
                self.events.append(('wheel', delta))

            def move(self, dx, dy):
                self.events.append(('move', dx, dy))

            def close(self):
                self.closed = True

        fake = FakeOutput()
        with mock.patch('ds4cc.input_map.uinput_reason', return_value=''), \
                mock.patch('ds4cc.input_map.UinputOutput', return_value=fake):
            mapper = IM.InputMapper()
            res = mapper.enable()
            self.assertTrue(res['ok'], res)
            self.assertTrue(mapper.enabled)
            mapper.feed_button('cross', True)
            mapper.feed_axis('l2', 1.0)
            self.assertIn(('key', 'KEY_SPACE', True), fake.events)
            self.assertIn(('mouse', 'BTN_RIGHT', True), fake.events)
            mapper.disable()
            self.assertFalse(mapper.enabled)
            self.assertTrue(fake.closed)
            self.assertIn(('key', 'KEY_SPACE', False), fake.events)


class VirtualPadStateTests(unittest.TestCase):
    def test_scale_stick_deadzone_and_full_range(self):
        self.assertEqual(VP.scale_stick(0, 0), (0.0, 0.0))
        self.assertEqual(VP.scale_stick(0.05, 0.0), (0.0, 0.0))
        x, y = VP.scale_stick(1.0, 0.0)
        self.assertAlmostEqual(x, 1.0)
        self.assertAlmostEqual(y, 0.0)
        x, _ = VP.scale_stick(0.55, 0.0)
        self.assertAlmostEqual(x, 0.5, places=2)

    def test_face_buttons_use_xbox_layout(self):
        state = VP.XboxState()
        self.assertEqual(state.feed_button('cross', True), [('key', 'BTN_A', 1)])
        self.assertEqual(state.feed_button('circle', True), [('key', 'BTN_B', 1)])
        self.assertEqual(state.feed_button('square', True), [('key', 'BTN_X', 1)])
        self.assertEqual(state.feed_button('triangle', True), [('key', 'BTN_Y', 1)])
        self.assertEqual(state.feed_button('ps', True), [('key', 'BTN_MODE', 1)])
        # Touchpad and PS share BTN_MODE; the count keeps it held until both are up.
        self.assertEqual(state.feed_button('touchpad', True), [])
        self.assertEqual(state.feed_button('ps', False), [])
        self.assertEqual(state.feed_button('touchpad', False), [('key', 'BTN_MODE', 0)])

    def test_sticks_are_scaled_and_flipped_for_evdev(self):
        state = VP.XboxState()
        self.assertEqual(state.feed_axis('lx', 1.0), [('abs', 'ABS_X', 32767), ('abs', 'ABS_Y', 0)])
        state.feed_axis('lx', 0.0)
        self.assertEqual(state.feed_axis('ly', 1.0), [('abs', 'ABS_X', 0), ('abs', 'ABS_Y', -32767)])
        self.assertEqual(state.feed_axis('rx', -1.0), [('abs', 'ABS_RX', -32767), ('abs', 'ABS_RY', 0)])

    def test_triggers(self):
        state = VP.XboxState()
        events = state.feed_axis('l2', 0.6)
        self.assertIn(('abs', 'ABS_Z', 153), events)
        self.assertIn(('key', 'BTN_TL2', 1), events)
        events = state.feed_axis('l2', 0.0)
        self.assertIn(('abs', 'ABS_Z', 0), events)
        self.assertIn(('key', 'BTN_TL2', 0), events)

    def test_trigger_pressure_updates_release_the_virtual_button(self):
        pad = VP.XboxState()
        events = []
        for value in (0.6, 0.8, 1.0, 0.7, 0.0):
            events += pad.feed_axis('r2', value)
        self.assertEqual([e for e in events if e[0] == 'key'],
                         [('key', 'BTN_TR2', 1), ('key', 'BTN_TR2', 0)])
        self.assertNotIn('BTN_TR2', pad._counts)

    def test_digital_only_triggers_still_move_the_virtual_axis(self):
        state = VP.XboxState()
        events = state.feed_button('l2', True)
        self.assertIn(('abs', 'ABS_Z', 255), events)
        self.assertIn(('key', 'BTN_TL2', 1), events)
        events = state.feed_button('l2', False)
        self.assertIn(('abs', 'ABS_Z', 0), events)
        self.assertIn(('key', 'BTN_TL2', 0), events)

    def test_dpad_becomes_a_hat(self):
        state = VP.XboxState()
        self.assertEqual(state.feed_button('dpad-up', True),
                         [('abs', 'ABS_HAT0X', 0), ('abs', 'ABS_HAT0Y', -1)])
        self.assertEqual(state.feed_button('dpad-right', True), [('abs', 'ABS_HAT0X', 1), ('abs', 'ABS_HAT0Y', -1)])
        self.assertEqual(state.feed_button('dpad-up', False), [('abs', 'ABS_HAT0X', 1), ('abs', 'ABS_HAT0Y', 0)])

    def test_reset_returns_neutral_events(self):
        state = VP.XboxState()
        state.feed_button('cross', True)
        state.feed_axis('lx', 1)
        state.feed_axis('r2', 1)
        events = state.reset()
        self.assertIn(('key', 'BTN_A', 0), events)
        self.assertIn(('key', 'BTN_TR2', 0), events)
        self.assertIn(('abs', 'ABS_X', 0), events)
        self.assertIn(('abs', 'ABS_Z', 0), events)
        self.assertEqual(state.snapshot()['buttons'], [])

    def test_virtual_pad_refuses_without_permission(self):
        pad = VP.VirtualPad()
        with mock.patch('ds4cc.virtual_pad.uinput_reason', return_value='/dev/uinput is locked'):
            res = pad.enable()
            self.assertFalse(res['ok'])
            self.assertIn('locked', res['message'])
            self.assertFalse(pad.enabled)

    def test_virtual_pad_writes_through_a_fake_uinput_device(self):
        class FakeUInput:
            def __init__(self, events, **kwargs):
                self.events = events
                self.kwargs = kwargs
                self.writes = []
                self.synced = 0
                self.closed = False

            def write(self, etype, code, value):
                self.writes.append((etype, code, value))

            def syn(self):
                self.synced += 1

            def close(self):
                self.closed = True

        created = []
        def factory(events, **kwargs):
            device = FakeUInput(events, **kwargs)
            created.append(device)
            return device

        pad = VP.VirtualPad()
        with mock.patch('ds4cc.virtual_pad.uinput_reason', return_value=''), \
                mock.patch('evdev.UInput', side_effect=factory):
            res = pad.enable()
            self.assertTrue(res['ok'], res)
            self.assertEqual(created[0].kwargs['phys'], 'ds4cc-vpad')
            self.assertEqual(created[0].kwargs['name'], VP.XBOX_NAME)
            pad.feed_button('cross', True)
            pad.feed_axis('lx', 1.0)
            pad.reset()
            self.assertTrue(created[0].synced > 0)
            self.assertTrue(created[0].writes)
            pad.disable()
            self.assertTrue(created[0].closed)


class SettingsFeatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'settings.json'
        self.store = SettingsStore(self.path)

    def test_mapping_defaults_and_persistence(self):
        data = self.store.get()
        self.assertEqual(data['mapping']['preset'], 'shooter')
        self.assertFalse(data['mapping']['enabled'])
        mapping = dict(data['mapping'])
        mapping['enabled'] = True
        mapping['bindings'] = dict(mapping['bindings'])
        mapping['bindings']['cross'] = 'KEY_F'
        self.store.update({'mapping': mapping})
        again = SettingsStore(self.path).get()['mapping']
        self.assertTrue(again['enabled'])
        self.assertEqual(again['bindings']['cross'], 'KEY_F')

    def test_mapping_rejects_wrong_types(self):
        data, changed = self.store.update({'mapping': {'enabled': True, 'bindings': 'nope'}})
        self.assertEqual(data['mapping']['enabled'], True)
        self.assertEqual(data['mapping']['bindings']['cross'], 'KEY_SPACE')
        self.assertIn('mapping', changed)

    def test_custom_game_add_remove_and_validation(self):
        entry = self.store.add_custom_game('My Game', 'wine /tmp/game.exe')
        self.assertTrue(entry['id'].startswith('manual:'))
        self.assertEqual(self.store.get()['custom_games'][0]['name'], 'My Game')
        for bad in ('', 'sudo wine /tmp/x.exe', 'wine "unclosed'):
            with self.assertRaises(ValueError):
                self.store.add_custom_game('x', bad)
        self.assertTrue(self.store.remove_custom_game(entry['id']))
        self.assertEqual(self.store.get()['custom_games'], [])

    def test_profiles_accept_generic_ids_and_normalize_steam(self):
        self.store.set_profile('desktop:foo.desktop', 12, 'desktop')
        self.store.set_profile('manual:abc123', 5, 'manual')
        self.store.set_profile('steam:620', 9, 'steam')
        profiles = self.store.get()['profiles']
        self.assertEqual(profiles['desktop:foo.desktop']['deadzone'], 12)
        self.assertEqual(profiles['manual:abc123']['deadzone'], 5)
        self.assertEqual(profiles['620']['deadzone'], 9)
        with self.assertRaises(ValueError):
            self.store.set_profile('desktop:../evil', 1, '')

    def test_reset_keeps_custom_games_but_resets_mapping(self):
        entry = self.store.add_custom_game('Keep me', '/tmp/keep.sh')
        self.store.update({'mapping': dict(self.store.get()['mapping'], enabled=True)})
        with mock.patch('ds4cc.settings.set_autostart'):
            data = self.store.reset()
        self.assertEqual([g['id'] for g in data['custom_games']], [entry['id']])
        self.assertFalse(data['mapping']['enabled'])


class DesktopEntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / 'applications'
        self.dir.mkdir()

    def write(self, name, body):
        path = self.dir / name
        path.write_text(body)
        return path

    def test_parses_a_game_entry_and_removes_exec_placeholders(self):
        self.write('Foo Game.desktop', '[Desktop Entry]\nType=Application\nName=Foo Game\n'
                                       'Exec=/usr/bin/foo --fullscreen %U\nCategories=Game;ActionGame;\n'
                                       'Comment=A game\n')
        entries = G.scan_desktops([self.dir])
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry['name'], 'Foo Game')
        self.assertTrue(entry['id'].startswith('desktop:'))
        self.assertEqual(entry['binary'], '/usr/bin/foo')
        self.assertNotIn('%U', entry['exec'])

    def test_skips_non_games_hidden_entries_and_our_own_launcher(self):
        self.write('Editor.desktop', '[Desktop Entry]\nType=Application\nName=Editor\n'
                                      'Exec=/usr/bin/editor\nCategories=Utility;TextEditor;\n')
        self.write('Hidden.desktop', '[Desktop Entry]\nType=Application\nName=Hidden Game\n'
                                      'Exec=/usr/bin/hidden\nCategories=Game;\nNoDisplay=true\n')
        self.write('ds4-control-center.desktop', '[Desktop Entry]\nType=Application\nName=DS4 Control Center\n'
                                                   'Exec=/opt/ds4/run.sh\nCategories=Game;\n')
        self.assertEqual(G.scan_desktops([self.dir]), [])

    def test_exec_binary_skips_wrappers(self):
        self.assertEqual(G.exec_binary(['env', 'MANGOHUD=1', 'game-bin']), 'game-bin')
        self.assertEqual(G.exec_binary(['flatpak', 'run', 'org.example.Game']), 'org.example.Game')
        self.assertEqual(G.exec_binary(['wine', '/tmp/foo.exe']), '/tmp/foo.exe')


class LutrisTests(unittest.TestCase):
    def test_reads_only_installed_games(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'pga.db'
            con = sqlite3.connect(db)
            con.execute('CREATE TABLE games (id INTEGER PRIMARY KEY, name TEXT, slug TEXT, runner TEXT, '
                        'directory TEXT, configpath TEXT, installed INTEGER)')
            con.execute('INSERT INTO games VALUES (1, "Installed Game", "installed-game", "wine", "/games/a", "", 1)')
            con.execute('INSERT INTO games VALUES (2, "Not Installed", "not-installed", "wine", "/games/b", "", 0)')
            con.commit()
            con.close()
            games = G.scan_lutris([db])
            self.assertEqual([g['name'] for g in games], ['Installed Game'])
            self.assertEqual(games[0]['id'], 'lutris:1')
            self.assertEqual(games[0]['directory'], '/games/a')

    def test_missing_or_broken_database_is_empty_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'bad.db'
            bad.write_text('not sqlite')
            self.assertEqual(G.scan_lutris([bad, Path(tmp) / 'missing.db']), [])


class UniversalLibraryTests(unittest.TestCase):
    def make(self):
        steam = SimpleNamespace(library=lambda force=False: [], launch_game=lambda appid: {'ok': True, 'message': appid})
        return G.UniversalGames(steam), steam

    def test_combines_and_deduplicates_sources(self):
        ug, _ = self.make()
        steam_games = [{'appid': '620', 'name': 'Portal 2', 'cover': None}]
        custom = [{'id': 'manual:abc', 'name': 'Cracked Game', 'command': 'wine /tmp/cracked.exe'}]
        with mock.patch('ds4cc.games.scan_desktops', return_value=[
            {'id': 'desktop:portal2', 'name': 'Portal 2', 'source': 'desktop', 'cover': None,
             'exec': '/usr/bin/portal2', 'binary': '/usr/bin/portal2', 'path': '/tmp/p.desktop'},
            {'id': 'desktop:other', 'name': 'Other Game', 'source': 'desktop', 'cover': None,
             'exec': '/usr/bin/other', 'binary': '/usr/bin/other', 'path': '/tmp/o.desktop'},
        ]), mock.patch('ds4cc.games.scan_lutris', return_value=[
            {'id': 'lutris:1', 'name': 'Lutris Game', 'source': 'lutris', 'cover': None, 'directory': '/games/l'},
        ]):
            result = ug.library(steam_games, custom)
        ids = [g['id'] for g in result['games']]
        self.assertIn('manual:abc', ids)
        self.assertIn('steam:620', ids)
        self.assertIn('lutris:1', ids)
        self.assertIn('desktop:other', ids)
        self.assertNotIn('desktop:portal2', ids)   # same name as the Steam copy
        self.assertEqual(result['counts']['manual'], 1)

    def test_running_matches_manual_lutris_and_desktop_processes(self):
        ug, _ = self.make()
        library = [
            {'id': 'manual:bar', 'name': 'Bar', 'source': 'manual', 'command': 'wine /tmp/Bar.exe'},
            {'id': 'desktop:foo', 'name': 'Foo', 'source': 'desktop', 'exec': '/usr/bin/foo', 'binary': '/usr/bin/foo'},
            {'id': 'lutris:3', 'name': 'Baz', 'source': 'lutris', 'directory': '/games/baz', 'slug': 'baz'},
        ]
        self.assertEqual(ug.running(None, library, [['wine', '/tmp/Bar.exe']])['id'], 'manual:bar')
        self.assertEqual(ug.running(None, library, [['/usr/bin/foo']])['id'], 'desktop:foo')
        home_game = {'id': 'manual:home', 'name': 'Home', 'source': 'manual', 'command': 'wine ~/Games/h.exe'}
        with mock.patch('os.path.expanduser', side_effect=lambda p: p.replace('~', '/home/test')):
            self.assertEqual(ug.running(None, [home_game], [['wine', '/home/test/Games/h.exe']])['id'], 'manual:home')
        self.assertEqual(ug.running(None, library, [['/games/baz/baz.exe']])['id'], 'lutris:3')
        self.assertIsNone(ug.running(None, library, [['/usr/bin/somethingelse']]))

    def test_steam_running_game_wins(self):
        ug, _ = self.make()
        library = [{'id': 'steam:620', 'appid': '620', 'name': 'Portal 2', 'source': 'steam'}]
        self.assertEqual(ug.running('620', library, [])['id'], 'steam:620')

    def test_manual_launch_uses_no_shell_and_rejects_dangerous_commands(self):
        ug, _ = self.make()
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'x.exe'
            exe.write_text('fake')
            with mock.patch('ds4cc.games.subprocess.Popen') as popen:
                res = ug.launch({'name': 'X', 'source': 'manual', 'command': 'wine %s' % exe})
            self.assertTrue(res['ok'], res)
            self.assertEqual(popen.call_args[0][0], ['wine', str(exe)])
            self.assertFalse(popen.call_args[1].get('shell', False))
            for command in ('sudo ./game', 'wine /definitely/missing/x.exe'):
                res = ug.launch({'name': 'X', 'source': 'manual', 'command': command})
                self.assertFalse(res['ok'], command)

    def test_desktop_launch_goes_through_gio(self):
        ug, _ = self.make()
        with tempfile.TemporaryDirectory() as tmp:
            entry = Path(tmp) / 'Game.desktop'
            entry.write_text('[Desktop Entry]\nType=Application\nName=Game\nExec=/usr/bin/game\nCategories=Game;\n')
            with mock.patch('ds4cc.games.shutil.which', return_value='/usr/bin/gio'), \
                    mock.patch('ds4cc.games.subprocess.Popen') as popen:
                res = ug.launch({'name': 'Game', 'source': 'desktop', 'path': str(entry)})
        self.assertTrue(res['ok'], res)
        self.assertEqual(popen.call_args[0][0][:2], ['gio', 'launch'])

    def test_lutris_launch_uses_the_documented_uri(self):
        ug, _ = self.make()
        with mock.patch('ds4cc.games.shutil.which', side_effect=lambda name: '/usr/bin/lutris' if name == 'lutris' else None), \
                mock.patch('ds4cc.games.subprocess.Popen') as popen:
            res = ug.launch({'name': 'Lutris Game', 'source': 'lutris', 'lutris_id': 7})
        self.assertTrue(res['ok'], res)
        self.assertEqual(popen.call_args[0][0], ['/usr/bin/lutris', 'lutris:rungameid/7'])

    def test_command_validation(self):
        self.assertEqual(G.validate_command('wine /tmp/x.exe'), 'wine /tmp/x.exe')
        for bad in ('', '   ', 'sudo ./x', 'wine "unclosed', 'x\ny'):
            with self.assertRaises(ValueError):
                G.validate_command(bad)


class MonitorOutputTests(unittest.TestCase):
    class Output:
        def __init__(self):
            self.calls = []

        def feed_button(self, name, pressed):
            self.calls.append(('button', name, pressed))

        def feed_axis(self, name, value):
            self.calls.append(('axis', name, value))

        def reset(self):
            self.calls.append(('reset',))

    def test_controller_events_are_fed_as_semantics(self):
        monitor = C.ControllerMonitor(EventLog())
        out = self.Output()
        monitor.add_output(out)
        ai = {0x00: SimpleNamespace(min=0, max=255, resolution=0),
              0x02: SimpleNamespace(min=0, max=255, resolution=0)}
        dev = SimpleNamespace(read=lambda: [
            SimpleNamespace(type=C.EV_KEY, code=0x130, value=1),
            SimpleNamespace(type=C.EV_ABS, code=0x00, value=255),
            SimpleNamespace(type=C.EV_ABS, code=0x02, value=200),
        ])
        monitor._drain(dev, 'gamepad', ai)
        self.assertIn(('button', 'cross', True), out.calls)
        self.assertIn(('axis', 'lx', 1.0), out.calls)
        self.assertIn(('axis', 'l2', 0.784), out.calls)
        out.calls = []
        dev2 = SimpleNamespace(read=lambda: [
            SimpleNamespace(type=C.EV_KEY, code=0x130, value=0),
        ])
        monitor._drain(dev2, 'gamepad', ai)
        self.assertIn(('button', 'cross', False), out.calls)

    def test_outputs_are_reset_on_disconnect(self):
        monitor = C.ControllerMonitor(EventLog())
        out = self.Output()
        monitor.add_output(out)
        monitor._reset_outputs()
        self.assertEqual(out.calls, [('reset',)])

    def test_repeated_reservation_does_not_grab_twice(self):
        monitor = C.ControllerMonitor(EventLog())
        device = mock.Mock()
        monitor._primary_dev = device
        self.assertTrue(monitor.set_grab(True)['ok'])
        self.assertTrue(monitor.set_grab(True)['ok'])
        device.grab.assert_called_once_with()
        self.assertTrue(monitor.status()['grab']['active'])

    def test_grab_and_ungrab_are_reported(self):
        monitor = C.ControllerMonitor(EventLog())
        class Dev:
            def __init__(self):
                self.grabbed = False

            def grab(self):
                self.grabbed = True

            def ungrab(self):
                self.grabbed = False
        dev = Dev()
        monitor._primary_dev = dev
        self.assertTrue(monitor.set_grab(True)['ok'])
        self.assertTrue(dev.grabbed)
        self.assertTrue(monitor.status()['grab']['active'])
        self.assertTrue(monitor.set_grab(False)['ok'])
        self.assertFalse(dev.grabbed)

    def test_add_output_is_idempotent(self):
        monitor = C.ControllerMonitor(EventLog())
        out = self.Output()
        monitor.add_output(out)
        monitor.add_output(out)
        self.assertEqual(len(monitor._outputs), 1)


class MonitorOwnDeviceTests(unittest.TestCase):
    def test_our_virtual_pad_is_never_read_as_a_controller(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / 'virtual' / 'input9'
            dev = base / 'device'
            (dev / 'id').mkdir(parents=True)
            (dev / 'capabilities').mkdir()
            (dev / 'name').write_text('Microsoft X-Box 360 pad\n')
            (dev / 'phys').write_text('ds4cc-vpad\n')
            (dev / 'uniq').write_text('\n')
            (dev / 'id' / 'vendor').write_text('045e\n')
            (dev / 'id' / 'product').write_text('028e\n')
            (dev / 'id' / 'bustype').write_text('0003\n')
            (dev / 'capabilities' / 'key').write_text('1\n')       # BTN_SOUTH bit 304 is not set; role would be other
            (dev / 'capabilities' / 'abs').write_text('1\n')
            ev = root / 'class' / 'event9'
            ev.parent.mkdir()
            ev.symlink_to(base)
            self.assertEqual(C.scan_nodes(root / 'class', Path(tmp) / 'dev'), [])


class FakeMonitor:
    def __init__(self, *args, **kwargs):
        self._outputs = []
        self.battery_history = SimpleNamespace(drain_rate=lambda: None)
        self.connected = False

    def add_output(self, output):
        self._outputs.append(output)

    def start(self):
        pass

    def stop(self):
        pass

    def status(self):
        return {'connected': False, 'info': None, 'battery': None, 'nodes': [], 'unreadable': [],
                'error': None, 'evdev': True, 'connected_since': None, 'last_input': None,
                'grab': {'wanted': False, 'active': False, 'error': ''}}

    def set_grab(self, on):
        return {'ok': True, 'message': ''}

    def connected_since(self):
        return None

    def last_active(self):
        return None

    def frame(self, since=0):
        return {'seq': 0, 'same': True}

    def rumble(self, *a):
        return {'ok': True, 'message': 'ok'}

    def reset_measurements(self):
        pass

    def primary_node(self):
        return None


class FakeSteam:
    def status(self):
        return {'installed': False, 'running': False, 'path': None, 'kind': None}

    def library(self, force=False):
        return []

    def launch(self):
        return {'ok': False, 'message': 'no steam'}

    def launch_game(self, appid):
        return {'ok': True, 'message': 'steam ' + str(appid)}

    def open_controller_settings(self, appid=''):
        return {'ok': True, 'message': 'steam settings'}

    def running_appid(self):
        return None


class FakeReconnector:
    def __init__(self, *a, **k):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def snapshot(self, *a):
        return {'state': 'idle', 'attempt': 0, 'max': 3}

    def suppress(self):
        pass

    def rearm(self):
        pass


class FakeWatcher:
    def __init__(self, *a, **k):
        self.running_app = None
        self.running_game = None

    def start(self):
        pass

    def stop(self):
        pass


class BridgeFeatureTests(unittest.TestCase):
    """Exercises the public API without hardware or real uinput devices."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SettingsStore(Path(self.tmp.name) / 'settings.json')
        self.patches = [
            mock.patch('ds4cc.bridge.SettingsStore', return_value=self.store),
            mock.patch('ds4cc.bridge.ControllerMonitor', FakeMonitor),
            mock.patch('ds4cc.bridge.Steam', FakeSteam),
            mock.patch('ds4cc.bridge.Bluetooth', lambda *a, **k: SimpleNamespace(
                status=lambda: {'installed': False}, installed=lambda: False,
                devices=lambda *a: [], action=lambda *a: {'ok': True, 'message': ''},
                cancel=lambda: None, start_scan=lambda: {'ok': True}, start_pair=lambda *a: {'ok': True},
                job=lambda: None, set_power=lambda *a: {'ok': True})),
            mock.patch('ds4cc.bridge._Reconnector', FakeReconnector),
            mock.patch('ds4cc.bridge._Watcher', FakeWatcher),
            mock.patch('ds4cc.bridge.uinput_reason', return_value='/dev/uinput is locked'),
            mock.patch('ds4cc.input_map.uinput_reason', return_value='/dev/uinput is locked'),
            mock.patch('ds4cc.virtual_pad.uinput_reason', return_value='/dev/uinput is locked'),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.api = bridge_mod.Api()
        self.addCleanup(self.api._shutdown)

    def test_mapping_api_and_saved_bindings(self):
        info = self.api.get_mapping()
        self.assertEqual(len(info['buttons']), 18)
        self.assertEqual(info['mapping']['preset'], 'shooter')
        self.assertFalse(info['available'])
        res = self.api.save_mapping({'bindings': {'cross': 'KEY_G'}})
        self.assertTrue(res['ok'], res)
        self.assertEqual(res['mapping']['mapping']['bindings']['cross'], 'KEY_G')
        self.assertEqual(self.store.get()['mapping']['bindings']['cross'], 'KEY_G')
        res = self.api.apply_mapping_preset('racing')
        self.assertTrue(res['ok'], res)
        self.assertEqual(res['mapping']['mapping']['left_stick'], 'ad')
        res = self.api.set_mapping_enabled(True)
        self.assertFalse(res['ok'])
        self.assertFalse(self.store.get()['mapping']['enabled'])

    def test_blocked_mapper_does_not_reserve_the_physical_controller(self):
        mapping = self.store.get()['mapping']
        mapping.update(enabled=True, grab=True)
        self.store.update({'mapping': mapping})
        with mock.patch.object(self.api._monitor, 'set_grab') as grab:
            self.api._apply_input_settings(self.store.get())
            grab.assert_called_once_with(False)

    def test_virtual_pad_reports_permission_problem(self):
        res = self.api.set_virtual_pad(True)
        self.assertFalse(res['ok'])
        self.assertIn('uinput', res['message'])
        self.assertFalse(self.store.get()['virtual_pad_enabled'])
        status = self.api.get_virtual_pad()
        self.assertFalse(status['enabled'])

    def test_custom_games_appear_in_the_universal_library(self):
        self.store.update({'scan_desktop_games': False, 'scan_lutris_games': False})
        res = self.api.add_custom_game('Hand Made', '/tmp/handmade.sh')
        self.assertTrue(res['ok'], res)
        games = self.api.get_games(True)['games']
        self.assertEqual([g['name'] for g in games], ['Hand Made'])
        self.assertEqual(games[0]['source'], 'manual')

    def test_system_check_mentions_virtual_input(self):
        checks = {c['id']: c for c in self.api.system_check()['checks']}
        self.assertEqual(checks['uinput']['state'], 'warn')
        self.assertIn('enable-uinput', checks['uinput']['hint'])

    def test_troubleshooting_reports_desired_but_blocked_features(self):
        from ds4cc import system
        checks = {c['id']: c for c in system.run_checks(
            {'evdev': True, 'nodes': [], 'info': None}, {'installed': False}, {'installed': False},
            uinput={'available': False, 'reason': 'no /dev/uinput'},
            mapping={'enabled': False, 'desired': True, 'state': 'blocked', 'message': 'locked'},
            vpad={'enabled': False, 'desired': True, 'state': 'blocked', 'message': 'locked'})}
        self.assertEqual(checks['uinput']['state'], 'warn')
        self.assertEqual(checks['keymap']['state'], 'fail')
        self.assertEqual(checks['vpad']['state'], 'fail')


if __name__ == '__main__':
    unittest.main()
