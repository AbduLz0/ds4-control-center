import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('backend', Path(__file__).parents[1] / 'app' / 'backend.py')
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)

class MappingTests(unittest.TestCase):
    def test_face_buttons(self):
        self.assertEqual(backend.BTN_MAP['BTN_SOUTH'], 'cross')
        self.assertEqual(backend.BTN_MAP['BTN_EAST'], 'circle')
        self.assertEqual(backend.BTN_MAP['BTN_WEST'], 'square')
        self.assertEqual(backend.BTN_MAP['BTN_NORTH'], 'triangle')

    def test_stick_axes(self):
        self.assertEqual(backend.ABS_MAP['ABS_X'], 'lx')
        self.assertEqual(backend.ABS_MAP['ABS_RY'], 'ry')

    def test_settings_defaults(self):
        self.assertEqual(backend.DEFAULTS['deadzone'], 8)
        self.assertEqual(backend.DEFAULTS['refresh_ms'], 50)
        self.assertFalse(backend.DEFAULTS['auto_start'])

    def test_invalid_bluetooth_mac_rejected(self):
        # Avoid invoking a system service: malformed addresses fail validation first.
        obj = object.__new__(backend.ControlCenter)
        result = obj.bluetooth_action('connect', 'not-a-mac')
        self.assertFalse(result['ok'])

if __name__ == '__main__': unittest.main()
