"""Rebuild the profile README: check production sites and draw the activity panel.

Run: python3 scripts/build.py   (needs GITHUB_TOKEN, or a logged-in `gh`)
Writes README.md, assets/activity-{light,dark}.svg and status/history.json.
Standard library only, so the workflow needs no install step.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGIN = 'nelsongallardo'
HISTORY_DAYS = 30


@dataclass(frozen=True)
class Service:
    name: str
    url: str
    about: str
    source: str | None


SERVICES = (
    Service('derabona.club', 'https://derabona.club/', 'Guess the footballer from their club career', 'https://github.com/nelsongallardo/guess-the-player'),
    Service('cuiz-ai.com', 'https://cuiz-ai.com/', 'Turns your notes into quizzes and flashcards', None),
    Service('tubesoundquiz.com', 'https://tubesoundquiz.com/', 'Which Tube line sounds like this?', 'https://github.com/nelsongallardo/tube-quiz'),
)


@dataclass(frozen=True)
class Check:
    up: bool
    code: int | None
    ms: int


def check(service: Service) -> Check:
    request = urllib.request.Request(service.url, headers={'User-Agent': f'{LOGIN}-status-check'})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            code = response.status
    except urllib.error.HTTPError as error:
        code = error.code
    except (urllib.error.URLError, TimeoutError):
        code = None
    ms = round((time.monotonic() - start) * 1000)
    return Check(up=code is not None and 200 <= code < 400, code=code, ms=ms)


# ---------- activity ----------

QUERY = '''query($login: String!) { user(login: $login) { contributionsCollection {
  restrictedContributionsCount totalPullRequestContributions
  contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }
} } }'''


def token() -> str:
    return os.environ.get('GITHUB_TOKEN') or subprocess.run(['gh', 'auth', 'token'], check=True, capture_output=True, text=True).stdout.strip()


@dataclass(frozen=True)
class Activity:
    total: int
    private: int
    pull_requests: int
    days: tuple[tuple[date, int], ...]

    @property
    def active_days(self) -> int:
        return sum(1 for _, n in self.days if n)

    @property
    def longest_streak(self) -> int:
        best = run = 0
        for _, n in self.days:
            run = run + 1 if n else 0
            best = max(best, run)
        return best

    def weeks(self) -> list[tuple[date, int]]:
        """Monday-anchored weekly totals, oldest first."""
        totals: dict[date, int] = {}
        for day, n in self.days:
            monday = day - timedelta(days=day.weekday())
            totals[monday] = totals.get(monday, 0) + n
        return sorted(totals.items())


def fetch_activity() -> Activity:
    body = json.dumps({'query': QUERY, 'variables': {'login': LOGIN}}).encode()
    request = urllib.request.Request('https://api.github.com/graphql', data=body,
                                     headers={'Authorization': f'bearer {token()}', 'User-Agent': LOGIN})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get('errors'):
        raise RuntimeError(payload['errors'])
    collection = payload['data']['user']['contributionsCollection']
    calendar = collection['contributionCalendar']
    days = tuple((date.fromisoformat(d['date']), d['contributionCount']) for w in calendar['weeks'] for d in w['contributionDays'])
    return Activity(total=calendar['totalContributions'], private=collection['restrictedContributionsCount'],
                    pull_requests=collection['totalPullRequestContributions'], days=days)


# ---------- drawing ----------

THEMES = {
    'light': dict(fg='#1f2328', muted='#59636e', faint='#d1d9e0', bar='#2da44e', peak='#1a7f37', bg='#ffffff'),
    'dark': dict(fg='#f0f6fc', muted='#9198a1', faint='#3d444d', bar='#2ea043', peak='#56d364', bg='#0d1117'),
}


def svg(activity: Activity, up: int, total_services: int, theme: str) -> str:
    c = THEMES[theme]
    width, height = 840, 270
    weeks = activity.weeks()[-52:]
    peak_week, peak = max(weeks, key=lambda w: w[1])
    share = round(100 * activity.private / activity.total) if activity.total else 0
    stats = (
        (f'{activity.total:,}', 'contributions'),
        (f'{activity.active_days}', 'active days'),
        (f'{activity.longest_streak}', 'day longest streak'),
        (f'{activity.pull_requests}', 'pull requests'),
        (f'{up}/{total_services}', 'sites up'),
    )
    font = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
    mono = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
           f'role="img" aria-label="GitHub activity, last 12 months: {activity.total} contributions on {activity.active_days} days">',
           f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="8" fill="{c["bg"]}" stroke="{c["faint"]}"/>',
           f'<text x="24" y="34" font-family="{mono}" font-size="12" fill="{c["muted"]}" letter-spacing="1">LAST 12 MONTHS</text>',
           f'<text x="{width - 24}" y="34" text-anchor="end" font-family="{mono}" font-size="12" fill="{c["muted"]}">{share}% in private repos</text>']
    column = (width - 48) / len(stats)
    for i, (value, label) in enumerate(stats):
        x = 24 + i * column
        out.append(f'<text x="{x:.0f}" y="76" font-family="{font}" font-size="30" font-weight="600" fill="{c["fg"]}">{escape(value)}</text>')
        out.append(f'<text x="{x:.0f}" y="96" font-family="{font}" font-size="13" fill="{c["muted"]}">{escape(label)}</text>')

    chart_top, chart_bottom = 146, 228
    slot = (width - 48) / len(weeks)
    out.append(f'<line x1="24" y1="{chart_bottom + .5}" x2="{width - 24}" y2="{chart_bottom + .5}" stroke="{c["faint"]}"/>')
    for i, (monday, n) in enumerate(weeks):
        x = 24 + i * slot
        h = max(2.0, (chart_bottom - chart_top) * n / peak) if n else 0
        fill, opacity = (c['peak'], 1) if monday == peak_week else (c['bar'], .55)
        if h:
            out.append(f'<rect x="{x + 1.5:.1f}" y="{chart_bottom - h:.1f}" width="{slot - 3:.1f}" height="{h:.1f}" rx="1.5" fill="{fill}" fill-opacity="{opacity}">'
                       f'<title>Week of {monday:%-d %b %Y}: {n}</title></rect>')
        if monday.day <= 7:
            out.append(f'<text x="{x + 1.5:.1f}" y="{chart_bottom + 18}" font-family="{mono}" font-size="11" fill="{c["muted"]}">{monday:%b}</text>')
        if monday == peak_week:
            tx = min(max(x + slot / 2, 24 + 60), width - 24 - 60)
            out.append(f'<text x="{tx:.1f}" y="{chart_bottom - h - 7:.1f}" text-anchor="middle" font-family="{mono}" font-size="11" fill="{c["fg"]}">'
                       f'busiest week · {n}</text>')
    out.append('</svg>')
    return '\n'.join(out) + '\n'


# ---------- status ----------

def update_history(checks: dict[str, Check], now: datetime) -> dict[str, list[list]]:
    path = ROOT / 'status' / 'history.json'
    history: dict[str, list[list]] = json.loads(path.read_text()) if path.exists() else {}
    cutoff = (now - timedelta(days=HISTORY_DAYS)).isoformat(timespec='seconds')
    for name, result in checks.items():
        rows = [row for row in history.get(name, []) if row[0] >= cutoff]
        rows.append([now.isoformat(timespec='seconds'), result.up, result.ms])
        history[name] = rows
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(history, indent=1) + '\n')
    return history


def status_table(checks: dict[str, Check], history: dict[str, list[list]]) -> str:
    lines = ['| Service | What it is | Status | Response | Uptime (30 days) |', '|---|---|---|--:|--:|']
    for service in SERVICES:
        result = checks[service.name]
        rows = history[service.name]
        uptime = 100 * sum(1 for row in rows if row[1]) / len(rows)
        state = '🟢&nbsp;Up' if result.up else ('🔴&nbsp;Down' if result.code is None else f'🔴&nbsp;HTTP&nbsp;{result.code}')
        source = f' · [code]({service.source})' if service.source else ''
        # Under a day of hourly checks, a percentage would only be noise.
        shown = f'{uptime:.1f}%' if len(rows) >= 24 else f'tracking since {datetime.fromisoformat(rows[0][0]):%-d %b}'
        lines.append(f'| [{service.name}]({service.url}) | {service.about}{source} | {state} | {result.ms:,}&nbsp;ms | {shown} |')
    return '\n'.join(lines)


def main() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    checks = {service.name: check(service) for service in SERVICES}
    history = update_history(checks, now)
    activity = fetch_activity()
    up = sum(1 for result in checks.values() if result.up)
    for theme in THEMES:
        (ROOT / 'assets' / f'activity-{theme}.svg').write_text(svg(activity, up, len(SERVICES), theme))
    template = (ROOT / 'scripts' / 'README.template.md').read_text()
    readme = (template.replace('{{STATUS_TABLE}}', status_table(checks, history))
                      .replace('{{CHECKED_AT}}', f'{now:%-d %b %Y, %H:%M} UTC'))
    (ROOT / 'README.md').write_text(readme)


if __name__ == '__main__':
    main()
