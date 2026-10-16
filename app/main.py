from pathlib import Path
import webview
from backend import ControlCenter

if __name__ == '__main__':
    bridge = ControlCenter()
    window = webview.create_window('DS4 Control Center', str(Path(__file__).resolve().parent.parent / 'index.html'), js_api=bridge, width=1440, height=940, min_size=(960, 650), background_color='#090d14')
    try: webview.start(debug=False)
    finally: bridge.shutdown()
