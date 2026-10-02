# Changelog

All notable changes to Shop-Seed Art are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
semantic-ish version labels for releases.

Entries are grouped by the kind of change they make to the product, so you can
scan for the thing you care about (a new seller feature, a deployment fix, a
behaviour change) without reading the whole file.

---

## [Unreleased] — since `v1.0` (2026-09-22)

The initial release covered the storefront, marketplace, payments, logistics and
background-job foundations. Everything below landed after that and is the first
thing to look at if you are picking the project up fresh.

### Added — AI Product Studio (seller-facing)

This is the largest addition. Sellers can now create a complete, correctly
placed product listing from a single photo and a sentence of dictation.

- **New app `ai_services`** — image, voice and text endpoints mounted under
  `/ai/`:
  - `POST /ai/image/enhance/` — run a photo through the local enhancement
    pipeline (segment → clean edges → composite background → white balance →
    exposure/S-curve → saturation → sharpen → trim/centre → verify).
  - `POST /ai/image/upload/` — accept a photo as-is, for sellers who skip
    enhancement but still need it attached at publish time.
  - `POST /ai/voice/transcribe/` — server-side dictation. Runs a **local
    faster-whisper** model, so audio never leaves the server and there is no
    per-request cost or rate limit. Supports Hindi, English and
    Hindi-English code-switching.
  - `POST /ai/voice/synthesise/` — text-to-speech read-back.
  - `POST /ai/text/product/catalog/` — generate title, description, keywords
    and a taxonomy placement in one call.
  - `POST /ai/text/product/description/`, `.../keywords/`, `.../tags/`,
    `.../rewrite/`, and `POST /ai/text/complete/` — general copy and SEO helpers.
  - `POST /ai/publish/` — create a real (unpublished) `Product` from the studio
    state, validating the category and copying the chosen image into product
    storage.
  - `GET /ai/health/` — reports provider, segmenter, advisor and speech status.
- **New model `ImageEnhancementJob`** — tracks every enhancement: original and
  enhanced files, background choice, stage log, quality metrics, provider name,
  an `is_ai` honesty flag, and a safe failure code/message. Owned by the seller.
- **New 6-step wizard** at `/seller/ai-studio/` (`seller:ai_studio`):
  Image → Enhance → Describe → AI Catalog → Smart Price → Preview. Each step is
  wired to a real endpoint; the seller can jump back and forth, and the stepper
  always shows where they are.
- **Local CV pipeline** (`ai_services/services/`) built on Pillow + NumPy + SciPy:
  - Deterministic **classical segmenter** (Otsu thresholding on an edge-band
    distance map, largest component containing the centre, hole filling,
    feathered edges).
  - Optional **U2Net** segmenter via `rembg`, auto-detected when installed.
  - A **fidelity guard**: if white balance would shift the product's colour
    beyond a tolerance, the pipeline falls back to an exposure-only correction
    rather than shipping a recoloured product.
  - A **vision advisor** (opt-in, off by default) that lets a vision model read
    the photo and suggest background, exposure, sharpness and framing.
- **Django system checks** (`ai_services/checks.py`) — flags a demo provider in
  production, an unknown provider/segmenter/advisor/background, `u2net`
  selected without `rembg` installed, and the advisor enabled without an API key.
- **New management command `preload_speech`** — loads the Whisper model at
  deploy or worker start-up so the first seller isn't left waiting minutes.
- **AI Seller Assistant card** on the seller dashboard, linking straight into
  the studio. The normal add-product form is still one click away.

### Added — product taxonomy

- **New `SubCategory` model** and `Product.subcategory`, editable inline on
  `Category` in the admin.
- **New `shop/taxonomy.py`** — the single place that resolves a name to a
  category or subcategory row, with plural folding ("a book" finds *Books*),
  `suggest_category` / `suggest_subcategory` for the studio's initial guess, and
  live-product price stats used to suggest a price.
- **Migration `0008_seed_subcategories`** seeds the second level for every
  department that already exists, idempotently, and never invents a department
  that isn't in the database.
- The studio's pickers are filled from the real tree, changing department
  re-scopes its subcategories, and the suggested price is the shop's own average
  for that department with the basis stated.

### Added — storefront

- **Role picker on the homepage** — a scroll-choreographed "Two ways in" section
  that routes a visitor down a seller path (7 steps, 5 capability chips) or a
  customer path (4 steps, 5 discovery chips). Sellers already signed in land on
  their dashboard; everyone else is sent to seller onboarding. Fully
  reduced-motion aware, and renders in its final state without JavaScript.
- **Platform Studio** — a superuser-only UI over the `SiteSetting` store, covering
  branding, appearance, homepage copy, header/footer, SEO, contact details,
  store settings and injected custom CSS/JS/HTML. Every save writes an admin
  `LogEntry` audit record.

### Added — Schemes for Artisans directory (artisan-facing)

A directory of support schemes for artisans and craftspeople at
**`/artisan-schemes/`** (`schemes:schemes_list`), reachable from a pill on the
homepage. **New app `schemes`**, registered in both the local and production
settings and mounted from `config/urls.py`.

**Deliberately frontend-only.** There is no model, no query and no external data
source yet — the app exists so the information architecture and the interaction
design can be reviewed against real content before anyone commits to a schema.

- **Homepage pill** (`shop/partials/schemes_hero_tab.html`) rendered *inside* the
  hero and absolutely positioned rather than `position: fixed`, so it scrolls
  away with the hero and can never linger over the sections below. The label is
  one accessible string that CSS collapses full → short → icon-only as the
  viewport narrows. The `×` is a **sibling** button, not a child of the link, so
  dismissing it can never trigger navigation. Dismissal is per session
  (`ssArtisanSchemesTabDismissed`) and applied by a small inline script **before
  first paint**, so it never flashes; blocked storage degrades to a visible pill.
- **Directory page** with client-side search (`/` focuses the field, `Esc` clears
  it, and `/` is never hijacked while typing), nine filter chips each carrying a
  **live count** computed from the records, tag chips on cards that filter the
  directory when clicked, a sort control (curated / A–Z / Z–A / government
  first), per-card bookmarks and a **Saved (n)** chip that appears on first save.
- **Sticky filter/sort toolbar** that pins under the header once the page header
  scrolls away. Its offset is measured from the real header at runtime
  (`--as-nav-h`) and falls back to `--ds-navbar-h`, because that token is a few
  pixels shorter than the rendered header.
- **Shareable, restorable views.** Search, filter, sort and the saved list are
  mirrored into `?q=`, `?type=`, `?sort=` and `?saved=1` with
  `history.replaceState`, restored on load and honoured on back/forward via
  `popstate`, so a filtered directory can be bookmarked or pasted into a message.
  Saved schemes persist in `localStorage` (`ssSavedSchemes`) — no account needed.
- **Honest by construction.** The six records are hand-written placeholders, so
  `official_url` is empty and `last_verified` is `None` on every one: each card
  renders `Last Verified: —`, and the card CTA is an **inert button** that
  announces in a polite live region that no official link has been published yet
  — no dead links, no invented URLs. A permanent note says the listings are
  placeholders, and the hero counters report **Links published: 0**. A test
  asserts no record advertises a URL, so this cannot regress.
- **Promotion path documented** — the record keys mirror the future `Scheme`
  model field-for-field, so swapping the literal for a queryset is a mechanical
  change (see the README).
- Below `640px` the pill stays full-size and the hero's progress bar and scroll
  hint step aside instead of overlapping it — a conscious trade-off, since the
  pill is the more useful of the two on a phone.
- `schemes/tests.py` adds 7 tests covering routing, per-filter counts, the
  no-unverified-link guarantee and the presentation layer.

### Changed

- **Orders are addressed by reference, not primary key.** Order, payment,
  shipping and seller-status URLs now use `SEED-2026-000149` instead of `149`,
  via a new `orderref` path converter (`core/converters.py`). The reference is
  what sellers and customers already read in emails, notifications, shipping
  labels and the admin, so a bookmark now looks like a receipt.
- **Legacy numeric order URLs still work and are permanently redirected (301)**
  to the reference form — except on POST, which is handled in place, because a
  301 would turn a cancellation into a no-op. Access control is identical on both
  forms.
- **Text output is now model-fallback aware.** `AI_TEXT_FALLBACK_MODELS` lets the
  studio try a list of free models in order, and an empty or truncated response
  is retried with a larger token budget rather than surfaced as a blank field.
- **The seller add-product form is no longer AI-powered.** The earlier
  AI-powered creation in the standard form was reverted so the classic form stays
  predictable; the AI path is the dedicated studio.

### Fixed

- Render builds no longer fail on missing ffmpeg/libyaml headers. Python is
  pinned to **3.13.3** via a new `.python-version` file (and repeated as
  `PYTHON_VERSION` on every service in `render.yaml`), because `av`, `PyYAML`
  and `zopfli` publish no cp314 wheels and pip was falling back to building from
  source.
- `render.yaml` no longer references `preDeployCommand`, which the free tier does
  not support. Migrations, the cache table, `collectstatic`, catalog compilation
  and superuser creation moved into `build.sh` (the build command), and the start
  command is a pure gunicorn so they never run twice. `setup.sh` remains for the
  Heroku `release` phase.
- Cron services are declared inside `services:` with `type: cron`, per Render's
  Blueprint spec.
- Razorpay payment links are created without the unsupported `theme` field.
- The CKEditor init script is repaired and the seller editor is fluid at every
  width.
- The AI Studio no longer assumes the catalog service returns placement keys, its
  taxonomy JSON is emitted as a real data block, and a leaked `{# #}` template
  comment containing `<script>` no longer reaches the browser.
- Manual price entry in the studio commits as it is typed and widens the slider,
  instead of being clamped to a fixed window.
- The homepage "Schemes for Artisans" pill was clipped to a ~10px sliver on every
  phone and tablet. The hero is exactly one viewport tall (`height: 100dvh`) but
  begins below the news ticker, so the bottom strip of the hero — and the pill
  docked to it — sits below the fold at scroll 0. `js/schemes-hero-tab.js` now
  measures the chrome above the hero and lifts the pill by that amount
  (`--as-tab-lift`), keeping it in step through a `ResizeObserver` and on resize.
  The lift is capped by the room the hero's CTA row leaves, so on a short
  viewport it shrinks rather than covering the CTAs, and is skipped entirely
  where there is no room to lift (measured at 320–1366px: fully visible from
  375×667 up, partially but collision-free at 360×640). Without JS the
  `--ds-news-ticker-h` token is the fallback.
- Dictation is now usable rather than merely present: the guide highlights the one
  thing to do next instead of a button that may not exist, a silent recording
  says what to hear and what to do about it, and Generate sits below both the
  voice and type tabs so it can't be missed.
- An unused vendored FontAwesome webfont copy is no longer collected into
  `staticfiles/` on every build.

### Housekeeping

- Gitignored the throwaway studio debugging artefacts (one-off probe scripts,
  evidence screenshots, synthetic audio used to prove the speech service rejects
  silence). The suites that are kept live at the repo root as
  `e2e_studio_*.py`.
- New dependencies: `faster-whisper`, `av`, `numpy`, `scipy` (for local
  dictation and the image pipeline). `rembg` is optional and only needed for the
  U2Net segmenter.
- `ai_services` added ~264 tests across 7 test modules; `shop/tests/test_taxonomy.py`
  adds 23 more, and the new `schemes` app adds 7. The suite is now **772 tests**,
  all passing.

---

## [1.0] — 2026-09-22

Initial Shop-Seed Art release: Django 5.2 multi-currency, multi-language
marketplace with a seller marketplace, Razorpay payments plus cash-on-delivery,
logistics with tracking, coupons and deals, a blog, moderated reviews, a double
opt-in newsletter, a durable background job queue, a Render blueprint, and a
GitHub Actions CI pipeline.
