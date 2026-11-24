"""Export album.html to assets/sticker-album.png at 2x. Needs playwright-cli on PATH."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from subprocess import run
from sys import argv
from threading import Thread

root = Path(__file__).resolve().parent
out = Path(argv[1]).resolve() if len(argv) > 1 else root / 'assets' / 'sticker-album.png'
out.parent.mkdir(parents=True, exist_ok=True)
cli = ['playwright-cli', '-s=figuritas-export']

# A static image can't be clicked, so the bonus points at the README text instead of "Flip it".
code = f'''async page => {{
  await page.setViewportSize({{width: 2000, height: 1200}});
  await page.evaluate(() => {{
    document.body.style.margin = '0';
    const album = document.querySelector('.album');
    album.style.width = '960px';
    album.style.zoom = '2';
    document.querySelector('.bonus details').outerHTML = '<b style="display:block;white-space:nowrap">Answer below ↓</b>';
  }});
  await page.evaluate(() => document.fonts.ready);
  await page.locator('.album').screenshot({{path: {str(out)!r}, omitBackground: true}});
  return await page.evaluate(() => {{ const r = document.querySelector('.album').getBoundingClientRect(); return [r.width, r.height]; }});
}}'''

with ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(root))) as server:
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        run([*cli, 'open', f'http://127.0.0.1:{server.server_port}/album.html'], cwd=root, check=True, capture_output=True)
        result = run([*cli, 'run-code', code], cwd=root, check=True, capture_output=True, text=True)
        assert '### Error' not in result.stdout, result.stdout
        print(result.stdout.split('### Ran')[0].strip())
    finally:
        run([*cli, 'close'], cwd=root, capture_output=True)
        server.shutdown()
