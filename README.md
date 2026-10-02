# Shop-Seed Art — Django E-Commerce Platform

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![Django 5.2](https://img.shields.io/badge/Django-5.2-green.svg)](https://www.djangoproject.com/)
[![Build](https://github.com/Techhackontime999/Shop-Seed-Art/actions/workflows/django.yml/badge.svg)](https://github.com/Techhackontime999/Shop-Seed-Art/actions/workflows/django.yml)

**Production:** https://shop-seed-art.onrender.com

A full-featured, production-ready e-commerce platform built on **Django 5.2**.
Shop-Seed Art is a complete marketplace: a multi-currency, multi-language storefront
with a seller marketplace, Razorpay payments (cards / UPI / netbanking) plus
cash-on-delivery, logistics with shipment tracking, coupons and deals, a blog,
moderated reviews, newsletter double opt-in, and a durable background job queue
for emails, fulfilment and refunds.

Sellers get an **AI Product Studio** — a six-step wizard that turns one photo and
a sentence of dictation into a real, correctly placed product listing, with
product-photo enhancement, local voice transcription and AI copy running in the
app itself.

It ships with a one-click **Render blueprint**, a **Heroku-style Procfile**, a
full test suite (772 tests) and a GitHub Actions CI pipeline that runs on
Python 3.12 and 3.13.

---

## Table of Contents

- [Features](#features)
- [AI Product Studio](#ai-product-studio)
  - [How a listing is created](#how-a-listing-is-created)
  - [Image enhancement pipeline](#image-enhancement-pipeline)
  - [Voice and text](#voice-and-text)
  - [Taxonomy-aware publishing](#taxonomy-aware-publishing)
  - [Studio API](#studio-api)
- [Platform Studio](#platform-studio)
- [Schemes for Artisans](#schemes-for-artisans)
  - [The homepage shortcut](#the-homepage-shortcut)
  - [The directory](#the-directory)
  - [Shareable views](#shareable-views)
  - [Saved schemes](#saved-schemes)
  - [Placeholder data, on purpose](#placeholder-data-on-purpose)
  - [Swapping in a real data source](#swapping-in-a-real-data-source)
  - [Where the code lives](#where-the-code-lives)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Local Development](#local-development)
  - [Prerequisites](#prerequisites)
  - [Linux / macOS](#linux--macos)
  - [Windows](#windows)
  - [Environment Variables](#environment-variables)
  - [Trying the AI Product Studio locally](#trying-the-ai-product-studio-locally)
  - [Demo Data](#demo-data)
- [Running Tests](#running-tests)
  - [End-to-end studio suites](#end-to-end-studio-suites)
- [Deployment](#deployment)
  - [Render (one-click)](#render-one-click)
  - [Heroku / generic platforms](#heroku--generic-platforms)
  - [Production environment variables](#production-environment-variables)
- [Production Operations](#production-operations)
  - [Async worker (DB-backed job queue)](#async-worker-db-backed-job-queue)
  - [Scheduled jobs (cron)](#scheduled-jobs-cron)
  - [Refund reconciliation](#refund-reconciliation)
  - [Warming the speech model](#warming-the-speech-model)
  - [Media storage (S3)](#media-storage-s3)
  - [Monitoring (Sentry)](#monitoring-sentry)
- [Security](#security)
- [Contributing](#contributing)
- [License](#license)

---

## Features

**Storefront & catalogue**
- Product catalogue with categories, **subcategories**, multi-image galleries and rich-text (CKEditor) descriptions
- Product **variants** — separate SKU, price and per-variant stock
- Full-text search, daily deals, product sitemap and `robots.txt`
- Scroll-choreographed **role picker** on the homepage that routes a visitor down a seller path or a customer path
- Responsive, mobile-first UI with light/dark themes, font/contrast preferences and accent colours

**Buying experience**
- Shopping cart (session-based, works for guests too) and wishlist
- Coupon codes with usage/over-refund protection and per-user targeting
- Guest checkout with session access + signed, expiring email tokens (guests never see a login wall)
- Multiple shipping methods with estimated delivery windows
- Orders addressed in the URL by **human reference** (`SEED-2026-000149`), not the database key

**Payments (Razorpay + COD)**
- In-page checkout (`checkout.js`) with hosted **Payment Link** fallback
- HMAC-verified browser callbacks and **webhooks** (double-delivery safe and idempotent)
- Cash on Delivery with recorded cash collection on delivery
- **Auto-refunds**: on customer cancellation, insufficient stock, or capture-after-cancel — with a durable retry + reconciliation sweep so funds can never be stranded

**Orders & fulfilment**
- Order status workflow (pending → processing → shipped → delivered / cancelled) with a full audit log
- Tax-inclusive totals (GST), PDF **tax invoices** (ReportLab)
- Cancellation restores stock and refunds captured payments atomically
- Returns/refunds admin with over-refund protection

**Marketplace & sellers**
- Seller registration and admin **verification** flow
- Seller storefronts and listings, configurable marketplace commission
- **Payouts** backed by a ledger (`SellerLedgerEntry`) with a reconciliation command
- **AI Product Studio** — create a listing from one photo and one sentence (see below)

**Logistics (LMS)**
- Courier registry with pluggable providers (mock, mockexpress, delhivery)
- Shipment creation, AWB labels, **tracking timelines** synced from courier APIs
- NDR (non-delivery report) and returns queues
- Courier API credentials encrypted with Fernet

**Content & community**
- **Schemes for Artisans** directory at `/artisan-schemes/` — filterable, sortable, shareable list of support programmes, reachable from a dismissible homepage pill (see below)
- Blog engine: posts, tags, comments, likes, bookmarks, follows, badges/XP and moderation reports
- News ticker, FAQ, About, Services, legal pages, and a customer-facing documentation section
- Moderated product reviews with verified-purchase weighting and a report queue

**Marketing**
- Newsletter with **double opt-in** confirmation
- Coupons, flash deals, and blog post→product linking

**Users & personalization**
- Accounts, customer/seller profiles, password management
- Per-user preferences: theme, language, currency, font size/accent
- In-app **notifications** plus transactional email digests

**Platform & operations**
- Custom admin dashboard with analytics/marketing pages and role-based groups (`customers`, `sellers`, `admins`)
- **Platform Studio** — superuser-only runtime branding and storefront configuration, no code changes (see below)
- **DB-backed async job queue** — durable, leased, retried background jobs
- `/healthz` readiness probe, Sentry error tracking, structured console logging

---

## AI Product Studio

Sellers should not have to become a copywriter and a photographer to list
something. The studio, at **`/seller/ai-studio/`**, walks them through six steps
and publishes a real `Product` row at the end. It is reachable from the **AI
Seller Assistant** card on the seller dashboard; sellers who prefer the
conventional form still have it one click away.

### How a listing is created

| Step | What the seller does | What the app does |
|---|---|---|
| 1 · Image | Uploads a photo | Validates it (format, size, pixels, EXIF orientation) and stores the original |
| 2 · Enhance | Picks a background | Runs the local CV pipeline, shows the staged result and the quality report, lets them keep the original instead |
| 3 · Describe | **Dictates** or types a sentence | Transcribes locally with faster-whisper (Hindi / English / mixed) |
| 4 · AI Catalog | Edits what came back | Generates title, description, SEO keywords and a category placement resolved against the shop's real tree |
| 5 · Smart Price | Moves a slider or types a price | Suggests the shop's own average for that department, and states the basis |
| 6 · Preview | Checks and publishes | Creates an **unpublished** product, copying the chosen image into product storage |

Every step is backed by a real endpoint under `/ai/`. The server keeps the
seller's most recent photo job, so a seller who reloads mid-flow picks up where
they left off, and each enhancement is stored as an `ImageEnhancementJob` with a
stage log, quality metrics, the provider that ran it, and an `is_ai` flag so a
placeholder can never be passed off as a real edit.

### Image enhancement pipeline

Photo enhancement is **entirely local** — Pillow, NumPy and SciPy. No pixel ever
leaves the server and OpenRouter is never used to edit an image. The pipeline
runs ten recorded stages:

```
validate → normalize → segment → clean → background → correct
         → sharpen → format → validate_output
```

- **Segmentation** uses a deterministic classical segmenter (Otsu thresholding on
  an edge-band distance map, largest component containing the centre, hole
  filling, feathered edges). If `rembg` is installed, a **U2Net** segmenter is
  preferred automatically.
- **Correction** does grey-world white balance, exposure against a target luma, a
  smoothstep S-curve and a saturation nudge — but a **fidelity guard** measures
  the colour shift and, if it exceeds tolerance, falls back to an exposure-only
  correction. A product is never silently recoloured.
- **Format** trims empty margins around the product silhouette, scales to fit a
  padded canvas and centres it, returning RGBA when a transparent background was
  chosen.
- An optional **vision advisor** (off by default) can let a vision model read the
  photo and suggest background, exposure, sharpness and framing. Without an API
  key the pipeline simply uses its defaults.

Every job records its stages and quality metrics, so a result can always be
explained after the fact.

### Voice and text

**Dictation runs on a local Whisper model** (`faster-whisper`): no API key, no
per-request cost, no provider rate limit, and the seller's audio never leaves
the server. The model loads once per process, so warm it at deploy time with
`python manage.py preload_speech`. On CPU, the `small` model runs at roughly
0.6× real time and handles Hindi-English code-switching; use `base` on a small
box or `medium` with a GPU.

**Text runs through OpenRouter** and is genuinely optional — the studio is
useable without a key, you just don't get generated copy. Because free model ids
are deprecated and rate limited, the client takes a **fallback list** and tries
each in turn, retrying an empty or truncated response with a larger token budget
rather than showing the seller a blank field.

### Taxonomy-aware publishing

A listing has to land in the shop's real category tree, and this is enforced
rather than assumed:

- The studio's pickers are filled from the live tree, and changing department
  re-scopes its subcategories.
- `shop/taxonomy.py` is the single place that resolves a name to a row, with
  plural folding ("a book" finds *Books*) and a `suggest_*` guess for the
  initial pick.
- The seller's own selection always wins over the model's suggestion.
- A subcategory can never come from a different department.
- **Publish refuses an unknown category or a mismatched subcategory** with a
  message the seller can act on, and never creates a taxonomy row on the fly — a
  typo cannot quietly become a new department.

### Studio API

All endpoints are JSON, require an authenticated user (publish additionally
requires a seller profile), and are rate limited per minute
(`IMAGE_ENHANCEMENT_RATE_LIMIT` 6, `AI_VOICE_RATE_LIMIT` 30, `AI_TTS_RATE_LIMIT`
20, `AI_TEXT_RATE_LIMIT` 60). Every job query is scoped to the requesting user,
so one seller can never read or publish from another's draft.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/ai/image/enhance/` | Run a photo through the enhancement pipeline |
| `POST` | `/ai/image/upload/` | Store a photo as-is (no enhancement) |
| `GET` | `/ai/image/status/<job_id>/` | Poll a job |
| `POST` | `/ai/image/select/` | Choose original or enhanced for a draft |
| `GET` | `/ai/image/draft/` | Fetch the seller's current draft |
| `POST` | `/ai/voice/transcribe/` | Transcribe recorded audio |
| `POST` | `/ai/voice/synthesise/` | Text-to-speech read-back |
| `POST` | `/ai/text/complete/` | General text completion |
| `POST` | `/ai/text/product/catalog/` | Title, description, keywords, placement |
| `POST` | `/ai/text/product/description/` | Product copy from known facts |
| `POST` | `/ai/text/product/keywords/` | SEO keywords |
| `POST` | `/ai/text/product/tags/` | Product tags |
| `POST` | `/ai/text/product/rewrite/` | Rewrite copy for SEO |
| `POST` | `/ai/publish/` | Create the unpublished product |
| `GET` | `/ai/health/` | Provider, segmenter, advisor and speech status |

---

## Platform Studio

Under **Platform Studio** in the admin, a superuser can rebrand and reconfigure
the whole storefront **at runtime, with no code changes** — store name, tagline,
logo, support email, copyright holder, contact details, appearance defaults,
homepage copy, header/footer visibility, SEO and analytics tags, store thresholds
such as currency and per-page limits, and injected custom CSS/JS/HTML.

Settings are typed (`text`, `textarea`, `boolean`, `select`, `color`, `number`),
grouped into Brand & Identity, Appearance, Homepage, Header & Navigation, Footer,
SEO & Analytics, Contact Details, Store Settings and Custom Code. Every save and
every reset writes an admin `LogEntry`, so there is an audit trail, and a
`SiteSetting` admin changelist exposes the raw rows. Note that injected custom
code is rendered unescaped, which is why this area is superuser-only.

---

## Schemes for Artisans

A small, self-contained feature in the **`schemes`** app: a directory of support
schemes for artisans and craftspeople at **`/artisan-schemes/`**
(`schemes:schemes_list`), reached from a pill on the homepage.

It ships **frontend-only on purpose** — there is no model, no query and no
external data source yet. The directory exists so the information architecture
and the interaction design can be reviewed against real content before anyone
commits to a schema. See
[Placeholder data, on purpose](#placeholder-data-on-purpose).

### The homepage shortcut

`shop/partials/schemes_hero_tab.html` renders the pill inside the hero section
(`shop/partials/hero_video.html`), so it is **absolutely positioned, not
`position: fixed`** — it scrolls away with the hero and can never linger over
the sections below.

- The label is one accessible string that CSS collapses **full → short →
  icon-only** as the viewport narrows, so the accessible name never changes and
  no text is truncated by an ellipsis.
- The `×` is a **sibling** `<button>`, not a child of the `<a>`, so dismissing
  the pill can never trigger navigation.
- Dismissal is stored per session in `sessionStorage`
  (`ssArtisanSchemesTabDismissed`). A tiny inline script applies a previous
  dismissal **before first paint**, so the pill never flashes for a visitor who
  already closed it; if `sessionStorage` is unavailable it degrades to a visible
  pill. The CSP already allows inline scripts (`'unsafe-inline'`).
- Below `640px` the pill is full-size and the hero's progress bar and scroll
  hint step aside rather than overlap it — a deliberate trade-off, since the
  pill is the more useful of the two on a phone.
- **The pill is lifted clear of the fold.** The hero is exactly one viewport
  tall (`height: 100dvh`) but starts below the news ticker, so that many pixels
  of its bottom edge hang below the fold — docking the pill to the hero's own
  bottom edge clipped it to a ~10px sliver on every phone and tablet. The tab
  script measures the strip above the hero and lifts the pill by exactly that
  much, publishing it as `--as-tab-lift`; if the hero's content leaves no room,
  the lift shrinks instead of covering the CTA row. Without JS it falls back to
  the `--ds-news-ticker-h` token, and on viewports too short to lift at all it
  stays docked.

### The directory

| Control | Behaviour |
|---|---|
| **Search** | Matches name, provider, category, benefits and eligibility client-side. `/` focuses the field, `Esc` clears it, and `/` is never hijacked while you are typing |
| **Filter chips** | Nine categories, each showing a **live count** computed from the records (Government 3, Equipment 4, …) |
| **Tag chips on cards** | Clicking a tag on a card filters the directory by it, so a card doubles as a way in |
| **Sort** | Curated order · Name A–Z · Name Z–A · Government first |
| **Bookmark** | Per-card save toggle; a **Saved (n)** chip appears in the filter row once something is saved |
| **Clear filters** | Appears only when something is active, and resets search, chips and the saved filter together |

Filter chips and the sort control live in a bar that **sticks under the header**
once the page header scrolls away. Its offset is *measured* from the real header
at runtime (`--as-nav-h`) and falls back to `--ds-navbar-h`, because the token is
slightly shorter than the rendered header and the toolbar would otherwise tuck
underneath it.

Saved and a category **compose**: turning on *Saved* and then *Government*
narrows to saved government schemes and keeps the Saved chip lit.

Accessibility: chips are `aria-pressed` buttons, the results count is an
`aria-live="polite"` status line, the save buttons carry an `.sr-only` label that
swaps between "Save this scheme" and "Remove from saved", and every interactive
target is at least 40px on touch widths.

### Shareable views

The whole view is mirrored into the query string with `history.replaceState`, so
a filtered directory can be bookmarked, pasted into a message or opened on a
phone. Back/forward navigation is honoured via `popstate`.

```
/artisan-schemes/?q=weaver&type=non-government&sort=name-asc&saved=1
```

| Parameter | Values | Meaning |
|---|---|---|
| `q` | free text | Search term |
| `type` | a filter slug, or `all` | Active filter chip |
| `sort` | `curated`, `name-asc`, `name-desc`, `government` | Sort order |
| `saved` | `1` | Saved-only view |

Unknown values fall back to the default rather than emptying the page, and the
search term is lower-cased in the URL while the input keeps the visitor's
original casing.

### Saved schemes

Saved scheme names live in `localStorage` under **`ssSavedSchemes`** — no account,
no server round-trip, works for guests. The chip is hidden until the first save,
and it survives reload, which is why a `saved=1` deep link into an empty list
shows a clear empty state instead of a blank page.

If this ever needs to be per-user, the only change is swapping the storage
adapter in `shop/static/js/schemes.js` for a call to a real endpoint.

### Placeholder data, on purpose

The six records in `schemes/views.py` are **hand-written samples**. None has been
checked against a ministry, board or organisation, so the feature refuses to
imply otherwise:

- `official_url` is `''` and `last_verified` is `None` on every record, so each
  card renders **`Last Verified: —`** instead of a date.
- The card CTA is an **inert `<button>`**, not a link. Clicking it announces,
  in a polite live region, that no official link has been published yet — there
  is no dead link, no invented URL and no `#` target.
- A permanent note above the results says the listings are placeholder content.
- The hero counters are honest by construction: programmes listed, filter
  categories, and **Links published: 0**.
- A test asserts that no record advertises a URL, so honesty cannot regress.

### Swapping in a real data source

`schemes/views.py` deliberately mirrors the future `Scheme` model field-for-field
— `name`, `provider`, `type`, `category`, `description`, `eligible_artisans`,
`benefits`, `state`, `application_method`, `official_url`, `last_verified`,
`active` — so promotion is mechanical:

1. Add the model + migration and register it in `admin.py`.
2. Replace the `SCHEMES` literal with the queryset in `schemes_list()`.
3. Fill `official_url` and `last_verified`; switch the CTA back to a real link in
   the template and delete the inert-button branch and its live region.
4. Flip the copy: drop the placeholder note, and only then show a "Verified"
   date and a real link count.
5. Move search, filtering and sorting server-side (or keep them client-side if the
   dataset stays small) and keep the `data-*` attributes the JS relies on.

### Where the code lives

| Path | Role |
|---|---|
| `schemes/views.py` | Placeholder records, filter/sort definitions, per-filter counts, tag-chip presentation |
| `schemes/urls.py` | `app_name = 'schemes'`, single `schemes_list` route |
| `schemes/templates/schemes/schemes_list.html` | The directory page |
| `schemes/tests.py` | 7 tests: routing, filter counts, no unverified links, presentation |
| `shop/static/css/schemes.css` | Page, toolbar, chips, cards, responsive rules |
| `shop/static/js/schemes.js` | Search, filter, sort, URL state, bookmarks, sticky offset |
| `shop/templates/shop/partials/schemes_hero_tab.html` | Homepage pill + pre-paint dismissal |
| `shop/static/css/schemes-hero-tab.css` · `shop/static/js/schemes-hero-tab.js` | Pill styling, mobile collision handling, dismissal |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 5.2 · Python 3.12 / 3.13 (pinned to 3.13.3 via `.python-version`) |
| Database | SQLite (dev) · PostgreSQL via `dj-database-url` (prod) |
| Cache / Sessions | LocMem or DatabaseCache (dev) · **Redis** (prod, with DB-session fallback) |
| Payments | Razorpay (order creation, payment links, refunds, webhooks) |
| AI — text / vision | **OpenRouter** (optional, no key required) with a fallback model list |
| AI — voice | **faster-whisper** local speech-to-text · browser `speechSynthesis` for read-back |
| AI — image | Local CV pipeline: Pillow · NumPy · SciPy (optional `rembg`/U2Net segmenter) |
| Media | Local filesystem or **Amazon S3** (`django-storages`) |
| Static files | WhiteNoise (`CompressedManifestStaticFilesStorage`) |
| Async jobs | `jobs` app — DB-backed queue drained by `run_worker` |
| PDF / documents | ReportLab, WeasyPrint, python-docx |
| Emails | SMTP / SES, console fallback in dev |
| Monitoring | Sentry SDK (no-op unless `SENTRY_DSN` is set) |
| Frontend | Django templates · Bootstrap 4 (crispy-forms) · custom CSS/JS |
| i18n | Django internationalisation with locale catalogs (`locale/`) |

---

## Project Structure

```
Shop-Seed-Art/
├── config/                  # Project settings & URL routing
│   └── settings/
│       ├── __init__.py      # Picks local/production from DJANGO_ENV
│       ├── local.py         # Dev settings (SQLite, console email, DEBUG=True)
│       └── production.py    # Prod settings (Postgres, HTTPS, security headers)
├── core/                    # Healthz, admin URL overrides, security middleware/CSP,
│                            #   shared URL converters, field encryption, sanitizers, throttling
├── shop/                    # Product catalogue, categories/subcategories, variants,
│                            #   search, sitemap, taxonomy resolution
├── cart/                    # Session-based shopping cart
├── wishlist/                # Wishlist
├── order/                   # Orders, status workflow, stock, invoices, cancellations,
│                            #   access rules (owner / guest token)
├── payments/                # Razorpay orders/payment-links/webhooks, refunds, COD
├── coupons/                 # Coupon codes
├── deals/                   # Flash deals on products
├── accounts/                # Users, customer/seller profiles, verification, KYC media
├── seller/                  # Seller marketplace, listings, commission, payouts/ledger,
│                            #   dashboard, AI Product Studio entry point
├── ai_services/             # AI Product Studio: image enhancement pipeline, local speech,
│                            #   OpenRouter text/vision, publish endpoint
│   ├── clients/             #   OpenRouter client (retries, fallbacks, TTS, vision)
│   ├── services/            #   Enhancement pipeline, segmenters, storage, speech
│   ├── utils/               #   Image I/O and upload validation
│   └── management/commands/ #   preload_speech
├── platform_studio/         # Superuser-only runtime branding & storefront settings
├── logistics/               # Courier integrations, shipments, tracking, NDR/returns
├── reviews/                 # Moderated product reviews
├── blogs/                   # Blog engine (posts, comments, badges, moderation)
├── newsletter/              # Double opt-in newsletter
├── notifications/           # In-app notifications + transactional emails
├── preferences/             # User theme/language/currency preferences, FX rates
├── jobs/                    # DB-backed async job queue (worker + reconciliation)
├── shipping/                # Shipping methods/addresses/shipments (legacy layer)
├── services/ · about/ · contact/ · faq/ · documentation/ · news/ · legal/
│                            # Content/marketing/static pages
├── schemes/                 # Schemes for Artisans directory (frontend-only for now):
│                            #   placeholder records, filter counts, sort, directory page
├── locale/                  # Gettext translation catalogs
├── static/                  # Static assets (collected into staticfiles/ in prod)
├── docs/                    # Customer licence agreement + invoice template documents
├── build.sh                 # Render build phase (deps, migrate, cache table,
│                            #   collectstatic, compilemessages, superuser)
├── setup.sh                 # Release phase for Heroku-style platforms
├── render.yaml              # Render Blueprint (web + worker + cron + Postgres)
├── .python-version          # Pinned Python (3.13.3) — Render honours this
├── Procfile                 # Heroku-style process definitions
├── e2e_studio_*.py          # Playwright end-to-end suites for the AI Studio
├── .env.example             # Documented environment variable template
└── .github/workflows/django.yml  # CI: checks, migrations check, 772 tests
```

---

## Local Development

### Prerequisites

- Python **3.12** or **3.13**
- `pip` and `virtualenv`/`venv`
- (Optional) PostgreSQL if you want to develop against prod-like DB
- (Optional) `rembg` for the U2Net segmenter, and `playwright` for the
  end-to-end studio suites — the image pipeline falls back to the built-in
  classical segmenter without the first, and the e2e scripts are not part of CI

### Linux / macOS

```sh
git clone https://github.com/Techhackontime999/Shop-Seed-Art.git

cd Shop-Seed-Art

python3 -m venv env
source env/bin/activate

pip install -r requirements.txt

cp .env.example .env          # review & adjust values
python manage.py migrate
python manage.py create_default_groups   # customers / sellers / admins
python manage.py createsuperuser
python manage.py runserver
```

Open http://localhost:8000 — the admin is at http://localhost:8000/admin/.

### Windows

```bat
git clone https://github.com/Techhackontime999/Shop-Seed-Art.git
cd Shop-Seed-Art

python -m venv siteenv
siteenv\Scripts\activate

pip install -r requirements.txt

copy .env.example .env
python manage.py migrate
python manage.py create_default_groups
python manage.py createsuperuser
python manage.py runserver
```

There is also an interactive installer, `windows_installation.bat`, which performs
the venv/deps/migrations/superuser steps for you.

> **Windows + WSL:** the repository's `env/` directory is a Linux (WSL) virtual
> environment and will not run on a native Windows Python. Create a fresh venv
> as shown above, or activate it from inside WSL (`source env/bin/activate`,
> `start_wsl.sh`).

### Environment Variables

All configuration is read from the environment, with `.env` auto-loaded in
`config/settings/local.py` / `production.py`. Copy `.env.example` to `.env`
and edit it. The most important variables:

| Variable | Purpose | Default (dev) |
|---|---|---|
| `DJANGO_ENV` | `local` or `production` — selects settings module | `local` |
| `SECRET_KEY` | Django secret key | insecure dev default |
| `FIELD_ENCRYPTION_KEY` | Fernet key for encrypted courier credentials (**required in prod**) | dev default |
| `DATABASE_URL` | PostgreSQL URL (prod); leave empty for SQLite | empty |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | Razorpay API keys | test placeholders |
| `RAZORPAY_WEBHOOK_SECRET` | Webhook signing secret (**required in prod**) | empty |
| `ADMIN_URL` | Obfuscated admin mount path (prod) | `admin/` |
| `AWS_STORAGE_BUCKET_NAME` | S3 bucket for persistent media (recommended prod) | empty |
| `SENTRY_DSN` | Error tracking DSN (optional) | empty |
| `EMAIL_HOST*` | SMTP settings; dev falls back to console email | — |
| `AI_API_KEY` | OpenRouter key for AI **text and vision only** (optional — the studio works without it) | empty |
| `AI_VOICE_PROVIDER` | `local` (Whisper, default), `openrouter`, or `browser` to disable server-side dictation | `local` |
| `AI_SPEECH_MODEL` | `tiny`/`base`/`small`/`medium` — the local Whisper model to load | `small` |
| `AI_TEXT_FALLBACK_MODELS` | Comma-separated model ids tried in order when the primary is unavailable | empty |

See [`.env.example`](./.env.example) for the complete, commented reference. The
AI section there documents every `AI_*` and `IMAGE_ENHANCEMENT_*` variable,
including the Whisper sizing guidance (`small` ≈ 460MB download, ≈1GB RAM) and
the note that `av`, `PyYAML` and `zopfli` need the Python pin to install cleanly.

### Trying the AI Product Studio locally

The studio needs a verified seller account — seed one with `seed_all`, or make
your superuser a seller, then open `/seller/ai-studio/`. Nothing further is
required: image enhancement is local and dictation is local, so the wizard works
with no API key at all. Add `AI_API_KEY` to get generated copy, and warm the
Whisper model once so the first dictation isn't slow:

```sh
python manage.py preload_speech
```

Django will also tell you if the AI configuration is wrong before it bites you —
`python manage.py check` flags a demo provider in production, an unknown
provider/segmenter/advisor/background, `u2net` chosen without `rembg`, and the
vision advisor enabled without an API key.

### Demo Data

Populate the store with realistic demo data (products, variants, categories,
deals, coupons, orders, reviews, blog posts, news, subscribers):

```sh
python manage.py seed_all --preset medium
# presets: tiny | small | medium | large | full
# individual flags: --users --products --orders --reviews --posts --news ...
```

Seed demo users:
- `admin` / `admin123` (superuser + verified seller)
- `priya.sharma` / `test123` and other customers
- `fashion_hub` / `test123` and other sellers

---

## Running Tests

```sh
python manage.py test                 # full suite (772 tests)
python manage.py test ai_services     # the AI Studio app
python manage.py test schemes         # the artisan scheme directory
python manage.py test shop.tests.test_taxonomy
python manage.py test order.tests.test_urls.LegacyOrderUrlTests
python manage.py test order.tests.test_services.OrderViewTests.test_cancel_refunds_captured_payment   # one test
```

The same checks run in CI (`.github/workflows/django.yml`) on Python 3.12 and
3.13: `manage.py check`, `makemigrations --check --dry-run`, then the full test
suite.

### End-to-end studio suites

`e2e_studio_ui_check.py`, `e2e_studio_ui_edge_check.py` and
`e2e_studio_placement_check.py` drive the studio in a real browser via
Playwright; `e2e_ai_studio_check.py` exercises the endpoints over the network.
These make real calls and need `playwright` installed, so they are **scripts, not
CI test cases**:

```sh
pip install playwright && playwright install chromium
python e2e_studio_ui_check.py
```

---

## Deployment

### Render (one-click)

The repository includes a [Render Blueprint](./render.yaml) that provisions
everything needed:

- **PostgreSQL** database
- **Web service** (gunicorn, 2 workers) — health check on `/healthz`
- **Background worker** draining the async job queue (`run_worker`)
- **Cron jobs**: refund reconciliation (every 10 min), job re-arming + keepalive
  (every 5 min), tracking sync (every 30 min), exchange-rate refresh (every 12 h)

Python is pinned to **3.13.3** by `.python-version`, and repeated as
`PYTHON_VERSION` on every service. This matters: without a pin the build follows
whatever Python is newest on the image, and `av`, `PyYAML` and `zopfli` publish
no cp314 wheels, so pip falls back to building from source and dies on missing
ffmpeg/libyaml headers.

To deploy:

1. Push this repository to GitHub.
2. Go to **https://dashboard.render.com/blueprints** → **New Blueprint** → connect the repo.
3. Render auto-detects `render.yaml`. Fill in the `sync: false` values when prompted:
   `SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`,
   `RAZORPAY_WEBHOOK_SECRET`, the `DJANGO_SUPERUSER_*` variables, and
   `KEEPALIVE_URL` (your web service's `/healthz` URL).
4. Migrations, the cache table, `collectstatic`, catalog compilation and the
   superuser are all created in `build.sh`, which runs as the **build command**.

> **Why not a pre-deploy phase?** Render's free tier does not support
> `preDeployCommand`, so those tasks live in `build.sh` and the start command is
> a pure gunicorn — otherwise they would run twice. `setup.sh` still exists for
> platforms that do have a release phase (see below).

> **Plans:** the free tier covers **one web service + one PostgreSQL** database.
> The background worker and cron jobs require a paid plan (Starter and above).
> On a purely free deployment, disable the `worker` and `cron` services — the
> web app still works, but transactional emails, fulfilment and refund retries
> will not drain until a worker runs. Cron services also carry a per-job monthly
> minimum, which is why the keep-alive pings ride the existing `job-reconcile`
> cron instead of adding a fourth.

### Heroku / generic platforms

A `Procfile` is provided:

```
release: bash setup.sh
web: gunicorn config.wsgi --bind 0.0.0.0:$PORT --workers=2 --access-logfile=-
worker: python manage.py run_worker --poll 5 --limit 25
```

`setup.sh` runs the release-phase tasks (collectstatic, migrate, compilemessages,
cache table, superuser). Set the same environment variables as for Render (minus
the Render-specific ones) and add the cron commands via your platform's
scheduler.

### Production environment variables

| Variable | Required | Notes |
|---|---|---|
| `DJANGO_ENV` | ✅ | `production` |
| `SECRET_KEY` | ✅ | unique per deployment |
| `FIELD_ENCRYPTION_KEY` | ✅ | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `DATABASE_URL` | ✅ | e.g. Render/Supabase PostgreSQL |
| `SITE_URL` | ✅ | your canonical domain, e.g. `https://shop-seed-art.onrender.com` — used in emails, invoices, payment links, tracking, SEO previews |
| `ALLOWED_HOSTS` | recommended | comma-separated hosts; defaults to `RENDER_EXTERNAL_URL` |
| `CSRF_TRUSTED_ORIGINS` | recommended | comma-separated origins; same as hosts for HTTPS |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | ✅ | Razorpay live keys |
| `RAZORPAY_WEBHOOK_SECRET` | ✅ | set in the Razorpay dashboard, must match |
| `DJANGO_SUPERUSER_USERNAME/EMAIL/PASSWORD` | optional | auto-creates/updates the superuser on first deploy |
| `AWS_STORAGE_BUCKET_NAME` (+ access key/secret/region) | recommended | persistent media; without it uploads are lost on redeploy |
| `ADMIN_URL` | recommended | random segment, e.g. `x7k2-admin/` |
| `SENTRY_DSN` | optional | error tracking |
| `REDIS_URL` | optional | Redis cache + sessions; otherwise DatabaseCache |
| `AI_API_KEY` | optional | OpenRouter key; unlocks AI text and the vision advisor. The studio works without it |
| `AI_TEXT_MODEL` / `AI_TEXT_FALLBACK_MODELS` | recommended with AI | use `:free` model ids and always list fallbacks — free ids get deprecated |
| `AI_VOICE_PROVIDER` | optional | `local` (Whisper, default), `openrouter`, or `browser` to turn server-side dictation off |
| `KEEPALIVE_URL` | recommended | your web service's `/healthz` URL, pinged by the 5-minute cron so the free web instance never spins down |

**Branding.** Your store name, tagline, logo letter, support email, copyright
holder and contact email are all editable at runtime — no code changes needed —
under **Platform Studio** in the admin (see [Platform Studio](#platform-studio)).
`DEFAULT_FROM_EMAIL` (preset `Shop-Seed Art <no-reply@shop-seed.com>`) is
overridable via env for a custom sender. Every Shop-Seed Art default (name, logo,
emails, demo data) can be replaced to present the platform as your own storefront.

---

## Production Operations

### Async worker (DB-backed job queue)

Transactional emails, fulfilment runs and gateway refunds are enqueued as durable
`jobs.Job` rows instead of blocking the checkout/webhook request path. A worker
drains them with crash-safe leases, exponential backoff and attempt caps:

```sh
python manage.py run_worker --poll 5 --limit 25      # long-lived worker
python manage.py run_worker --once --limit 200       # cron-friendly batch
```

Handlers are idempotent (at-least-once delivery). Jobs that exhaust
`JOB_MAX_ATTEMPTS` are marked `dead` and are reviewable in the admin. A
`reconcile_jobs` run re-arms crashed/stuck jobs even if no worker was alive.

### Scheduled jobs (cron)

- **Tracking sync** — polls courier APIs for in-flight shipments:

  ```sh
  python manage.py sync_tracking_status --limit 100 --min-age-hours 1
  ```

- **Exchange rates** — refresh the cached live FX rates (default every 12 h):

  ```sh
  python manage.py update_currency_rates
  ```

### Refund reconciliation

Auto-refunds (cancellation, insufficient stock, capture-after-cancel) are tried
inline and, on any gateway failure, enqueued as a durable `refund_payment` job.
`reconcile_refunds` sweeps every payment where the gateway took money but it
hasn't been returned yet:

```sh
python manage.py reconcile_refunds --dry-run   # preview first
```

### Warming the speech model

Local dictation loads the Whisper model once per process, which takes a couple of
minutes on first use. Warm it at deploy or worker start-up so the first seller
isn't left waiting:

```sh
python manage.py preload_speech
```

`small` is a ~460MB download and ~1GB of RAM. On a GPU worker set
`AI_SPEECH_DEVICE=cuda` and `AI_SPEECH_COMPUTE_TYPE=float16`. If you have no
spare capacity, `AI_VOICE_PROVIDER=browser` disables server-side dictation
entirely and the studio falls back to the browser's own `SpeechRecognition`.

### Media storage (S3)

Render's disk is ephemeral — uploads are lost on every redeploy. Set
`AWS_STORAGE_BUCKET_NAME`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and
`AWS_S3_REGION_NAME` to serve media from S3. Protected folders
(`protected/`, `seller_documents/`) are never served from the public media URL —
they require the authenticated `accounts:seller_document` view (enforce the same
rule in your S3 bucket policy).

### Monitoring (Sentry)

Set `SENTRY_DSN` to enable error tracking. Optional: `SENTRY_ENVIRONMENT`,
`SENTRY_TRACES_SAMPLE_RATE`, and `GIT_SHA`/`RENDER_GIT_COMMIT` for release tags.

---

## Security

- HTTPS-only production settings (HSTS preload, secure cookies) behind a proxy
- Content-Security-Policy and Permissions-Policy headers via a custom middleware
- Stored-XSS protection: rich text is sanitized on save
- Field-level encryption (Fernet) for courier API credentials
- Obfuscated admin path (`ADMIN_URL`), rate-limited auth endpoints
- Upload validation (MIME/size limits), oversized-body rejection
- Guest order access via signed, expiring tokens; protected KYC media is never public
- Payment webhooks/callbacks verified by HMAC; captures are idempotent and serialized
- **AI Studio**: magic-byte upload sniffing (not just the extension), pixel-count
  and minimum-dimension limits, per-endpoint rate limits, CSRF-protected POSTs,
  and every job query scoped to the owning seller
- **AI Studio**: the non-AI `demo` enhancement provider is a hard **error** in
  production (`manage.py check`), so a placeholder can never reach a live listing
- **AI Studio**: product copy is sanitized as HTML, and publish never creates a
  category row — an unknown category is refused, not invented
- Dictation runs locally, so seller audio never leaves the server

See [SECURITY.md](./SECURITY.md) for how to report a vulnerability.

---

## Contributing

Contributions are welcome — bug fixes, features and documentation. Please read
[CONTRIBUTING.md](./CONTRIBUTING.md) first (branch model, commit conventions,
how to run the checks and open a pull request) and follow our
[Code of Conduct](./CODE_OF_CONDUCT.md).

Looking for what changed recently? See [CHANGELOG.md](./CHANGELOG.md) for the
feature, behaviour-change and deployment history of the project.

Because Shop-Seed Art is a **commercial product**, contributors must agree to the
[Contributor License Agreement](./CLA.md) (the PR template includes the
acknowledgement checkbox). Contributors are credited in
[CONTRIBUTORS.md](./CONTRIBUTORS.md) and may list their work on this project on
their own portfolios — but must not claim ownership of the project.

---

## License

Shop-Seed Art is released under the **Shop-Seed Art Commercial License** — see the
[LICENSE](./LICENSE) file for the full terms.

In short: a licensed copy may be used, modified, and deployed to operate your
own e-commerce business (any number of your own storefronts). **Redistributing,
reselling, or offering the software itself to third parties — as source code or
as a hosted/SaaS platform — requires a separate written agreement.**

Interested in commercial licensing, white-labeling, or reseller terms? Contact
amitkumarkh01012006@gmail.com.
