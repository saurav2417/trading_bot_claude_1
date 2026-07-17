#!/usr/bin/env python3
"""
Publish the HRC Transport SEO package to WordPress via the REST API.

Usage:
  1. Fill in deploy/placeholders.json with the real phone, address, email, GBP link.
  2. Set credentials (never commit them):
       export WP_URL="https://hrctransport.com"
       export WP_USER="<wordpress username the application password belongs to>"
       export WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx xxxx"
  3. Dry run (shows what would be created):   python3 publish.py --dry-run
  4. Create everything as DRAFTS (default):   python3 publish.py
  5. Publish live:                            python3 publish.py --live

Idempotent: if a page/post with the same slug exists, it is updated, not duplicated.
Rank Math SEO title/description are sent as post meta (works when Rank Math is
installed and exposes meta over REST; otherwise paste them manually — they are
printed in the summary).
"""
import argparse
import base64
import json
import os
import re
import sys
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# file, type, publish order
MANIFEST = [
    ("content/route-kolkata-to-bhutan.md", "page"),
    ("content/route-kolkata-to-siliguri.md", "page"),
    ("content/route-kolkata-to-gangtok-sikkim.md", "page"),
    ("content/services.md", "page"),
    ("articles/kolkata-to-siliguri-transport-charges.md", "post"),
    ("articles/send-goods-india-to-bhutan-guide.md", "post"),
    ("articles/ftl-vs-ptl-which-to-choose.md", "post"),
]


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_placeholders():
    path = os.path.join(HERE, "placeholders.json")
    with open(path) as f:
        mapping = json.load(f)
    missing = [k for k, v in mapping.items() if "XXXX" in v or v.startswith("[")]
    if missing:
        die(f"placeholders.json still has unfilled values: {missing}. "
            "Fill in real values first — never publish placeholder contact info.")
    return mapping


def apply_placeholders(text, mapping):
    for key, val in mapping.items():
        text = text.replace(key, val)
    return text


def extract(md, pattern):
    m = re.search(pattern, md)
    return m.group(1).strip().strip("`") if m else None


def md_to_html(md):
    """Minimal markdown → HTML good enough for the block editor to render.
    Uses python-markdown if available."""
    try:
        import markdown  # type: ignore
        return markdown.markdown(md, extensions=["tables"])
    except ImportError:
        pass
    html_parts, in_code, code_lines = [], False, []
    for line in md.split("\n"):
        if line.strip().startswith("```"):
            if in_code:
                html_parts.append("\n".join(code_lines))  # raw html blocks (JSON-LD)
                code_lines = []
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(line)
            continue
        s = line.strip()
        if not s:
            continue
        if s.startswith("### "):
            html_parts.append(f"<h3>{inline(s[4:])}</h3>")
        elif s.startswith("## "):
            html_parts.append(f"<h2>{inline(s[3:])}</h2>")
        elif s.startswith("# "):
            html_parts.append(f"<h1>{inline(s[2:])}</h1>")
        elif s.startswith("- "):
            html_parts.append(f"<ul><li>{inline(s[2:])}</li></ul>")
        elif s.startswith("|"):
            html_parts.append(f"<p>{inline(s)}</p>")  # tables degrade to text w/o markdown lib
        elif re.match(r"^\d+\. ", s):
            item_text = re.sub(r"^\d+\. ", "", s)
            html_parts.append(f"<ol><li>{inline(item_text)}</li></ol>")
        else:
            html_parts.append(f"<p>{inline(s)}</p>")
    return "\n".join(html_parts)


def inline(s):
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\*(.+?)\*", r"<em>\1</em>", s)
    s = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', s)
    return s


def parse_file(relpath, mapping):
    with open(os.path.join(ROOT, relpath)) as f:
        raw = f.read()
    raw = apply_placeholders(raw, mapping)
    slug = extract(raw, r"\*\*Slug:\*\*\s*`?(/?[^`\n]+)`?")
    seo_title = extract(raw, r"\*\*SEO Title[^:]*:\*\*\s*`?([^`\n]+)`?")
    meta_desc = extract(raw, r"\*\*Meta Description[^:]*:\*\*\s*`?([^`\n]+)`?")
    if not slug:
        die(f"{relpath}: no slug found")
    slug = slug.strip("/").split("/")[-1] or None
    # body: everything after '## Page copy' (pages) or after first '---\n\n#' (articles)
    m = re.search(r"## Page copy\s*\n(.*)", raw, re.S)
    if not m:
        m = re.search(r"\n---\s*\n\s*(# .*)", raw, re.S)
    if not m:
        die(f"{relpath}: no body found")
    body_md = m.group(1)
    # drop the trailing "FAQ JSON-LD" heading but keep the html block itself
    body_md = re.sub(r"## FAQ JSON-LD.*?```html", "```html", body_md, flags=re.S)
    title_m = re.search(r"^# (.+)$", body_md, re.M)
    h1 = title_m.group(1).strip() if title_m else seo_title
    body_md = re.sub(r"^# .+\n", "", body_md, count=1, flags=re.M)  # h1 comes from post title
    return {"slug": slug, "title": h1, "seo_title": seo_title,
            "meta_desc": meta_desc, "html": md_to_html(body_md)}


class WP:
    def __init__(self, url, user, password):
        self.base = url.rstrip("/") + "/wp-json/wp/v2"
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}",
                        "Content-Type": "application/json",
                        "User-Agent": "hrc-seo-deploy/1.0"}

    def req(self, method, path, data=None):
        body = json.dumps(data).encode() if data is not None else None
        r = urllib.request.Request(self.base + path, data=body,
                                   headers=self.headers, method=method)
        try:
            with urllib.request.urlopen(r, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:300]
            die(f"{method} {path} -> HTTP {e.code}: {detail}")

    def find_by_slug(self, kind, slug):
        items = self.req("GET", f"/{kind}s?slug={slug}&status=any&per_page=1")
        return items[0]["id"] if items else None

    def upsert(self, kind, item, status):
        payload = {
            "title": item["title"], "slug": item["slug"],
            "content": item["html"], "status": status,
            "meta": {"rank_math_title": item["seo_title"] or "",
                     "rank_math_description": item["meta_desc"] or ""},
        }
        existing = self.find_by_slug(kind, item["slug"])
        if existing:
            res = self.req("POST", f"/{kind}s/{existing}", payload)
            action = "updated"
        else:
            res = self.req("POST", f"/{kind}s", payload)
            action = "created"
        return action, res.get("link", "?")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="publish immediately (default: draft)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    status = "publish" if args.live else "draft"

    mapping = load_placeholders()
    items = [(parse_file(p, mapping), kind) for p, kind in MANIFEST]

    if args.dry_run:
        for it, kind in items:
            print(f"[dry-run] {kind}: /{it['slug']}/  ({it['title']})")
            print(f"          SEO title: {it['seo_title']}")
            print(f"          Meta desc: {it['meta_desc']}")
        return

    url = os.environ.get("WP_URL") or die("set WP_URL")
    user = os.environ.get("WP_USER") or die("set WP_USER")
    pw = os.environ.get("WP_APP_PASSWORD") or die("set WP_APP_PASSWORD")
    wp = WP(url, user, pw)
    me = wp.req("GET", "/users/me?context=edit")
    print(f"Authenticated as: {me.get('name')} ({me.get('slug')})\n")

    for it, kind in items:
        action, link = wp.upsert(kind, it, status)
        print(f"{action} {kind} [{status}]: {link}")
        print(f"   ↳ if Rank Math meta didn't apply, paste manually — "
              f"title: {it['seo_title']} | desc: {it['meta_desc']}")
    print("\nDone. Next: set homepage copy from content/homepage.md, add pages to the "
          "main menu, submit sitemap in Search Console, request indexing per page.")


if __name__ == "__main__":
    main()
