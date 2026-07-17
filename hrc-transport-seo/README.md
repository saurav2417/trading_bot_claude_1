# HRC Transport — SEO Overhaul & Lead-Generation Package

Complete, ready-to-deploy SEO package for **https://hrctransport.com** (self-hosted WordPress + Jetpack).
Goal: go from **1 indexed page and zero route rankings** to ranking for commercial route searches
("Kolkata to Siliguri transport", "transport service to Bhutan", etc.) and converting that traffic into calls/WhatsApp leads.

## ⚠️ Placeholders to replace before publishing

Search all files for these markers and replace with real values:

| Placeholder | Replace with |
|---|---|
| `+91-XXXXX-XXXXX` | Your real phone number (same one as on Google Business Profile) |
| `[VERIFY-ADDRESS]` | Confirmed office address. Assumed: 21 Phears Lane, Kolkata 700012 (from IndiaMART listing — verify) |
| `[GBP-LINK]` | Your Google Business Profile short link |
| `[EMAIL]` | Business email |
| `[YEARS]` | Years in business |

## What's in this package

```
hrc-transport-seo/
├── README.md                ← you are here (master checklist below)
├── audit/AUDIT.md           ← full audit findings & why leads aren't coming
├── guides/
│   ├── wordpress-setup.md   ← Rank Math, sitemap, Search Console, indexation, speed
│   └── local-seo.md         ← Google Business Profile optimization & citations
├── content/                 ← ready-to-paste WordPress PAGES (each has title tag, meta, copy, FAQ, schema)
│   ├── homepage.md
│   ├── route-kolkata-to-siliguri.md
│   ├── route-kolkata-to-gangtok-sikkim.md
│   ├── route-kolkata-to-bhutan.md
│   ├── services.md
│   └── about-contact.md
├── articles/                ← ready-to-paste BLOG POSTS (publish ~1 per week)
│   ├── kolkata-to-siliguri-transport-charges.md
│   ├── send-goods-india-to-bhutan-guide.md
│   └── ftl-vs-ptl-which-to-choose.md
├── schema/localbusiness.jsonld  ← site-wide structured data
└── site-preview/index.html      ← modern homepage design you can preview in a browser
```

## Implementation checklist (in priority order)

### Week 1 — Foundation (biggest impact)
- [ ] **Install Rank Math SEO** (free) from Plugins → Add New. Run its setup wizard, choose "Local Business".
- [ ] **Fix permalinks**: Settings → Permalinks → "Post name" (`/sample-page/` style URLs).
- [ ] **Google Search Console**: verify the domain, submit `https://hrctransport.com/sitemap_index.xml` (Rank Math generates it). This alone should fix the "only 1 page indexed" problem.
- [ ] **Replace homepage** with `content/homepage.md` copy (or rebuild using `site-preview/index.html` as the design reference). Set the new title tag + meta description in Rank Math.
- [ ] **Add site-wide LocalBusiness schema**: `schema/localbusiness.jsonld` → Rank Math → Local SEO settings, or paste via a header script.
- [ ] Put **phone number + WhatsApp button in the header of every page** — sticky on mobile. This is where the leads come from.

### Week 2 — Route pages (this is what ranks and converts)
- [ ] Publish the 3 route pages from `content/` as WordPress Pages with the exact slugs given in each file.
- [ ] Publish `services.md` and `about-contact.md`.
- [ ] Link all route pages from the homepage and main menu.
- [ ] In Search Console → URL Inspection → "Request indexing" for each new page.

### Week 3 — Local SEO
- [ ] Follow `guides/local-seo.md`: complete every GBP field, make Name/Address/Phone identical everywhere (website, GBP, IndiaMART, Justdial).
- [ ] Ask 5 recent happy customers for Google reviews (script included in guide).
- [ ] Link your website ↔ GBP both ways.

### Week 4+ — Content engine
- [ ] Publish 1 article per week from `articles/` (3 provided; topic list for 10 more in AUDIT.md).
- [ ] Each article internally links to the matching route page.
- [ ] Monthly: check Search Console → Performance for which queries get impressions; create/expand pages for those queries.

## Expected results timeline (realistic)
- **2–4 weeks**: all pages indexed; brand searches ("HRC Transport") show proper title/description.
- **6–10 weeks**: route pages start appearing on page 2–3 for "kolkata to siliguri transporter"-type queries; GBP calls increase from profile completeness + reviews.
- **3–6 months**: page-1 contention for medium-competition route keywords; steady inbound calls/WhatsApp from route pages + articles.

Leads = **rankings × conversion**. The route pages are built so every screen has a call/WhatsApp action; don't strip those out when pasting into WordPress.
