#!/usr/bin/env python3
"""Animated GitHub stats card for the profile README (stdlib only).

    GH_TOKEN=<token> python scripts/github_stats.py dist/github-stats.svg
    python scripts/github_stats.py --selftest

Calendar numbers (totals, streaks, growth, weekdays) include private work whenever
the profile shows private contributions. Commit hours and languages only see repos
the token can read, so a PAT with private access makes those two complete.
"""
import calendar
import html
import itertools
import json
import math
import os
import sys
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone

LOGIN = os.environ.get("GH_USER", "Ahmed-Islam-AI")
TZ = timezone(timedelta(hours=5))  # PKT; Pakistan has no DST

INK, MUTED, ACCENT, ACCENT_HI = "#FAF7F4", "#948D86", "#F15629", "#FF8A5C"
# Checked with dataviz validate_palette.js (dark, all pairs): only 3 hues pass, rest folds into Other.
LANG_COLORS, OTHER_COLOR = ["#F15629", "#3987E5", "#199E70"], "#5C5652"
SANS = "'Segoe UI Variable Display','Segoe UI',Inter,system-ui,-apple-system,Roboto,'Helvetica Neue',Arial,sans-serif"
MONO = "'JetBrains Mono','Fira Code',ui-monospace,SFMono-Regular,Consolas,'Liberation Mono',monospace"

YEAR_Q = """query($l:String!,$f:DateTime!,$t:DateTime!){user(login:$l){contributionsCollection(from:$f,to:$t){
  contributionCalendar{weeks{contributionDays{date contributionCount}}}
  commitContributionsByRepository(maxRepositories:100){contributions{totalCount}
    repository{name owner{login} primaryLanguage{name}}}}}}"""
HIST_Q = """query($o:String!,$n:String!,$id:ID!,$a:String){repository(owner:$o,name:$n){defaultBranchRef{target{
  ... on Commit{history(first:100,after:$a,author:{id:$id}){pageInfo{hasNextPage endCursor} nodes{authoredDate}}}}}}}"""


def gql(query, **variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {os.environ['GH_TOKEN']}", "User-Agent": "profile-stats-svg"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.load(r)
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"]


def fetch():
    u = gql("query($l:String!){user(login:$l){id name createdAt contributionsCollection{contributionYears}}}", l=LOGIN)["user"]
    days, langs, repos = {}, Counter(), set()
    for y in u["contributionsCollection"]["contributionYears"]:
        cc = gql(YEAR_Q, l=LOGIN, f=f"{y}-01-01T00:00:00Z", t=f"{y}-12-31T23:59:59Z")["user"]["contributionsCollection"]
        for w in cc["contributionCalendar"]["weeks"]:
            for d in w["contributionDays"]:
                days[date.fromisoformat(d["date"])] = d["contributionCount"]
        for r in cc["commitContributionsByRepository"]:
            repo = r["repository"]
            repos.add((repo["owner"]["login"], repo["name"]))
            if repo["primaryLanguage"]:
                langs[repo["primaryLanguage"]["name"]] += r["contributions"]["totalCount"]
    hours = Counter()
    for owner, name in sorted(repos):
        cursor = None
        while True:
            try:
                ref = gql(HIST_Q, o=owner, n=name, id=u["id"], a=cursor)["repository"]["defaultBranchRef"]
            except RuntimeError:
                break  # repo the token can't read
            if not ref:
                break
            hist = ref["target"]["history"]
            hours.update(datetime.fromisoformat(n["authoredDate"]).astimezone(TZ).hour for n in hist["nodes"])
            if not hist["pageInfo"]["hasNextPage"]:
                break
            cursor = hist["pageInfo"]["endCursor"]
    return u["name"] or LOGIN, date.fromisoformat(u["createdAt"][:10]), days, langs, hours, len(repos)


def streaks(counts):
    """counts: daily totals, oldest first, last = today. -> ((len, end_idx) current, (len, end_idx) longest)."""
    longest, run = (0, 0), 0
    for i, c in enumerate(counts):
        run = run + 1 if c else 0
        if run > longest[0]:
            longest = (run, i)
    end = len(counts) - 1
    if counts and not counts[-1]:
        end -= 1  # today isn't over, an empty today doesn't break the streak
    cur = 0
    while end - cur >= 0 and counts[end - cur]:
        cur += 1
    return (cur, end), longest


def nice(m):
    step = 10 ** (len(str(int(m))) - 1)
    return max(step, math.ceil(m / step) * step)


def fmt(d, year=True):
    return f"{d:%b} {d.day}, {d.year}" if year else f"{d:%b} {d.day}"


def pt(cx, cy, r, frac):  # frac of a full turn, clockwise from 12 o'clock
    a = 2 * math.pi * frac - math.pi / 2
    return cx + r * math.cos(a), cy + r * math.sin(a)


_ids = itertools.count()
LOOP = 12  # seconds; the intro replays so the card is moving whenever someone scrolls to it
_frames = []


def loop(frm, to, delay, dur, ease="cubic-bezier(.2,.8,.2,1)"):
    """Inline style: hold `frm`, ease to `to` at `delay`, hold, rewind in the last .8s, repeat every LOOP s.
    `to` is also the static style, so renderers without CSS animation show the finished card."""
    name = f"k{len(_frames)}"
    a, b, c = (100 * t / LOOP for t in (delay, delay + dur, LOOP - .8))
    _frames.append(f"@keyframes {name}{{0%,{a:.2f}%{{{frm};animation-timing-function:{ease}}}"
                   f"{b:.2f}%,{c:.2f}%{{{to};animation-timing-function:cubic-bezier(.5,0,.75,0)}}100%{{{frm}}}}}")
    return f"{to};animation:{name} {LOOP}s infinite"


FADE = ("opacity:0", "opacity:1")


def roll(x, y, value, size, delay, anchor="start"):
    """Odometer-style number: each digit column spins up to its value."""
    text = f"{value:,}"
    widths = [size * (0.3 if ch == "," else 0.6) for ch in text]
    total, lh = sum(widths), size * 1.25
    cx = x - (total / 2 if anchor == "middle" else 0)
    cid = f"r{next(_ids)}"
    out = [f'<clipPath id="{cid}"><rect x="{cx - 4:.1f}" y="{y - size * .86:.1f}" width="{total + 8:.1f}" height="{size * 1.06:.1f}"/></clipPath>'
           f'<g clip-path="url(#{cid})" class="num" font-size="{size}">']
    for i, (ch, w) in enumerate(zip(text, widths)):
        mid = cx + w / 2
        if ch == ",":
            out.append(f'<text x="{mid:.1f}" y="{y}">,</text>')
        else:
            d = int(ch)
            col = "".join(f'<text x="{mid:.1f}" y="{y + k * lh:.1f}">{k % 10}</text>' for k in range(11 + d))
            style = loop("transform:translateY(0)", f"transform:translateY(-{(10 + d) * lh:.1f}px)", delay + i * .07, 1.7)
            out.append(f'<g style="{style}">{col}</g>')
        cx += w
    out.append("</g>")
    return "".join(out), total


def card(x, y, w, h, title=None, sub=None, featured=False):
    stroke = 'stroke="url(#edge)" stroke-width="1.4"' if featured else 'stroke="#FFFFFF" stroke-opacity=".08"'
    s = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="20" fill="#FFFFFF" fill-opacity=".035" {stroke}/>'
    if title:
        s += f'<text x="{x + 28}" y="{y + 40}" font-size="19" font-weight="700" fill="{INK}">{title}</text>'
    if sub:
        s += f'<text x="{x + 28}" y="{y + 62}" class="mono" font-size="13" fill="{MUTED}">{sub}</text>'
    return s


def render(name, created, days, langs, hours, n_repos, today):
    start = min(days)
    span = [start + timedelta(i) for i in range((today - start).days + 1)]
    counts = [days.get(d, 0) for d in span]
    total = sum(counts)
    (cur, cur_end), (best, best_end) = streaks(counts)
    o = []

    # ── header ──
    o.append(f'<text x="40" y="58" font-size="26" font-weight="800" fill="{INK}" letter-spacing="-.4">GitHub Telemetry</text>'
             f'<text x="40" y="83" class="mono" font-size="14" fill="{MUTED}"><tspan fill="{ACCENT}">$</tspan> '
             f'git stats --author={LOGIN.lower()} --since={created.year}</text>'
             f'<rect x="916" y="38" width="244" height="30" rx="15" fill="{ACCENT}" fill-opacity=".1" stroke="{ACCENT}" stroke-opacity=".45"/>'
             f'<circle cx="936" cy="53" r="4" fill="{ACCENT}" class="pulse"/>'
             f'<text x="949" y="57.5" class="mono" font-size="13" fill="{INK}">live · synced {today.day} {today:%b %Y}</text>')

    # ── row 1: total · current streak · longest streak ──
    o.append(card(40, 104, 300, 186))
    o.append(f'<text x="68" y="146" font-size="16" font-weight="600" fill="{MUTED}">Total contributions</text>')
    o.append(roll(68, 222, total, 64, .2)[0])
    o.append(f'<text x="68" y="262" font-size="15" font-weight="600" fill="{ACCENT}">since {fmt(created)}</text>')

    o.append(card(360, 104, 480, 186, featured=True))
    cx, cy, r = 472, 197, 60
    ratio = min(1, cur / best) if best else 0
    o.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#FFFFFF" stroke-opacity=".08" stroke-width="10"/>'
             f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="url(#ring)" stroke-width="10" stroke-linecap="round" '
             f'pathLength="100" stroke-dasharray="100" transform="rotate(-90 {cx} {cy})" filter="url(#glow)" '
             f'style="{loop("stroke-dashoffset:100", f"stroke-dashoffset:{100 * (1 - ratio):.2f}", .4, 1.8)}"/>')
    if 0 < ratio < 1:
        ex, ey = pt(cx, cy, r, ratio)
        o.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4.5" fill="{INK}" style="{loop(*FADE, 2.2, .4)}"/>')
    o.append(f'<circle r="3.5" fill="#FFFFFF" filter="url(#glow)" class="amb" style="{loop(*FADE, 2.2, .5)}">'
             f'<animateMotion dur="5s" repeatCount="indefinite" path="M{cx},{cy - r}a{r},{r} 0 1,1 -.01,0"/></circle>')
    o.append(roll(cx, 212, cur, 44, .4, "middle")[0])
    o.append(f'<text x="{cx}" y="238" text-anchor="middle" font-size="13" font-weight="600" fill="{MUTED}">days</text>')
    if cur:
        a, b = span[cur_end - cur + 1], span[cur_end]
        when = f'{fmt(a, False)} → {"today" if b == today else fmt(b, False)}'
        status = "Personal best, still going" if cur >= best else f"{round(100 * cur / best)}% of the {best}-day record"
    else:
        when, status = "No active streak", "Next commit starts a new one"
    o.append(f'<text x="574" y="170" font-size="22" font-weight="700" fill="{INK}">Current streak</text>'
             f'<text x="574" y="200" font-size="16" font-weight="600" fill="{ACCENT}">{when}</text>'
             f'<text x="574" y="228" font-size="15" fill="{MUTED}">{status}</text>')

    o.append(card(860, 104, 300, 186))
    o.append(f'<text x="888" y="146" font-size="16" font-weight="600" fill="{MUTED}">Longest streak</text>')
    s, w = roll(888, 222, best, 64, .6)
    o.append(s + f'<text x="{888 + w + 10:.1f}" y="222" font-size="20" font-weight="600" fill="{MUTED}">days</text>')
    if best:
        a, b = span[best_end - best + 1], span[best_end]
        o.append(f'<text x="888" y="262" font-size="15" font-weight="600" fill="{ACCENT}">{fmt(a, a.year != b.year)} → {fmt(b)}</text>')

    # ── row 2a: ship clock (commits by hour, radial) ──
    o.append(card(40, 310, 420, 250, "Ship clock", "commits by hour · PKT"))
    cx, cy, r0, r1 = 345, 442, 34, 78
    hmax = max(hours.values(), default=0) or 1
    peak = max(range(24), key=lambda s: sum(hours[(s + i) % 24] for i in range(3)))
    in_peak = {(peak + i) % 24 for i in range(3)}
    o.append(f'<circle cx="{cx}" cy="{cy}" r="{r0}" fill="none" stroke="#FFFFFF" stroke-opacity=".1"/>'
             f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" class="mono" font-size="12" fill="{MUTED}">24h</text>')
    (ix, iy), (ox, oy), (hx, hy), (jx, jy) = (pt(cx, cy, rr, f) for rr, f in ((r0 + 2, -1 / 12), (r1 + 2, -1 / 12), (r1 + 2, 0), (r0 + 2, 0)))
    o.append(f'<g class="spin" style="transform-origin:{cx}px {cy}px">'  # radar sweep
             f'<path d="M{ix:.1f} {iy:.1f}L{ox:.1f} {oy:.1f}A{r1 + 2} {r1 + 2} 0 0 1 {hx:.1f} {hy:.1f}L{jx:.1f} {jy:.1f}'
             f'A{r0 + 2} {r0 + 2} 0 0 0 {ix:.1f} {iy:.1f}Z" fill="url(#sweep)"/>'
             f'<line x1="{jx:.1f}" y1="{jy:.1f}" x2="{hx:.1f}" y2="{hy:.1f}" stroke="{ACCENT_HI}" stroke-opacity=".7" stroke-width="1.5" stroke-linecap="round"/></g>')
    for h in range(24):
        f = (h + .5) / 24
        (x1, y1), (x2, y2) = pt(cx, cy, r0 + 6, f), pt(cx, cy, r1, f)
        o.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#FFFFFF" stroke-opacity=".045" stroke-width="7" stroke-linecap="round"/>')
        if hours[h]:
            xe, ye = pt(cx, cy, r0 + 6 + (r1 - r0 - 6) * hours[h] / hmax, f)
            paint = f'stroke="url(#hot)"' if h in in_peak else f'stroke="{ACCENT}" stroke-opacity=".45"'
            o.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{xe:.1f}" y2="{ye:.1f}" {paint} stroke-width="7" stroke-linecap="round" '
                     f'pathLength="1" stroke-dasharray="1" style="{loop("stroke-dashoffset:1", "stroke-dashoffset:0", .8 + h * .03, .7)}"/>')
    (ax, ay), (bx, by) = pt(cx, cy, r1 + 9, peak / 24), pt(cx, cy, r1 + 9, (peak + 3) / 24)
    o.append(f'<path d="M{ax:.1f} {ay:.1f}A{r1 + 9} {r1 + 9} 0 0 1 {bx:.1f} {by:.1f}" fill="none" stroke="{ACCENT_HI}" stroke-width="2" '
             f'stroke-linecap="round" style="{loop(*FADE, 1.8, .6)}"/>')
    for lbl, f, dy in (("00", 0, 4), ("06", .25, 4), ("12", .5, 8), ("18", .75, 4)):
        lx, ly = pt(cx, cy, r1 + 22, f)
        o.append(f'<text x="{lx:.1f}" y="{ly + dy - (4 if f == 0 else 0):.1f}" text-anchor="middle" class="mono" font-size="13" fill="{MUTED}">{lbl}</text>')
    buckets = {"Night owl": [22, 23, 0, 1, 2, 3, 4], "Early bird": [5, 6, 7, 8, 9],
               "Day shipper": list(range(10, 17)), "Evening coder": list(range(17, 22))}
    persona = max(buckets, key=lambda k: sum(hours[h] for h in buckets[k]) / len(buckets[k])) if hours else "No data yet"
    o.append(f'<text x="68" y="434" font-size="26" font-weight="800" fill="{INK}" letter-spacing="-.3">{persona}</text>'
             f'<text x="68" y="462" class="mono" font-size="14" fill="{ACCENT}">peak {peak:02d}:00–{(peak + 3) % 24:02d}:00</text>'
             f'<text x="68" y="530" font-size="14" fill="{MUTED}">{sum(hours.values()):,} commits sampled</text>')

    # ── row 2b: growth trajectory (contributions per month) ──
    ym = [(created.year, created.month)]
    while ym[-1] != (today.year, today.month):
        y, m = ym[-1]
        ym.append((y + m // 12, m % 12 + 1))
    monthly = Counter()
    for d, c in zip(span, counts):
        monthly[(d.year, d.month)] += c
    vals = [monthly[k] for k in ym]
    this_year = sum(v for (y, _), v in monthly.items() if y == today.year)
    last_year = sum(v for (y, _), v in monthly.items() if y == today.year - 1)
    o.append(card(480, 310, 680, 250, "Growth trajectory", "contributions per month"))
    o.append(f'<text x="1132" y="350" text-anchor="end" font-size="19" font-weight="700" fill="{INK}">{this_year:,} in {today.year}</text>')
    if last_year:
        mult = this_year / last_year
        o.append(f'<text x="1132" y="372" text-anchor="end" class="mono" font-size="13" fill="{ACCENT}">'
                 f'{"↑" if mult >= 1 else "↓"} {mult:.1f}× vs {today.year - 1}</text>')
    x0, x1, y0, y1 = 548, 1132, 400, 520
    top = nice(max(vals))
    for t in (0, top // 2, top):
        gy = y1 - t / top * (y1 - y0)
        o.append(f'<line x1="{x0}" y1="{gy:.1f}" x2="{x1}" y2="{gy:.1f}" stroke="#FFFFFF" stroke-opacity="{.14 if t == 0 else .05}"/>'
                 f'<text x="{x0 - 10}" y="{gy + 4:.1f}" text-anchor="end" class="mono" font-size="13" fill="{MUTED}">{t:,}</text>')
    step = (x1 - x0) / max(1, len(vals) - 1)
    pts = [(x0 + i * step, y1 - v / top * (y1 - y0)) for i, v in enumerate(vals)]
    line = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
    o.append(f'<path d="M{x0},{y1} L{line} L{pts[-1][0]:.1f},{y1}Z" fill="url(#area)" style="{loop(*FADE, 1.6, 1)}"/>'
             f'<polyline points="{line}" fill="none" stroke="{ACCENT}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" '
             f'pathLength="1" stroke-dasharray="1" style="{loop("stroke-dashoffset:1", "stroke-dashoffset:0", .5, 1.8, "cubic-bezier(.4,0,.2,1)")}"/>'
             f'<circle r="3.5" fill="#FFD9C7" filter="url(#glow)" class="amb" style="{loop(*FADE, 2.3, .5)}">'  # comet riding the line
             f'<animateMotion dur="6s" repeatCount="indefinite" path="M{line.replace(" ", " L")}"/></circle>')
    for i, (y, m) in enumerate(ym):
        if i == 0 or (m == 1 and i * step > 40):
            o.append(f'<text x="{x0 + i * step:.1f}" y="540" text-anchor="{"start" if i == 0 else "middle"}" class="mono" font-size="13" '
                     f'fill="{MUTED}">{f"{calendar.month_abbr[m]} ’{y % 100:02d}" if i == 0 else y}</text>')
    pi = max(range(len(vals)), key=vals.__getitem__)
    (px, py), (lx, ly) = pts[pi], pts[-1]
    pm = ym[pi]
    o.append(f'<g style="{loop(*FADE, 2.2, .6)}">'
             f'<circle cx="{px:.1f}" cy="{py:.1f}" r="5" fill="{ACCENT_HI}" stroke="#1A1A1A" stroke-width="2"/>'
             f'<text x="{min(max(px, x0 + 60), x1 - 60):.1f}" y="{py - 14:.1f}" text-anchor="middle" font-size="14" font-weight="600" fill="{INK}">'
             f'{calendar.month_abbr[pm[1]]} ’{pm[0] % 100:02d} · {vals[pi]:,}</text></g>')
    if pi != len(vals) - 1:
        o.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="4" fill="{ACCENT}" stroke="#1A1A1A" stroke-width="2" style="{loop(*FADE, 2.2, .6)}"/>')

    # ── row 3a: weekly rhythm ──
    week = [0] * 7
    for d, c in zip(span, counts):
        week[d.weekday()] += c
    wmax = max(week) or 1
    busiest = max(range(7), key=week.__getitem__)
    o.append(card(40, 580, 560, 220, "Weekly rhythm", "all contributions by weekday"))
    o.append(f'<text x="572" y="620" text-anchor="end" font-size="15" font-weight="600" fill="{INK}">Busiest: {calendar.day_name[busiest]}</text>'
             f'<text x="572" y="642" text-anchor="end" class="mono" font-size="13" fill="{MUTED}">weekend {round(100 * (week[5] + week[6]) / (total or 1))}%</text>'
             f'<line x1="68" y1="755" x2="572" y2="755" stroke="#FFFFFF" stroke-opacity=".14"/>')
    for i, v in enumerate(week):
        bx, bh = 68 + i * 72 + 16, max(3, 84 * v / wmax)
        paint = 'fill="url(#hotV)"' if i == busiest else f'fill="{ACCENT}" fill-opacity=".4"'
        if i == busiest:  # breathing glow behind the busiest day
            o.append(f'<g style="{loop(*FADE, 1.8, .5)}"><rect x="{bx}" y="{755 - bh:.1f}" width="40" height="{bh:.1f}" rx="4" '
                     f'fill="{ACCENT}" filter="url(#glow)" class="pulse"/></g>')
        o.append(f'<rect class="grow" x="{bx}" y="{755 - bh:.1f}" width="40" height="{bh:.1f}" rx="4" {paint} '
                 f'style="{loop("transform:scaleY(0)", "transform:scaleY(1)", 1 + i * .06, .8)}"/>'
                 f'<text x="{bx + 20}" y="778" text-anchor="middle" class="mono" font-size="13" fill="{INK if i == busiest else MUTED}">{calendar.day_abbr[i]}</text>')
        if i == busiest:
            o.append(f'<text x="{bx + 20}" y="{755 - bh - 9:.1f}" text-anchor="middle" font-size="14" font-weight="600" fill="{INK}" '
                     f'style="{loop(*FADE, 1.6, .5)}">{v:,}</text>')

    # ── row 3b: languages by commit ──
    commits = sum(langs.values())
    rows = [(lang, n, LANG_COLORS[i]) for i, (lang, n) in enumerate(langs.most_common(3))]
    if commits - sum(n for _, n, _ in rows):
        rows.append(("Other", commits - sum(n for _, n, _ in rows), OTHER_COLOR))
    o.append(card(620, 580, 540, 220, "Languages by commit", f"{commits:,} commits across {n_repos} repos"))
    cx, cy, r = 1050, 712, 64
    gap, acc = 200 / (2 * math.pi * r), 0.0  # 2px gap in pathLength=100 units
    for i, (lang, n, color) in enumerate(rows):
        share = 100 * n / commits
        ry = 682 + i * 30
        o.append(f'<circle cx="654" cy="{ry - 5.5}" r="5.5" fill="{color}"/>'
                 f'<text x="670" y="{ry}" font-size="16" fill="{INK}">{html.escape(lang)}</text>'
                 f'<text x="900" y="{ry}" text-anchor="end" font-size="16" font-weight="600" fill="{MUTED}">{round(share)}%</text>'
                 f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="18" pathLength="100" '
                 f'stroke-dashoffset="{-(acc + gap / 2):.2f}" transform="rotate(-90 {cx} {cy})" '
                 f'style="{loop("stroke-dasharray:0 100", f"stroke-dasharray:{max(0, share - gap):.2f} 100", 1.2 + i * .25, .6, "ease-out")}"/>')
        acc += share
    if rows:
        o.append(f'<g style="{loop(*FADE, 2.2, .6)}">'
                 f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" font-size="26" font-weight="800" class="numfill">{round(100 * rows[0][1] / commits)}%</text>'
                 f'<text x="{cx}" y="{cy + 24}" text-anchor="middle" font-size="12" fill="{MUTED}">{html.escape(rows[0][0])}</text></g>')

    desc = (f"{total:,} contributions since {fmt(created)}. Current streak {cur} days, longest {best} days. "
            f"Peak commit hours {peak:02d}:00 to {(peak + 3) % 24:02d}:00 PKT ({persona}). "
            f"{this_year:,} contributions in {today.year}. Busiest day {calendar.day_name[busiest]}. "
            f"Top languages by commit: {', '.join(f'{l} {round(100 * n / commits)}%' for l, n, _ in rows)}.")
    return SVG.format(name=html.escape(name), desc=html.escape(desc), sans=SANS, mono=MONO, frames="\n".join(_frames), body="\n".join(o))


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 830" width="1200" height="830" role="img" aria-labelledby="t d">
<title id="t">GitHub stats for {name}</title>
<desc id="d">{desc}</desc>
<style>
text{{font-family:{sans};font-variant-numeric:tabular-nums}}
.mono{{font-family:{mono}}}
.num text{{font-weight:800;text-anchor:middle;fill:url(#numfill)}}
.numfill{{fill:url(#numfill)}}
.grow{{transform-box:fill-box;transform-origin:50% 100%}}
.pulse{{animation:pulse 2.4s ease-in-out infinite}}
.spin{{animation:spin 7s linear infinite}}
@keyframes pulse{{50%{{opacity:.25}}}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
{frames}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important}}.amb{{display:none}}}}
</style>
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0B0B0B"/><stop offset="1" stop-color="#141210"/></linearGradient>
<radialGradient id="glowA" cx=".1" cy="0" r=".6"><stop offset="0" stop-color="#F15629" stop-opacity=".2"/><stop offset="1" stop-color="#F15629" stop-opacity="0"/></radialGradient>
<radialGradient id="glowB" cx=".95" cy="1" r=".5"><stop offset="0" stop-color="#F15629" stop-opacity=".09"/><stop offset="1" stop-color="#F15629" stop-opacity="0"/></radialGradient>
<pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1" fill="#FFFFFF" fill-opacity=".045"/></pattern>
<linearGradient id="numfill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF"/><stop offset="1" stop-color="#EBDDD2"/></linearGradient>
<linearGradient id="ring" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FFB38F"/><stop offset=".5" stop-color="#F15629"/><stop offset="1" stop-color="#C7401A"/></linearGradient>
<linearGradient id="edge" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#F15629" stop-opacity=".75"/><stop offset=".5" stop-color="#F15629" stop-opacity=".15"/><stop offset="1" stop-color="#FF8A5C" stop-opacity=".6"/></linearGradient>
<linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F15629" stop-opacity=".35"/><stop offset="1" stop-color="#F15629" stop-opacity="0"/></linearGradient>
<linearGradient id="hot" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="830"><stop offset="0" stop-color="#FF8A5C"/><stop offset="1" stop-color="#F15629"/></linearGradient>
<linearGradient id="sweep" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#F15629" stop-opacity="0"/><stop offset="1" stop-color="#F15629" stop-opacity=".3"/></linearGradient>
<linearGradient id="hotV" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FF8A5C"/><stop offset="1" stop-color="#F15629"/></linearGradient>
<filter id="glow" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<clipPath id="frame"><rect width="1200" height="830" rx="28"/></clipPath>
</defs>
<g clip-path="url(#frame)">
<rect width="1200" height="830" fill="url(#bg)"/><rect width="1200" height="830" fill="url(#dots)"/>
<rect width="1200" height="830" fill="url(#glowA)"/><rect width="1200" height="830" fill="url(#glowB)"/>
</g>
<rect x=".5" y=".5" width="1199" height="829" rx="28" fill="none" stroke="#FFFFFF" stroke-opacity=".08"/>
{body}
</svg>
"""


def selftest():
    assert streaks([1, 1, 0, 1, 1, 1, 0]) == ((3, 5), (3, 5))  # empty today keeps yesterday's streak
    assert streaks([1, 0, 1, 1]) == ((2, 3), (2, 3))
    assert streaks([2, 2, 2, 0, 1, 0, 0]) == ((0, 5), (3, 2))  # missed yesterday -> broken
    assert streaks([0, 0]) == ((0, 0), (0, 0))
    assert nice(312) == 400 and nice(0) == 1 and nice(7) == 7 and nice(1663) == 2000
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    else:
        out = sys.argv[1]
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        svg = render(*fetch(), today=datetime.now(TZ).date())
        with open(out, "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"wrote {out}")
