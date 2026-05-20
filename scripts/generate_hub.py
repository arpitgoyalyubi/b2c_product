#!/usr/bin/env python3
"""
generate_hub.py — Auto-generates index.html from meta.json sidecar files.

How it works:
  • Root-level  foo.meta.json        → card links to  foo.html
  • Subfolder   foo/meta.json        → card links to  foo/

To add a new report/prototype, just drop a meta.json next to the HTML file.
Schema:
  {
    "title":       "string",
    "description": "string",
    "section":     "live-reports | analyses | prototypes",
    "icon":        "emoji",
    "accent":      "#hex",
    "badges":      [{"label": "string", "color": "blue|green|purple|amber|gray"}],
    "order":       number   (optional, default 99)
  }
"""

import json
import os
import re
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# ── Section config ─────────────────────────────────────────────────────────────
SECTIONS = [
    {"key": "live-reports", "label": "Live Reports"},
    {"key": "analyses",     "label": "Analyses"},
    {"key": "prototypes",   "label": "Prototypes & Mocks"},
]

# ── Jira epics — hardcoded (external links, no local file) ────────────────────
JIRA_EPICS = [
    {
        "href": "https://goyubi.atlassian.net/browse/ASP-3429",
        "title": "SEO Epic — ASP-3429",
        "description": "Bond page SEO sprint: SSR, meta titles, JSON-LD schema, H1 headers, canonical tags, sitemap. 13 of 30 tickets shipped.",
        "icon": "🎯",
        "accent": "#7C3AED",
        "badges": [{"label": "SEO", "color": "purple"}, {"label": "Jira ↗", "color": "blue"}],
        "external": True,
    },
    {
        "href": "https://goyubi.atlassian.net/browse/ASP-3411",
        "title": "Payment Conversion — ASP-3411",
        "description": "Improve KYC-done → first investment conversion. Current 8% vs 40% target. Primary GTV lever.",
        "icon": "💸",
        "accent": "#16A34A",
        "badges": [{"label": "Payment", "color": "green"}, {"label": "Jira ↗", "color": "blue"}],
        "external": True,
    },
    {
        "href": "https://goyubi.atlassian.net/browse/ASP-3427",
        "title": "User Acquisition — ASP-3427",
        "description": "Signup quality and platform mix. Premium tier targeting, KYC start rate, Android Low optimisation.",
        "icon": "📱",
        "accent": "#D97706",
        "badges": [{"label": "Acquisition", "color": "amber"}, {"label": "Jira ↗", "color": "blue"}],
        "external": True,
    },
    {
        "href": "https://goyubi.atlassian.net/browse/ASP-3412",
        "title": "Repeat Investor — ASP-3412",
        "description": "Re-engagement nudges, push notification flows, portfolio-led discovery for existing investors.",
        "icon": "🔁",
        "accent": "#2563EB",
        "badges": [{"label": "Repeat", "color": "blue"}, {"label": "Jira ↗", "color": "blue"}],
        "external": True,
    },
    {
        "href": "https://goyubi.atlassian.net/browse/ASP-3472",
        "title": "Portfolio Revamp — ASP-3472",
        "description": "Portfolio 2.0 — Personal Analyst. Investment summary bar, holdings tab, insights tab, cashflow and payouts full-screen views.",
        "icon": "💼",
        "accent": "#7C3AED",
        "badges": [{"label": "Portfolio", "color": "purple"}, {"label": "Jira ↗", "color": "blue"}],
        "external": True,
    },
]

# ── Badge color map ────────────────────────────────────────────────────────────
BADGE_CLASS = {
    "blue":   "badge-blue",
    "green":  "badge-green",
    "purple": "badge-purple",
    "amber":  "badge-amber",
    "gray":   "badge-gray",
}


def collect_cards():
    """Walk repo, find all meta.json files, return list of card dicts."""
    cards = []

    # Root-level: foo.meta.json → foo.html
    for meta_file in sorted(REPO_ROOT.glob("*.meta.json")):
        basename = meta_file.stem  # e.g. "weekly-review"
        href = f"{basename}.html"
        try:
            data = json.loads(meta_file.read_text())
        except Exception as e:
            print(f"  WARN: could not parse {meta_file.name}: {e}")
            continue
        cards.append({**data, "href": href, "external": False})

    # Subfolder: foo/meta.json → foo/
    for meta_file in sorted(REPO_ROOT.glob("*/meta.json")):
        folder = meta_file.parent.name
        if folder == "scripts":
            continue
        href = f"{folder}/"
        try:
            data = json.loads(meta_file.read_text())
        except Exception as e:
            print(f"  WARN: could not parse {folder}/meta.json: {e}")
            continue
        cards.append({**data, "href": href, "external": False})

    return cards


def render_badge(badge):
    cls = BADGE_CLASS.get(badge.get("color", "blue"), "badge-blue")
    return f'<span class="badge {cls}">{badge["label"]}</span>'


def render_card(card):
    href     = card["href"]
    title    = card["title"]
    desc     = card["description"]
    icon     = card.get("icon", "📄")
    accent   = card.get("accent", "#2563EB")
    badges   = card.get("badges", [])
    external = card.get("external", False)

    target_attr = ' target="_blank" rel="noopener"' if external else ""
    badges_html = "\n        ".join(render_badge(b) for b in badges)
    arrow_html  = '<span class="arrow">→</span>' if not external else ""

    return f"""    <a class="card" href="{href}"{target_attr} style="--accent:{accent}">
      <div class="card-icon">{icon}</div>
      <div class="card-title">{title}</div>
      <div class="card-desc">{desc}</div>
      <div class="card-meta">
        {badges_html}
        {arrow_html}
      </div>
    </a>"""


def render_section(label, cards):
    if not cards:
        return ""
    cards_html = "\n\n".join(render_card(c) for c in cards)
    return f"""
  <div class="section-label">{label}</div>
  <div class="card-grid">

{cards_html}

  </div>
"""


def build_html(sections_html):
    today = date.today().strftime("%b %-d %Y")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Aspero B2C — Product Hub</title>
<style>
  :root {{
    --blue:    #2563EB;
    --blue-lt: #EFF6FF;
    --green:   #16A34A;
    --green-lt:#F0FDF4;
    --purple:  #7C3AED;
    --amber:   #D97706;
    --gray:    #64748B;
    --border:  #E2E8F0;
    --text:    #0F172A;
    --text2:   #475569;
    --bg:      #F1F5F9;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
  }}

  /* Header */
  .header {{
    background: linear-gradient(135deg, #1E3A8A 0%, #2563EB 60%, #3B82F6 100%);
    color: white;
    padding: 48px 32px 40px;
    text-align: center;
  }}
  .header .logo {{
    font-size: 13px;
    font-weight: 700;
    letter-spacing: .12em;
    text-transform: uppercase;
    opacity: .7;
    margin-bottom: 12px;
  }}
  .header h1 {{
    font-size: 32px;
    font-weight: 800;
    margin-bottom: 10px;
    letter-spacing: -.02em;
  }}
  .header p {{
    font-size: 15px;
    opacity: .8;
    max-width: 560px;
    margin: 0 auto;
    line-height: 1.6;
  }}

  /* Main grid */
  .wrap {{ max-width: 1080px; margin: 0 auto; padding: 40px 24px 60px; }}

  .section-label {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: var(--gray);
    margin-bottom: 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
  }}

  .card-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 20px;
    margin-bottom: 40px;
  }}

  .card {{
    background: white;
    border-radius: 14px;
    border: 1px solid var(--border);
    padding: 24px;
    text-decoration: none;
    color: inherit;
    display: flex;
    flex-direction: column;
    transition: box-shadow .15s, transform .15s;
    position: relative;
    overflow: hidden;
  }}
  .card:hover {{
    box-shadow: 0 8px 24px rgba(0,0,0,.10);
    transform: translateY(-2px);
  }}
  .card::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 4px;
    background: var(--accent, var(--blue));
  }}

  .card-icon {{ font-size: 28px; margin-bottom: 12px; }}
  .card-title {{
    font-size: 16px;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 6px;
  }}
  .card-desc {{
    font-size: 13px;
    color: var(--text2);
    line-height: 1.6;
    flex: 1;
    margin-bottom: 16px;
  }}
  .card-meta {{
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }}
  .badge {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 9px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
  }}
  .badge-blue   {{ background: var(--blue-lt); color: var(--blue); }}
  .badge-green  {{ background: var(--green-lt); color: var(--green); }}
  .badge-purple {{ background: #F5F3FF; color: var(--purple); }}
  .badge-amber  {{ background: #FFFBEB; color: var(--amber); }}
  .badge-gray   {{ background: #F1F5F9; color: var(--gray); }}

  .arrow {{
    margin-left: auto;
    font-size: 18px;
    color: var(--gray);
    transition: transform .15s;
  }}
  .card:hover .arrow {{ transform: translateX(4px); }}

  /* Footer */
  .footer {{
    text-align: center;
    color: var(--gray);
    font-size: 12px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
  }}

  @media (max-width: 600px) {{
    .header h1 {{ font-size: 24px; }}
    .card-grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>

<div class="header">
  <div class="logo">Aspero · B2C Product</div>
  <h1>Product Hub</h1>
  <p>Analytics, prototypes, SEO, and sprint reports — everything in one place.</p>
</div>

<div class="wrap">
{sections_html}
</div>

<div class="wrap" style="padding-top: 0">
  <div class="footer">
    Aspero B2C Product Hub · Auto-generated {today} · <a href="https://github.com/arpitgoyalyubi/b2c_product" style="color:var(--blue)">GitHub Repo ↗</a>
  </div>
</div>

</body>
</html>
"""


def main():
    print("Scanning for meta.json files...")
    all_cards = collect_cards()
    print(f"  Found {len(all_cards)} cards")

    # Group by section
    by_section = {s["key"]: [] for s in SECTIONS}
    for card in all_cards:
        section = card.get("section", "analyses")
        if section not in by_section:
            print(f"  WARN: unknown section '{section}' in {card['href']}, defaulting to analyses")
            section = "analyses"
        by_section[section].append(card)

    # Sort each section by order
    for key in by_section:
        by_section[key].sort(key=lambda c: c.get("order", 99))

    # Build section HTML
    sections_html = ""
    for s in SECTIONS:
        sections_html += render_section(s["label"], by_section[s["key"]])

    # Jira epics section
    sections_html += render_section("Active Jira Epics", JIRA_EPICS)

    # GitHub Actions card (always last)
    gh_card = {
        "href": "https://github.com/arpitgoyalyubi/b2c_product/actions",
        "title": "GitHub Actions — All Agents",
        "description": "Funnel agent (8 AM IST), Growth agent (9 AM IST), PM agent (8:45 AM IST), SEO agent, Persona Quality agent — all running daily.",
        "icon": "🤖",
        "accent": "#64748B",
        "badges": [{"label": "CI/CD", "color": "blue"}, {"label": "5 agents live", "color": "green"}],
        "external": True,
    }
    sections_html += render_section("Agent Dashboards", [gh_card])

    html = build_html(sections_html)

    out = REPO_ROOT / "index.html"
    out.write_text(html)
    print(f"  Written → {out}")


if __name__ == "__main__":
    main()
