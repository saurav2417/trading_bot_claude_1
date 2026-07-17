# WordPress Technical SEO Setup — hrctransport.com

Do these in order from your WordPress admin (wp-admin). Total time: ~2 hours.

## 1. Install Rank Math SEO (free)
1. Plugins → Add New → search **"Rank Math SEO"** → Install → Activate.
2. Run the Setup Wizard:
   - Site type: **Small Business** → Category: **Local Business** → sub-type **MovingCompany** (closest match).
   - Enter business name **HRC Transport**, address `[VERIFY-ADDRESS]`, phone `+91-XXXXX-XXXXX` — must match your Google Business Profile exactly.
   - Enable the **Sitemap** module. Note the sitemap URL: `https://hrctransport.com/sitemap_index.xml`.
3. Rank Math → Titles & Meta → Homepage: paste the title/meta from `content/homepage.md`.

## 2. Permalinks
Settings → Permalinks → select **Post name**. (If the site is old and URLs change, Rank Math's redirection module
will handle old → new; enable it.)

## 3. Reading settings — the indexation killer
Settings → Reading → make sure **"Discourage search engines from indexing this site" is UNCHECKED.**
This single checkbox is the most common cause of a one-page index.

## 4. Google Search Console (GSC)
1. Go to https://search.google.com/search-console → Add property → **Domain** → `hrctransport.com`.
2. Verify via DNS TXT record (your domain registrar) — or use the URL-prefix method + Rank Math's
   "Search Console" verification field if DNS is hard.
3. Sitemaps → submit `sitemap_index.xml`.
4. After publishing each new page: URL Inspection → paste URL → **Request Indexing**.
5. Weekly habit: Performance report → see which queries get impressions → improve those pages.

## 5. Bing Webmaster Tools (5 minutes, free extra traffic)
https://www.bing.com/webmasters → "Import from Google Search Console". Done.

## 6. Speed & Core Web Vitals
1. Test at https://pagespeed.web.dev for mobile. Target: LCP < 2.5s.
2. Install **LiteSpeed Cache** (if host is LiteSpeed) or **WP Super Cache** (any host). Enable page caching.
3. Compress images before upload (https://squoosh.app) — max ~150 KB for hero images, use WebP.
4. Remove unused plugins/themes entirely (deactivate AND delete).

## 7. Security basics (free Jetpack has no Scan)
- Install **Wordfence** (free) → enable firewall + login rate limiting.
- All admin accounts: strong unique passwords + 2FA (Wordfence or Jetpack's SSO).
- Updates: WordPress core, theme, plugins — set auto-update on for plugins you trust.
- Backups: **UpdraftPlus** (free) → weekly backup to Google Drive.
- ✅ Jetpack downtime Monitor: already enabled (2026-07-17) — alerts go to the site owner's email.

## 8. Site-wide conversion elements (leads!)
- Header: phone number as a clickable `tel:` link, visible on every page without scrolling.
- Floating WhatsApp button on mobile. Plugin: **"Click to Chat"** (free) → set number `+91XXXXXXXXXX`,
  prefilled message: "Hi HRC Transport, I need a quote for goods transport."
- Footer on every page: full NAP block (Name, Address, Phone) — identical to GBP — plus link `[GBP-LINK]`.

## 9. Analytics
- Install **Site Kit by Google** (free) → connects Analytics (GA4) + Search Console into wp-admin.
- In GA4, mark these as conversions: `tel:` clicks, WhatsApp clicks, quote-form submissions.
- This is how you'll literally count SEO leads.

## 10. Publishing the content in this package
For each file in `content/`:
1. Pages → Add New. Title = the H1 given in the file. Slug = the slug given in the file (Permalink → edit).
2. Paste the body (WordPress converts markdown headings if you paste into the block editor as markdown;
   otherwise use headings blocks manually).
3. In the Rank Math box below the editor: paste the **SEO Title** and **Meta Description** from the file.
4. Paste the FAQ JSON-LD from the file into a **Custom HTML block** at the end of the page.
5. Publish → GSC → Request Indexing.
Add every route page to Appearance → Menus → main menu.
