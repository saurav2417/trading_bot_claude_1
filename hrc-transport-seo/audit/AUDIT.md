# HRC Transport — Technical SEO Audit (July 2026)

**Site:** https://hrctransport.com · Self-hosted WordPress, Jetpack-connected (free plan), site ID 256220255.
**Audit method:** search-engine index analysis + WordPress.com/Jetpack API reads. (Direct crawl and paid-Jetpack
API reads were unavailable; re-verify details below once you have dashboard access in front of you.)

## Executive summary

The site is effectively invisible to search engines beyond a single indexed homepage, while direct competitors
(Trukky, Easyport, TempoMyCity, packersmovers.com) rank with dedicated route pages for exactly the queries your
customers type. There is no meta description, a weak title tag, no visible structured data, no sitemap submission
evidence, and a thin local-SEO footprint. **The gap is not quality of service — it's that Google has almost
nothing of yours to rank.** Everything in this package targets that gap.

## Findings

### 1. Indexation — CRITICAL
- `site:hrctransport.com` returns **one result** (the homepage). No services, contact, about, or route pages are indexed.
- Likely causes (verify in order): no XML sitemap submitted to Google Search Console; possibly "Discourage search
  engines" partially enabled historically; pages may simply not exist; weak internal linking.
- **Fix:** Rank Math sitemap + Search Console submission + publish the pages in `content/` (see guides/wordpress-setup.md).

### 2. Title tag — HIGH
- Current: `Transporter for Kolkata, Siliguri, Sikkim and Bhutan`
- Problems: no brand name (kills brand-search CTR), no commercial modifier, generic word "Transporter" as the lead.
- **Fix:** `HRC Transport | Goods Transport Service — Kolkata to Siliguri, Sikkim & Bhutan` (in content/homepage.md).

### 3. Meta description — HIGH
- None set; Google pulls testimonial fragments ("…transported surgical material… charged reasonable amount…"),
  which reads as broken text in results and depresses click-through.
- **Fix:** every page in `content/` ships a purpose-written meta description ≤155 chars with a call to action.

### 4. Site architecture — CRITICAL for leads
- A single homepage cannot rank for route queries. Competitors win with URL-level targeting:
  - trukky.com`/kolkata-to-siliguri`
  - easyport.co.in`/best-1-kolkata-to-siliguri-transport-service/`
  - tempomycity.com`/kolkata-siliguri-transport.html`
- **Fix:** the 3 route pages + services page in `content/`, interlinked, in the main menu. Add more routes later
  (Guwahati, Malda, Durgapur, Asansol…) using the same template.

### 5. Structured data — MEDIUM
- No LocalBusiness/Service schema detected in search results presentation.
- **Fix:** `schema/localbusiness.jsonld` site-wide + per-page FAQPage schema (included inside each content file).
  This enables rich results and strengthens the GBP ↔ website entity connection.

### 6. Local SEO — HIGH
- GBP exists (per owner) but the website shows no consistent NAP (Name/Address/Phone) block; IndiaMART lists the
  business as "HRC Logistics (Hindusthan Road Carriers), 21 Phears Lane, Kolkata 700012" — a different name than
  the website brand. Name inconsistency dilutes local ranking signals.
- **Fix:** one canonical NAP everywhere; see guides/local-seo.md.

### 7. Reliability/trust infrastructure — MEDIUM
- Jetpack Monitor (free downtime alerts): **OFF** — enable it (Jetpack → Settings, or ask Claude to enable via connector).
- Jetpack Scan: unavailable on free plan — WordPress security basics in guides/wordpress-setup.md instead.
- HTTPS: ✅ working.

### 8. Conversion path — HIGH (this turns SEO into leads)
- Testimonials exist (good) but a lead must be able to act in one tap on mobile: click-to-call + WhatsApp
  + a 3-field quote form. All page templates in `content/` and the `site-preview/index.html` build include these.

## Keyword targets

| Page | Primary keyword | Supporting keywords |
|---|---|---|
| Homepage | transport service kolkata | transporter in kolkata, goods transport kolkata, logistics company kolkata |
| Route: Siliguri | kolkata to siliguri transport | kolkata to siliguri truck, part load kolkata siliguri, transporter for siliguri |
| Route: Sikkim | kolkata to gangtok transport | kolkata to sikkim truck service, transporter for gangtok |
| Route: Bhutan | india to bhutan road transport | kolkata to phuentsholing transport, bhutan cargo service from india |
| Services | full truck load kolkata | part load service kolkata, commercial goods transport |

## Article pipeline (beyond the 3 included)
1. Kolkata to Guwahati transport — charges & transit time
2. Documents needed to send commercial goods to Bhutan (e-way bill, customs at Jaigaon)
3. How to pack fragile/surgical/medical equipment for road transport
4. Monsoon advisory: NH10 Siliguri–Gangtok route status and planning
5. E-way bill rules for West Bengal ↔ Sikkim shipments
6. Warehousing/transshipment at Siliguri — why it matters for North-East cargo
7. Truck types explained: 407 vs 709 vs 22ft container — which do you need?
8. How transport charges are calculated (per kg vs per truck)
9. Sending household goods vs commercial goods — what's different?
10. Why GST-registered transporters matter for your input credit

## Competitor notes
- Competitors rank with modest content — 600–1,000-word route pages. The bar is low; consistent execution wins.
- None dominate "Bhutan transport from Kolkata" strongly — **the Bhutan route page is your fastest win** (lower
  competition, high-value cross-border shipments, and you already serve it).
