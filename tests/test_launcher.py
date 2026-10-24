"""Exercise the real launcher without opening a window or requiring GUI libraries."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class LauncherTests(unittest.TestCase):
    def launch(self, overrides=None):
        with tempfile.TemporaryDirectory(prefix='ds4 launcher ') as tmp:
            root = Path(tmp)
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'run.sh', root / 'run.sh')
            interpreter = root / 'fake-python'
            interpreter.write_text(
                '#!%s\n' % sys.executable +
                'import json, os, sys\n'
                'if sys.argv[1:2] != ["-c"]:\n'
                '    print(json.dumps({"env": dict(os.environ), "args": sys.argv[1:]}))\n'
            )
            interpreter.chmod(0o755)
            env = dict(os.environ, PYTHON=str(interpreter))
            for key in ('PYWEBVIEW_GUI', 'WEBKIT_DISABLE_COMPOSITING_MODE',
                        'WEBKIT_DISABLE_DMABUF_RENDERER', 'QTWEBENGINE_DISABLE_SANDBOX',
                        'QTWEBENGINE_CHROMIUM_FLAGS'):
                env.pop(key, None)
            env.update(overrides or {})
            result = subprocess.run(['bash', str(root / 'run.sh'), '--debug'],
                                    env=env, text=True, capture_output=True, check=True)
            return json.loads(result.stdout)

    def test_default_backend_matches_installed_gtk_dependencies(self):
        result = self.launch()
        self.assertEqual(result['env']['PYWEBVIEW_GUI'], 'gtk')
        self.assertEqual(result['env']['WEBKIT_DISABLE_COMPOSITING_MODE'], '1')
        self.assertEqual(result['env']['WEBKIT_DISABLE_DMABUF_RENDERER'], '1')
        self.assertNotIn('QTWEBENGINE_DISABLE_SANDBOX', result['env'])
        self.assertNotIn('QTWEBENGINE_CHROMIUM_FLAGS', result['env'])
        self.assertTrue(result['args'][0].endswith('/app/main.py'))
        self.assertEqual(result['args'][1:], ['--debug'])

    def test_explicit_backend_and_graphics_options_are_preserved(self):
        overrides = {
            'PYWEBVIEW_GUI': 'qt',
            'WEBKIT_DISABLE_COMPOSITING_MODE': '0',
            'WEBKIT_DISABLE_DMABUF_RENDERER': '0',
            'QTWEBENGINE_CHROMIUM_FLAGS': '--disable-gpu',
        }
        result = self.launch(overrides)
        for key, value in overrides.items():
            self.assertEqual(result['env'][key], value)
        self.assertNotIn('QTWEBENGINE_DISABLE_SANDBOX', result['env'])


if __name__ == '__main__':
    unittest.main()
