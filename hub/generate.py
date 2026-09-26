#!/usr/bin/env python3
"""Render hub.svg, a CheckMyGit-style card for a GitHub profile README.

Pulls public profile data from the GitHub GraphQL API and draws it as one
self-contained SVG: avatar sidebar, welcome banner, stat tiles, contribution
heatmap, tech stack and a language donut. The font (Geist, subset) and the
avatar are embedded, so the card looks the same wherever GitHub shows it.

    GITHUB_TOKEN=<token> python hub/generate.py [-o hub/dist/hub.svg]

Settings live in hub/config.json next to this file.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import io
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools import subset
from fontTools.ttLib import TTFont

HERE = Path(__file__).resolve().parent
FONT_URL = "https://cdn.jsdelivr.net/npm/@fontsource/geist-sans@5.3.0/files/geist-sans-latin-{}-normal.woff2"
WEIGHTS = (400, 500, 600, 700)
ASCENT, DESCENT = 0.92, 0.22  # Geist's hhea metrics, in em

# CheckMyGit's dark palette. The greens are sampled from the screenshot in the
# r/coolgithubprojects post this card is modelled on.
PAGE, CARD, RAISED, BORDER = "#030303", "#0a0a0a", "#1a1a1a", "#222222"
TEXT, TEXT2, TEXT3, ACCENT = "#ededed", "#a1a1a1", "#666666", "#52a44e"
HEAT = ("#171b21", "#1f432b", "#2e6b38", "#52a44e", "#6cd064")
LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}

# Card geometry: 846px is the width of a profile README on desktop.
W, PAD, GUTTER, SIDE_W, AVATAR = 846, 24, 24, 240, 200

# Brand colours for tech chips; languages fall back to GitHub's linguist colours.
TECH_COLORS = {
    "angular": "#DD0031", "aws": "#FF9900", "c": "#555555", "c#": "#178600", "c++": "#F34B7D",
    "css": "#663399", "dart": "#00B4AB", "django": "#44B78B", "docker": "#2496ED",
    "express": "#EDEDED", "fastapi": "#009688", "figma": "#F24E1E", "firebase": "#FFCA28",
    "flutter": "#54C5F8", "git": "#F05032", "go": "#00ADD8", "graphql": "#E10098",
    "html": "#E34C26", "java": "#B07219", "javascript": "#F1E05A", "kotlin": "#A97BFF",
    "laravel": "#FF2D20", "mongodb": "#47A248", "mysql": "#4479A1", "nestjs": "#E0234E",
    "next.js": "#EDEDED", "nginx": "#009639", "node.js": "#5FA04E", "php": "#4F5D95",
    "postgresql": "#4169E1", "prisma": "#5A67D8", "python": "#3572A5", "react": "#61DAFB",
    "react native": "#61DAFB", "redis": "#DC382D", "riverpod": "#45D2B0", "rust": "#DEA584",
    "socket.io": "#EDEDED", "sqlite": "#0F80CC", "supabase": "#3ECF8E", "svelte": "#FF3E00",
    "swift": "#F05138", "tailwind css": "#38BDF8", "typescript": "#3178C6", "vue": "#41B883",
}

# Heroicons (outline) and Octicons (filled), as used by CheckMyGit: (viewBox, style, paths)
ICONS = {
    "folder": (24, "stroke", ["M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"]),
    "star": (24, "stroke", ["M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"]),
    "users": (24, "stroke", ["M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"]),
    "clock": (24, "stroke", ["M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"]),
    "bolt": (24, "stroke", ["M13 10V3L4 14h7v7l9-11h-7z"]),
    "code": (24, "stroke", ["M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"]),
    "chart": (24, "stroke", ["M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"]),
    "calendar": (24, "stroke", ["M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"]),
    "office": (24, "stroke", ["M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"]),
    "pin": (24, "stroke", ["M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z", "M15 11a3 3 0 11-6 0 3 3 0 016 0z"]),
    "link": (24, "stroke", ["M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"]),
    "x": (24, "fill", ["M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"]),
    "people": (16, "fill", ["M2 5.5a3.5 3.5 0 115.898 2.549 5.507 5.507 0 013.034 4.084.75.75 0 11-1.482.235 4.001 4.001 0 00-7.9 0 .75.75 0 01-1.482-.236A5.507 5.507 0 013.102 8.05 3.49 3.49 0 012 5.5zM11 4a.75.75 0 100 1.5 1.5 1.5 0 01.666 2.844.75.75 0 00-.416.672v.352a.75.75 0 00.574.73c1.2.289 2.162 1.2 2.522 2.372a.75.75 0 101.434-.44 5.01 5.01 0 00-2.56-3.012A3 3 0 0011 4z"]),
    "github": (16, "fill", ["M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"]),
}

QUERY = """
query($login: String!) {
  user(login: $login) {
    login name bio avatarUrl company location websiteUrl twitterUsername createdAt
    followers { totalCount }
    following { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC,
                 orderBy: {field: STARGAZERS, direction: DESC}) {
      totalCount
      nodes {
        isFork stargazerCount
        languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date weekday contributionLevel } }
      }
    }
  }
}
"""


@dataclass
class Language:
    name: str
    color: str
    size: int
    percent: int = 0


@dataclass
class Profile:
    login: str
    name: str | None
    bio: str | None
    avatar_url: str
    company: str | None
    location: str | None
    website: str | None
    twitter: str | None
    created: dt.datetime
    followers: int
    following: int
    repos: int
    stars: int
    languages: list[Language]
    contributions: int
    weeks: list[list[dict]]

    @property
    def years(self) -> int:
        days = (dt.datetime.now(dt.timezone.utc) - self.created).days
        return max(1, round(days / 365))


# ---------------------------------------------------------------- data


def http_get(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "profile-hub"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read(), res.headers.get_content_type()


def fetch_profile(login: str, token: str) -> Profile:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": login}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "profile-hub"},
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        payload = json.load(res)
    if payload.get("errors") or not (payload.get("data") or {}).get("user"):
        sys.exit("GitHub API error: " + "; ".join(e["message"] for e in payload.get("errors", [])))
    u = payload["data"]["user"]
    repos = u["repositories"]["nodes"]

    # Language bytes across original (non-fork) repos, the way CheckMyGit counts them.
    sizes: dict[str, Language] = {}
    for repo in repos:
        if repo["isFork"]:
            continue
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            lang = sizes.setdefault(name, Language(name, edge["node"]["color"] or "#8b949e", 0))
            lang.size += edge["size"]
    languages = sorted(sizes.values(), key=lambda lang: -lang.size)
    total = sum(lang.size for lang in languages)
    for lang in languages:
        lang.percent = round(lang.size / total * 100) if total else 0
    if languages:  # top ten add up to 100, as on CheckMyGit
        languages[0].percent += 100 - sum(lang.percent for lang in languages[:10])

    cal = u["contributionsCollection"]["contributionCalendar"]
    return Profile(
        login=u["login"], name=u["name"], bio=u["bio"], avatar_url=u["avatarUrl"],
        company=u["company"], location=u["location"], website=u["websiteUrl"],
        twitter=u["twitterUsername"],
        created=dt.datetime.fromisoformat(u["createdAt"].replace("Z", "+00:00")),
        followers=u["followers"]["totalCount"], following=u["following"]["totalCount"],
        repos=u["repositories"]["totalCount"], stars=sum(r["stargazerCount"] for r in repos),
        languages=languages, contributions=cal["totalContributions"],
        weeks=[w["contributionDays"] for w in cal["weeks"]],
    )


# ---------------------------------------------------------------- type & drawing


class Fonts:
    """Geist at four weights: advance widths for layout, subsets for embedding."""

    def __init__(self, cache: Path):
        cache.mkdir(parents=True, exist_ok=True)
        self.raw: dict[int, bytes] = {}
        self.advance: dict[int, dict[int, int]] = {}
        for weight in WEIGHTS:
            path = cache / f"geist-{weight}.woff2"
            if not path.exists():
                path.write_bytes(http_get(FONT_URL.format(weight))[0])
            self.raw[weight] = path.read_bytes()
            font = TTFont(io.BytesIO(self.raw[weight]))
            hmtx = font["hmtx"].metrics
            self.advance[weight] = {cp: hmtx[glyph][0] for cp, glyph in font.getBestCmap().items()}

    def width(self, text: str, size: float, weight: int = 400, tracking: float = 0.0) -> float:
        adv = self.advance[weight]
        units = sum(adv.get(ord(ch), adv[ord("n")]) for ch in text)
        return (units / 1000 + tracking * len(text)) * size

    def fit(self, text: str, size: float, weight: int, max_width: float) -> float:
        """Shrink the font size until the text fits (never below 75%)."""
        width = self.width(text, size, weight)
        return size if width <= max_width else max(size * 0.75, size * max_width / width)

    def wrap(self, text: str, size: float, weight: int, max_width: float) -> list[str]:
        lines: list[str] = []
        for word in text.split():
            if lines and self.width(f"{lines[-1]} {word}", size, weight) <= max_width:
                lines[-1] += f" {word}"
            else:
                lines.append(word)
        return lines

    def embed(self, weight: int, chars: set[str]) -> str:
        font = TTFont(io.BytesIO(self.raw[weight]), recalcTimestamp=False)
        options = subset.Options()
        options.desubroutinize = True
        subsetter = subset.Subsetter(options)
        subsetter.populate(text="".join(sorted(chars)))
        subsetter.subset(font)
        font.flavor = "woff2"
        buf = io.BytesIO()
        font.save(buf)
        return base64.b64encode(buf.getvalue()).decode()


def baseline(top: float, line_height: float, size: float) -> float:
    """Baseline of a line box, placed the way CSS centres text in its line height."""
    return top + (line_height - size * (ASCENT + DESCENT)) / 2 + size * ASCENT


def attr(value: str) -> str:
    return escape(value, {'"': "&quot;"})


def legible(color: str, background: str = CARD, target: float = 4.5) -> str:
    """Lighten a brand colour until it reads on the dark card (WCAG contrast)."""
    def luminance(rgb: tuple[float, ...]) -> float:
        lin = [c / 255 for c in rgb]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in lin]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    rgb = tuple(int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    bg = luminance(tuple(int(background.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)))
    mixed = rgb
    for step in range(21):
        mixed = tuple(round(c + (255 - c) * step / 20) for c in rgb)
        if (luminance(mixed) + 0.05) / (bg + 0.05) >= target:
            break
    return "#{:02x}{:02x}{:02x}".format(*mixed)


def fmt_number(n: int) -> str:
    for limit, suffix in ((1_000_000, "M"), (1_000, "k")):
        if n >= limit:
            return f"{n / limit:.1f}".removesuffix(".0") + suffix
    return str(n)


def fmt_bytes(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}MB"
    if n >= 1_000:
        return f"{n / 1_000:.1f}KB"
    return f"{n} bytes"


class Canvas:
    def __init__(self, fonts: Fonts):
        self.fonts = fonts
        self.body: list[str] = []
        self.defs: list[str] = []
        self.used: dict[int, set[str]] = {w: set() for w in WEIGHTS}

    def add(self, markup: str) -> None:
        self.body.append(markup)

    def rect(self, x, y, w, h, rx=8.0, fill=CARD, stroke=BORDER) -> None:
        # Inset by half the stroke so 1px borders land on whole pixels.
        self.add(f'<rect x="{x + .5:.1f}" y="{y + .5:.1f}" width="{w - 1:.1f}" height="{h - 1:.1f}" '
                 f'rx="{rx:g}" fill="{fill}" stroke="{stroke}"/>')

    def text(self, x, y, s, size, weight=400, fill=TEXT, anchor="start", tracking=0.0) -> None:
        self.used[weight].update(s)
        extra = f' text-anchor="{anchor}"' if anchor != "start" else ""
        if tracking:
            extra += f' letter-spacing="{tracking * size:.2f}"'
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size:.4g}" font-weight="{weight}" '
                 f'fill="{fill}"{extra}>{escape(s)}</text>')

    def runs(self, x, y, parts, size, anchor="start") -> None:
        """One line of differently styled runs: parts = [(text, weight, colour), ...]."""
        spans = []
        for s, weight, fill in parts:
            self.used[weight].update(s)
            spans.append(f'<tspan font-weight="{weight}" fill="{fill}">{escape(s)}</tspan>')
        extra = f' text-anchor="{anchor}"' if anchor != "start" else ""
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size:g}"{extra} '
                 f'xml:space="preserve">{"".join(spans)}</text>')

    def runs_width(self, parts, size) -> float:
        return sum(self.fonts.width(s, size, weight) for s, weight, _ in parts)

    def icon(self, name, x, y, size, color) -> None:
        box, style, paths = ICONS[name]
        paint = (f'fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" '
                 f'stroke-linejoin="round"' if style == "stroke" else f'fill="{color}"')
        body = "".join(f'<path d="{d}"/>' for d in paths)
        self.add(f'<g transform="translate({x:.1f} {y:.1f}) scale({size / box:.4f})" {paint}>{body}</g>')


# ---------------------------------------------------------------- sections


TILES = {
    "repos": ("Total Repos", "folder", lambda p: p.repos),
    "stars": ("All Stars", "star", lambda p: p.stars),
    "followers": ("Followers", "users", lambda p: p.followers),
    "years": ("Years Active", "clock", lambda p: p.years),
    "contributions": ("Contributions", "bolt", lambda p: p.contributions),
    "languages": ("Languages", "code", lambda p: len(p.languages)),
}

CATEGORIES = [
    ("Full-Stack", {"TypeScript", "JavaScript", "Python", "Ruby", "PHP"}),
    ("Systems", {"Rust", "Go", "C", "C++"}),
    ("Mobile", {"Swift", "Kotlin", "Dart"}),
    ("Data Science", {"R", "Julia"}),
    ("DevOps", {"Shell", "Dockerfile", "HCL"}),
]


def profile_tags(p: Profile, extra: list[str]) -> list[str]:
    """Your own tags first, then CheckMyGit's automatic ones; four at most."""
    auto = []
    if p.stars > 1000:
        auto.append("Popular Creator")
    elif p.stars > 100:
        auto.append("Rising Star")
    if p.repos > 50:
        auto.append("Prolific")
    if p.followers > 1000:
        auto.append("Influencer")
    elif p.followers > 100:
        auto.append("Community Member")
    if p.languages:
        auto += [cat for cat, langs in CATEGORIES if p.languages[0].name in langs][:1]
    if p.contributions > 1000:
        auto.append("Highly Active")
    elif p.contributions > 365:
        auto.append("Consistent")
    if p.years > 5:
        auto.append("Veteran")
    tags = list(extra)
    tags += [t for t in auto if t not in tags]
    return tags[:4]


def draw_pills(cv: Canvas, labels: list[str], x: float, y: float, width: float) -> float:
    cx, row = x, y
    for label in labels:
        w = cv.fonts.width(label, 12, 500) + 18
        if cx > x and cx + w > x + width:
            cx, row = x, row + 30
        cv.rect(cx, row, w, 22, rx=11, fill="none")
        cv.text(cx + w / 2, baseline(row + 3, 16, 12), label, 12, 500, TEXT2, anchor="middle")
        cx += w + 8
    return row + 22


def draw_sidebar(cv: Canvas, p: Profile, cfg: dict, avatar: tuple[bytes, str], x: float, y: float) -> float:
    f, w = cv.fonts, SIDE_W
    r = AVATAR / 2
    cx, cy = x + r, y + r
    data, mime = avatar
    cv.defs.append(f'<clipPath id="avatar"><circle cx="{cx:g}" cy="{cy:g}" r="{r - 4:g}"/></clipPath>')
    cv.add(f'<circle cx="{cx:g}" cy="{cy:g}" r="{r - 2:g}" fill="#161616" stroke="{BORDER}" stroke-width="4"/>')
    cv.add(f'<image href="data:{mime};base64,{base64.b64encode(data).decode()}" x="{x + 4:g}" y="{y + 4:g}" '
           f'width="{AVATAR - 8}" height="{AVATAR - 8}" clip-path="url(#avatar)" '
           f'preserveAspectRatio="xMidYMid slice"/>')
    y += AVATAR + 16

    if p.name:
        cv.text(x, baseline(y, 32, 24), p.name, f.fit(p.name, 24, 600, w), 600, TEXT)
        y += 36
    handle = f"@{p.login}"
    cv.text(x, baseline(y, 28, 20), handle, f.fit(handle, 20, 400, w), 400, TEXT2)
    y += 28

    if p.bio:
        y += 16
        for line in f.wrap(p.bio, 15, 400, w):
            cv.text(x, baseline(y, 22, 15), line, 15, 400, TEXT2)
            y += 22

    y += 16
    cv.rect(x, y, w, 40, fill=RAISED)
    label = "Follow on GitHub"
    left = x + (w - 24 - f.width(label, 14, 500)) / 2
    cv.icon("github", left, y + 12, 16, TEXT)
    cv.text(left + 24, baseline(y + 10, 20, 14), label, 14, 500, TEXT)
    y += 40

    tags = profile_tags(p, cfg.get("tags", []))
    if tags:
        y = draw_pills(cv, tags, x, y + 16, w)

    meta = []
    if p.company:
        meta.append(("office", p.company.lstrip("@"), TEXT2))
    if p.location:
        meta.append(("pin", p.location, TEXT2))
    if p.website:
        meta.append(("link", re.sub(r"^https?://", "", p.website).rstrip("/"), ACCENT))
    if p.twitter:
        meta.append(("x", f"@{p.twitter}", ACCENT))
    meta.append(("calendar", f"Joined {p.created:%B %Y}", TEXT2))
    y += 16
    for i, (icon, label, color) in enumerate(meta):
        y += 8 if i else 0
        cv.icon(icon, x, y + 2, 16, TEXT2)
        cv.text(x + 24, baseline(y, 20, 14), label, f.fit(label, 14, 400, w - 24), 400, color)
        y += 20

    y += 16
    line = baseline(y, 20, 14)
    cv.icon("people", x, y + 2, 16, TEXT2)
    followers = [(str(p.followers), 600, TEXT), (" follower" if p.followers == 1 else " followers", 400, TEXT2)]
    cv.runs(x + 24, line, followers, 14)
    dot = x + 24 + cv.runs_width(followers, 14) + 16
    cv.text(dot, line, "·", 14, 400, TEXT3)
    cv.runs(dot + f.width("·", 14) + 16, line, [(str(p.following), 600, TEXT), (" following", 400, TEXT2)], 14)
    return y + 20


def draw_banner(cv: Canvas, p: Profile, cfg: dict, x: float, y: float, w: float) -> float:
    f, pad = cv.fonts, 24
    inner = w - 2 * pad
    title = f"Welcome to {p.name or p.login}'s Hub"
    tagline = cfg.get("tagline") or "Explore their open source contributions and projects"
    credit = [("Inspired by ", 400, TEXT3), ("CheckMyGit", 600, ACCENT)]
    credit_w = cv.runs_width(credit, 12)

    # The credit sits on the right as in the original, but only when the title leaves room for it.
    text_w = inner - credit_w - 24 if cfg.get("credit", True) else inner
    show_credit = cfg.get("credit", True) and f.width(title, 20, 600) <= text_w
    if not show_credit:
        text_w = inner
    size = f.fit(title, 20, 600, text_w)
    lines = f.wrap(tagline, 14, 400, text_w)
    h = pad + 28 + 4 + 20 * len(lines) + pad

    cv.rect(x, y, w, h)
    cv.text(x + pad, baseline(y + pad, 28, 20), title, size, 600, TEXT)
    for i, line in enumerate(lines):
        cv.text(x + pad, baseline(y + pad + 32 + 20 * i, 20, 14), line, 14, 400, TEXT2)
    if show_credit:
        cv.runs(x + w - pad, baseline(y + h / 2 - 8, 16, 12), credit, 12, anchor="end")
    return y + h


def draw_tiles(cv: Canvas, p: Profile, cfg: dict, x: float, y: float, w: float, tile_h: float) -> float:
    keys = [k for k in cfg.get("stats", ["repos", "stars", "followers", "years"]) if k in TILES][:4]
    cols = 2
    tile_w = (w - 16 * (cols - 1)) / cols
    big = tile_h >= 136  # taller tiles get the larger number, like text-4xl
    num_size, num_lh = (36, 40) if big else (30, 36)
    content = 20 + 8 + num_lh + 16
    for i, key in enumerate(keys):
        label, icon, value = TILES[key]
        tx, ty = x + (i % cols) * (tile_w + 16), y + (i // cols) * (tile_h + 16)
        cv.rect(tx, ty, tile_w, tile_h)
        top = ty + (tile_h - content) / 2
        mid = tx + tile_w / 2
        cv.icon(icon, mid - 10, top, 20, TEXT3)
        cv.text(mid, baseline(top + 28, num_lh, num_size), fmt_number(value(p)), num_size, 700, TEXT,
                anchor="middle")
        cv.text(mid, baseline(top + 28 + num_lh, 16, 12), label.upper(), 12, 400, TEXT2,
                anchor="middle", tracking=0.05)
    rows = -(-len(keys) // cols)
    return y + rows * tile_h + (rows - 1) * 16


def section_header(cv: Canvas, x, y, w, icon, title, right=None) -> float:
    cv.icon(icon, x, y + 4, 20, TEXT3)
    cv.text(x + 28, baseline(y, 28, 18), title, 18, 600, TEXT)
    if right:
        cv.runs(x + w, baseline(y + 4, 20, 14), right, 14, anchor="end")
    return y + 28 + 16


def draw_contributions(cv: Canvas, p: Profile, x: float, y: float, w: float) -> float:
    weeks = p.weeks[-52:]
    y = section_header(cv, x, y, w, "chart", "Contributions",
                       [(fmt_number(p.contributions), 600, TEXT), (" in the last year", 400, TEXT2)])
    gap = 2
    grid_x = x + 16 + 32 + 8  # card padding, day-label column, gap
    cell = (x + w - 16 - grid_x - gap * (len(weeks) - 1)) / len(weeks)
    step = cell + gap
    grid_y = y + 16 + 14 + 8
    grid_h = 7 * cell + 6 * gap
    h = 16 + 14 + 8 + grid_h + 16 + 16 + 16
    cv.rect(x, y, w, h)

    # Month labels where a month starts; drop one that would collide with the next.
    marks, last = [], None
    for i, week in enumerate(weeks):
        month = dt.date.fromisoformat(week[0]["date"]).month
        if month != last:
            marks.append((i, dt.date(2000, month, 1).strftime("%b")))
            last = month
    for (i, label), nxt in zip(marks, marks[1:] + [(len(weeks) + 3, "")]):
        if nxt[0] - i >= 3:
            cv.text(grid_x + i * step, baseline(y + 16, 14, 10), label, 10, 400, TEXT3)

    for row, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        cv.text(grid_x - 12, grid_y + row * step + cell / 2 + 3.5, label, 10, 400, TEXT3, anchor="end")

    cells = []
    for i, week in enumerate(weeks):
        for day in week:
            cells.append(f'<rect x="{grid_x + i * step:.1f}" y="{grid_y + day["weekday"] * step:.1f}" '
                         f'width="{cell:.1f}" height="{cell:.1f}" rx="2.5" '
                         f'fill="{HEAT[LEVELS.get(day["contributionLevel"], 0)]}"/>')
    cv.add("<g>" + "".join(cells) + "</g>")
    cv.text(x + 16, baseline(grid_y + grid_h + 16, 16, 12), f"Last {len(weeks)} weeks of activity",
            12, 400, TEXT3)
    return y + h


def tech_chips(p: Profile, cfg: dict) -> list[tuple[str, str]]:
    names = cfg.get("techStack") or [lang.name for lang in p.languages[:8]]
    linguist = {lang.name.lower(): lang.color for lang in p.languages}
    return [(n, TECH_COLORS.get(n.lower()) or linguist.get(n.lower()) or "#8b949e") for n in names]


def draw_tech_and_languages(cv: Canvas, p: Profile, cfg: dict, x: float, y: float, w: float) -> float:
    f = cv.fonts
    y = section_header(cv, x, y, w, "code", "Tech Stack & Languages")
    card_w = (w - 16) / 2

    # Lay out chips first so both cards can share the taller height.
    chips, cx, cy = [], 0.0, 0.0
    for name, color in tech_chips(p, cfg):
        chip_w = f.width(name, 12, 500) + 34
        if cx and cx + chip_w > card_w - 32:
            cx, cy = 0.0, cy + 24 + 8
        chips.append((name, color, cx, cy, chip_w))
        cx += chip_w + 8
    tech_h = 16 + 16 + 16 + (cy + 24 if chips else 0) + 16

    langs = p.languages[:5]
    legend_h = len(langs) * 20 + (len(langs) - 1) * 8 if langs else 20
    row_h = max(120, legend_h)
    lang_h = 16 + row_h + 16 + 16 + 16
    h = max(tech_h, lang_h)

    cv.rect(x, y, card_w, h)
    cv.text(x + 16, baseline(y + 16, 16, 12), "CORE TECHNOLOGIES", 12, 600, TEXT3, tracking=0.05)
    for name, color, dx, dy, chip_w in chips:
        ink = legible(color)
        left, top = x + 16 + dx, y + 48 + dy
        cv.add(f'<rect x="{left + .5:.1f}" y="{top + .5:.1f}" width="{chip_w - 1:.1f}" height="23" rx="11.5" '
               f'fill="{color}" fill-opacity="0.125" stroke="{color}" stroke-opacity="0.25"/>')
        cv.add(f'<circle cx="{left + 14:.1f}" cy="{top + 12:.1f}" r="4" fill="{ink}"/>')
        cv.text(left + 24, baseline(top + 4, 16, 12), name, 12, 500, ink)

    lx = x + card_w + 16
    cv.rect(lx, y, card_w, h)
    if not langs:
        cv.text(lx + card_w / 2, y + h / 2, "No language data available", 14, 400, TEXT3, anchor="middle")
        return y + h
    total = sum(lang.size for lang in langs)
    dcx, dcy, radius = lx + 16 + 60, y + 16 + row_h / 2, 50
    circumference = 2 * 3.141592653589793 * radius
    offset = 0.0
    for lang in langs:
        length = lang.size / total * circumference
        cv.add(f'<circle cx="{dcx:.1f}" cy="{dcy:.1f}" r="{radius}" fill="none" stroke="{lang.color}" '
               f'stroke-width="20" stroke-dasharray="{length:.2f} {circumference:.2f}" '
               f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {dcx:.1f} {dcy:.1f})"/>')
        offset += length
    cv.text(dcx, dcy + 4, f"{len(langs)} langs", 12, 400, TEXT3, anchor="middle")

    legend_x, legend_r = lx + 16 + 120 + 24, lx + card_w - 16
    top = y + 16 + (row_h - legend_h) / 2
    for i, lang in enumerate(langs):
        row = top + i * 28
        cv.add(f'<circle cx="{legend_x + 6:.1f}" cy="{row + 10:.1f}" r="6" fill="{lang.color}"/>')
        cv.text(legend_x + 20, baseline(row, 20, 14), lang.name, 14, 400, TEXT)
        cv.text(legend_r, baseline(row, 20, 14), f"{lang.percent}%", 14, 400, TEXT2, anchor="end")
    cv.text(lx + 16, baseline(y + 16 + row_h + 16, 16, 12), f"Based on {fmt_bytes(total)} of code",
            12, 400, TEXT3)
    return y + h


# ---------------------------------------------------------------- page


def render(p: Profile, cfg: dict, fonts: Fonts, avatar: tuple[bytes, str]) -> str:
    cv = Canvas(fonts)
    main_x = PAD + SIDE_W + GUTTER
    main_w = W - main_x - PAD

    side_bottom = draw_sidebar(cv, p, cfg, avatar, PAD, PAD)
    y = draw_banner(cv, p, cfg, main_x, PAD, main_w) + 24
    # Stretch the tiles so the right column ends with the sidebar, within reason.
    tile_h = min(168, max(112, (side_bottom - y - 16) / 2))
    y = draw_tiles(cv, p, cfg, main_x, y, main_w, tile_h)

    y = max(y, side_bottom) + 32
    if p.weeks:
        y = draw_contributions(cv, p, PAD, y, W - 2 * PAD) + 24
    y = draw_tech_and_languages(cv, p, cfg, PAD, y, W - 2 * PAD)
    h = y + PAD

    faces = "".join(
        f'@font-face{{font-family:"Geist";font-weight:{weight};'
        f'src:url(data:font/woff2;base64,{fonts.embed(weight, chars | {" "})}) format("woff2")}}'
        for weight, chars in cv.used.items() if chars
    )
    style = (faces + 'text{font-family:Geist,-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",'
             "Helvetica,Arial,sans-serif}")
    label = f"{p.name or p.login}'s GitHub hub"
    glow_r = (W ** 2 / 4 + h ** 2) ** 0.5
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h:.0f}" viewBox="0 0 {W} {h:.0f}" '
        f'role="img" aria-label="{attr(label)}">'
        f"<title>{escape(label)}</title>"
        f"<defs><style>{style}</style>{''.join(cv.defs)}"
        f'<radialGradient id="glow" gradientUnits="userSpaceOnUse" cx="{W / 2:g}" cy="0" r="{glow_r:.0f}">'
        f'<stop offset="0" stop-color="#787878" stop-opacity="0.05"/>'
        f'<stop offset="0.4" stop-color="#787878" stop-opacity="0"/></radialGradient></defs>'
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{h - 1:.0f}" rx="12" fill="{PAGE}" stroke="{RAISED}"/>'
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{h - 1:.0f}" rx="12" fill="url(#glow)"/>'
        + "\n".join(cv.body)
        + "</svg>\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--out", type=Path, default=HERE / "dist" / "hub.svg")
    args = parser.parse_args()

    cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    login = cfg.get("username") or os.environ.get("GITHUB_REPOSITORY_OWNER")
    if not token or not login:
        sys.exit("Set GITHUB_TOKEN and a username in hub/config.json")

    profile = fetch_profile(login, token)
    avatar = http_get(profile.avatar_url + ("&" if "?" in profile.avatar_url else "?") + "s=400")
    svg = render(profile, cfg, Fonts(HERE / ".cache"), avatar)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(svg, encoding="utf-8")
    print(f"Wrote {args.out} ({len(svg.encode()) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
