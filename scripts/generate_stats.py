"""Generate assets/stats.svg: commit counts, repo totals, and language mix.

Runs in GitHub Actions (see .github/workflows/stats.yml). Uses only the
standard library. Reads GITHUB_TOKEN (or STATS_TOKEN, a PAT that can also
see private repos) from the environment.
"""

import json
import os
import urllib.request
from datetime import datetime, timezone
from html import escape
from pathlib import Path

USER = "abi2055"
OUT = Path(__file__).resolve().parent.parent / "assets" / "stats.svg"
# Languages that are generated or vendored rather than written.
EXCLUDED_LANGUAGES = {"Jupyter Notebook", "Makefile", "CMake", "Batchfile"}
TOP_N = 6
# GitHub linguist colors for the languages likely to show up; others fall back.
LANGUAGE_COLORS = {
    "Python": "#3572A5", "C++": "#f34b7d", "C": "#555555", "Java": "#b07219",
    "JavaScript": "#f1e05a", "TypeScript": "#3178c6", "HTML": "#e34c26",
    "CSS": "#663399", "Go": "#00ADD8", "Kotlin": "#A97BFF", "GLSL": "#5686a5",
    "Shell": "#89e051", "TeX": "#3D6117", "Rust": "#dea584",
}
FALLBACK_COLOR = "#8b949e"

TOKEN = os.environ.get("STATS_TOKEN") or os.environ.get("GITHUB_TOKEN")


def request(url, body=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def graphql(query, **variables):
    result = request("https://api.github.com/graphql", {"query": query, "variables": variables})
    if "errors" in result:
        raise RuntimeError(result["errors"])
    return result["data"]


def owned_repos():
    # /user/repos includes private repos when STATS_TOKEN is a PAT;
    # GITHUB_TOKEN can only see public ones, so use the public endpoint then.
    if os.environ.get("STATS_TOKEN"):
        base = "https://api.github.com/user/repos?affiliation=owner&per_page=100"
    else:
        base = f"https://api.github.com/users/{USER}/repos?type=owner&per_page=100"
    repos, page = [], 1
    while True:
        batch = request(f"{base}&page={page}")
        repos += batch
        if len(batch) < 100:
            return [r for r in repos if not r["fork"]]
        page += 1


def commit_counts():
    """Sum commit contributions per year since the account was created."""
    created = graphql("query($login:String!){user(login:$login){createdAt}}", login=USER)
    start_year = int(created["user"]["createdAt"][:4])
    now = datetime.now(timezone.utc)
    query = """query($login:String!,$from:DateTime!,$to:DateTime!){
      user(login:$login){contributionsCollection(from:$from,to:$to){
        totalCommitContributions restrictedContributionsCount}}}"""
    total = 0
    for year in range(start_year, now.year + 1):
        c = graphql(query, login=USER, **{"from": f"{year}-01-01T00:00:00Z", "to": f"{year}-12-31T23:59:59Z"})
        total += c["user"]["contributionsCollection"]["totalCommitContributions"]
    last_year = graphql(
        query, login=USER,
        **{"from": now.replace(year=now.year - 1).isoformat(), "to": now.isoformat()},
    )["user"]["contributionsCollection"]["totalCommitContributions"]
    return total, last_year


def language_totals(repos):
    totals = {}
    for repo in repos:
        for lang, size in request(repo["languages_url"]).items():
            if lang not in EXCLUDED_LANGUAGES:
                totals[lang] = totals.get(lang, 0) + size
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    top, rest = ranked[:TOP_N], sum(size for _, size in ranked[TOP_N:])
    if rest:
        top.append(("Other", rest))
    grand = sum(size for _, size in top) or 1
    return [(lang, size / grand) for lang, size in top], len(totals)


def render(stats, languages):
    width, pad = 840, 28
    bar_y, bar_w, bar_h = 132, width - 2 * pad, 10

    tiles = ""
    tile_w = (width - 2 * pad) / len(stats)
    for i, (label, value) in enumerate(stats):
        x = pad + i * tile_w
        tiles += (
            f'<text x="{x:.1f}" y="74" class="value">{escape(str(value))}</text>'
            f'<text x="{x:.1f}" y="96" class="label">{escape(label)}</text>'
        )

    segments, offset = "", 0.0
    for lang, share in languages:
        w = share * bar_w
        color = LANGUAGE_COLORS.get(lang, FALLBACK_COLOR)
        segments += f'<rect x="{pad + offset:.2f}" y="{bar_y}" width="{w:.2f}" height="{bar_h}" fill="{color}"/>'
        offset += w

    legend, col_w = "", (width - 2 * pad) / 4
    for i, (lang, share) in enumerate(languages):
        x = pad + (i % 4) * col_w
        y = bar_y + 40 + (i // 4) * 26
        color = LANGUAGE_COLORS.get(lang, FALLBACK_COLOR)
        legend += (
            f'<circle cx="{x + 5:.1f}" cy="{y - 4}" r="5" fill="{color}"/>'
            f'<text x="{x + 16:.1f}" y="{y}" class="lang">{escape(lang)} '
            f'<tspan class="pct">{share * 100:.1f}%</tspan></text>'
        )

    rows = (len(languages) + 3) // 4
    height = bar_y + 40 + rows * 26 + 10

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="GitHub stats for {USER}">
<style>
  :root {{ --bg:#ffffff; --border:#d0d7de; --fg:#1f2328; --muted:#59636e; --track:#eaeef2; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0d1117; --border:#30363d; --fg:#e6edf3; --muted:#9198a1; --track:#21262d; }}
  }}
  text {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: var(--fg); }}
  .title {{ font-size:15px; font-weight:600; }}
  .value {{ font-size:26px; font-weight:600; }}
  .label {{ font-size:12px; fill: var(--muted); }}
  .lang {{ font-size:13px; }}
  .pct {{ fill: var(--muted); }}
</style>
<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="10" fill="var(--bg)" stroke="var(--border)"/>
<text x="{pad}" y="34" class="title">GitHub activity</text>
{tiles}
<clipPath id="bar"><rect x="{pad}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="5"/></clipPath>
<rect x="{pad}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="5" fill="var(--track)"/>
<g clip-path="url(#bar)">{segments}</g>
{legend}
</svg>
"""


def main():
    repos = owned_repos()
    languages, language_count = language_totals(repos)
    total_commits, last_year = commit_counts()
    stars = sum(r["stargazers_count"] for r in repos)
    stats = [
        ("Total commits", f"{total_commits:,}"),
        ("Commits, last 12 months", f"{last_year:,}"),
        ("Repositories", len(repos)),
        ("Languages", language_count),
        ("Stars", stars),
    ]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(render(stats, languages))
    print(f"wrote {OUT}: {stats}")


if __name__ == "__main__":
    main()
