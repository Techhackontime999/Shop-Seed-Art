/* ═══════════════════════════════════════════════════════════════════════
   Shop-Seed Art — Schemes for Artisans directory page
   -----------------------------------------------------------------------
   Frontend-only wiring for the directory UI. No network calls, no APIs:
     • search field — client-side matching, `/` to focus, Esc to clear
     • filter chips  — single-select (aria-pressed) + per-category counts
     • sort          — curated / A–Z / Z–A / government first
     • saved list    — bookmarks kept in localStorage, shareable via ?saved=1
     • URL state     — q / type / sort / saved, so any view can be shared
     • card CTA      — explains that the official link is not published yet
                       instead of linking out to a made-up address

   Every user-facing string comes from data-* attributes rendered by the
   template, so the page stays translatable.

   Vanilla JS, no dependencies. Everything degrades to a readable, fully
   listed page when JS is unavailable.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var SAVED_KEY = 'ssSavedSchemes';

  function haystack(card) {
    return (card.getAttribute('data-scheme-name') + ' ' +
            card.getAttribute('data-scheme-provider') + ' ' +
            card.getAttribute('data-scheme-category') + ' ' +
            card.getAttribute('data-scheme-type') + ' ' +
            card.textContent).toLowerCase();
  }

  function fill(template, values) {
    return String(template || '').replace(/%\((\w+)\)s/g, function (match, key) {
      return Object.prototype.hasOwnProperty.call(values, key) ? values[key] : match;
    });
  }

  function store(key, value) {
    try {
      if (value === null) window.localStorage.removeItem(key);
      else window.localStorage.setItem(key, value);
    } catch (e) { /* private mode / storage blocked — stay in memory */ }
  }

  function readStore(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }

  /* ── Saved schemes ────────────────────────────────────────────────── */
  function readSaved() {
    var raw = readStore(SAVED_KEY);
    if (!raw) return [];
    try {
      var parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed.filter(function (v) { return typeof v === 'string'; }) : [];
    } catch (e) { return []; }
  }

  function initDirectory() {
    var grid = document.querySelector('[data-schemes-grid]');
    if (!grid) return;

    var cards = Array.prototype.slice.call(grid.querySelectorAll('[data-schemes-card]'));
    if (!cards.length) return;

    var chips = Array.prototype.slice.call(document.querySelectorAll('[data-schemes-filter]'));
    var input = document.querySelector('[data-schemes-search]');
    var clearBtn = document.querySelector('[data-schemes-search-clear]');
    var countOut = document.querySelector('[data-schemes-count]');
    var emptyState = document.querySelector('[data-schemes-empty]');
    var resetBtn = document.querySelector('[data-schemes-reset]');
    var sortSelect = document.querySelector('[data-schemes-sort]');
    var toolbar = document.querySelector('[data-schemes-toolbar]');
    var savedChip = document.querySelector('[data-schemes-filter="saved"]');
    var savedCountOut = document.querySelector('[data-schemes-saved-count]');
    var clearAllBtn = document.querySelector('[data-schemes-clear-all]');

    var haystacks = cards.map(haystack);
    var tagLists = cards.map(function (card) {
      return (card.getAttribute('data-scheme-tags') || '').split(/\s+/).filter(Boolean);
    });
    var typeLists = cards.map(function (card) {
      return (card.getAttribute('data-scheme-type') || '').toLowerCase();
    });
    var order = cards.map(function (_card, i) { return i; });
    var names = cards.map(function (card) { return card.getAttribute('data-scheme-name') || ''; });

    var knownFilters = chips.map(function (chip) { return chip.getAttribute('data-schemes-filter'); });
    var knownSorts = sortSelect
      ? Array.prototype.map.call(sortSelect.options, function (o) { return o.value; })
      : ['curated'];

    var state = { query: '', filter: 'all', sort: 'curated', savedOnly: false };
    var saved = readSaved();

    /* ── URL <-> state ─────────────────────────────────────────────── */
    function readUrl() {
      var params = new URLSearchParams(window.location.search);
      state.query = params.get('q') || '';
      state.savedOnly = params.get('saved') === '1';

      var type = params.get('type');
      state.filter = type && knownFilters.indexOf(type) !== -1 ? type : 'all';

      var sort = params.get('sort');
      state.sort = sort && knownSorts.indexOf(sort) !== -1 ? sort : 'curated';
    }

    function writeUrl() {
      var params = new URLSearchParams();
      if (state.query) params.set('q', state.query);
      if (state.filter !== 'all') params.set('type', state.filter);
      if (state.sort !== 'curated') params.set('sort', state.sort);
      if (state.savedOnly) params.set('saved', '1');
      var qs = params.toString();
      try {
        window.history.replaceState(null, '', qs ? '?' + qs : window.location.pathname);
      } catch (e) { /* file:// or locked history — the page still works */ }
    }

    /* ── Sorting ───────────────────────────────────────────────────── */
    function sortedCards() {
      var idx = cards.map(function (_card, i) { return i; });
      if (state.sort === 'name-asc') {
        idx.sort(function (a, b) { return names[a].localeCompare(names[b], undefined, { sensitivity: 'base' }); });
      } else if (state.sort === 'name-desc') {
        idx.sort(function (a, b) { return names[b].localeCompare(names[a], undefined, { sensitivity: 'base' }); });
      } else if (state.sort === 'government') {
        idx.sort(function (a, b) {
          var ga = typeLists[a] === 'government' ? 0 : 1;
          var gb = typeLists[b] === 'government' ? 0 : 1;
          return ga !== gb ? ga - gb : order[a] - order[b];
        });
      }
      return idx.map(function (i) { return cards[i]; });
    }

    function paintOrder() {
      sortedCards().forEach(function (card) { grid.appendChild(card); });
      if (emptyState) grid.appendChild(emptyState);
    }

    /* ── Apply ─────────────────────────────────────────────────────── */
    function apply() {
      var shown = 0;

      cards.forEach(function (card, index) {
        var savedOk = !state.savedOnly || saved.indexOf(names[index]) !== -1;
        var tagOk = state.filter === 'all'
          || state.filter === 'saved'
          || tagLists[index].indexOf(state.filter) !== -1;
        var textOk = !state.query || haystacks[index].indexOf(state.query) !== -1;
        var visible = savedOk && tagOk && textOk;
        card.hidden = !visible;
        if (visible) shown += 1;
      });

      paintOrder();

      if (countOut) {
        var list = shown === 1
          ? countOut.getAttribute('data-count-one')
          : fill(countOut.getAttribute('data-count-plural'), { count: shown });
        var label = state.filter === 'all'
          ? ''
          : ' · ' + (chipLabel(state.filter) || '');
        countOut.textContent = list + label;
      }

      if (emptyState) emptyState.hidden = shown !== 0;
      if (clearAllBtn) clearAllBtn.hidden = !isFiltered();

      paintSaved();
    }

    function chipLabel(slug) {
      var chip = chips.filter(function (c) { return c.getAttribute('data-schemes-filter') === slug; })[0];
      if (!chip) return '';
      var span = chip.querySelector('.as-chip-text');
      return span ? span.textContent.trim() : chip.textContent.trim();
    }

    function isFiltered() {
      return !!state.query || state.filter !== 'all' || state.savedOnly;
    }

    /* ── Saved painting ────────────────────────────────────────────── */
    function paintSaved() {
      cards.forEach(function (card, index) {
        var isSaved = saved.indexOf(names[index]) !== -1;
        var btn = card.querySelector('[data-schemes-save]');
        if (!btn) return;
        btn.setAttribute('aria-pressed', isSaved ? 'true' : 'false');
        btn.classList.toggle('is-saved', isSaved);
        var label = btn.getAttribute('data-label-off');
        var on = btn.getAttribute('data-label-on');
        var text = btn.querySelector('[data-schemes-save-text]');
        if (text) text.textContent = isSaved ? on : label;
        btn.setAttribute('aria-label', isSaved ? on : label);
        btn.setAttribute('title', isSaved ? on : label);
      });

      if (savedCountOut) savedCountOut.textContent = saved.length;
      if (savedChip) {
        /* Kept visible while the view is filtered to saved schemes, so the
           control never disappears while it is the active filter. */
        savedChip.hidden = saved.length === 0 && !state.savedOnly;
        savedChip.classList.toggle('is-on', state.savedOnly);
        savedChip.setAttribute('aria-pressed', state.savedOnly ? 'true' : 'false');
      }
    }

    function toggleSaved(name) {
      var at = saved.indexOf(name);
      if (at === -1) saved.push(name); else saved.splice(at, 1);
      store(SAVED_KEY, JSON.stringify(saved));
    }

    /* ── Controls ──────────────────────────────────────────────────── */
    function selectChip(slug) {
      state.filter = slug;
      chips.forEach(function (chip) {
        /* The Saved chip is painted by paintSaved() instead: it stays lit
           while a category is active on top of it. */
        var chipSlug = chip.getAttribute('data-schemes-filter');
        var isActive = chipSlug === slug && chipSlug !== 'saved';
        chip.classList.toggle('is-active', isActive);
        chip.setAttribute('aria-pressed', isActive ? 'true' : 'false');
      });
    }

    function syncClearButton() {
      if (clearBtn) clearBtn.hidden = !input.value.length;
    }

    function setSearch(value, focus) {
      state.query = String(value || '').trim().toLowerCase();
      if (input) input.value = value || '';
      syncClearButton();
      apply();
      writeUrl();
      if (focus && input) input.focus();
    }

    function resetAll(focus) {
      selectChip('all');
      state.savedOnly = false;
      if (sortSelect) sortSelect.value = state.sort;
      setSearch('', false);
      apply();
      if (focus && input) input.focus();
    }

    if (input) {
      input.addEventListener('input', function () { setSearch(input.value, false); });
      if (clearBtn) {
        clearBtn.addEventListener('click', function () { setSearch('', true); });
      }
    }

    chips.forEach(function (chip) {
      chip.addEventListener('click', function () {
        var slug = chip.getAttribute('data-schemes-filter');
        if (slug === 'saved') {
          state.savedOnly = !state.savedOnly;
          selectChip(state.savedOnly ? 'saved' : 'all');
        } else {
          selectChip(slug);
        }
        apply();
        writeUrl();
      });
    });

    if (sortSelect) {
      sortSelect.addEventListener('change', function () {
        state.sort = knownSorts.indexOf(sortSelect.value) === -1 ? 'curated' : sortSelect.value;
        apply();
        writeUrl();
      });
    }

    [resetBtn, clearAllBtn].forEach(function (btn) {
      if (btn) btn.addEventListener('click', function () { resetAll(true); });
    });

    Array.prototype.forEach.call(document.querySelectorAll('[data-schemes-save]'), function (btn) {
      btn.addEventListener('click', function () {
        toggleSaved(btn.getAttribute('data-scheme-name'));
        paintSaved();
        if (state.savedOnly) apply();
        writeUrl();
      });
    });

    /* Tag chips double as filter triggers. */
    Array.prototype.forEach.call(document.querySelectorAll('[data-schemes-tag]'), function (chip) {
      chip.addEventListener('click', function () {
        var slug = chip.getAttribute('data-schemes-tag');
        selectChip(state.filter === slug ? 'all' : slug);
        apply();
        writeUrl();
      });
    });

    /* ── Keyboard ──────────────────────────────────────────────────── */
    function typingInto(el) {
      if (!el) return false;
      var tag = el.tagName;
      return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
    }

    document.addEventListener('keydown', function (event) {
      if (event.key === '/' && !typingInto(event.target) && !event.metaKey && !event.ctrlKey && !event.altKey) {
        if (!input) return;
        event.preventDefault();
        input.focus();
        input.select();
        return;
      }
      if (event.key === 'Escape') {
        if (input && document.activeElement === input && input.value) {
          event.preventDefault();
          setSearch('', true);
        }
      }
    });

    window.addEventListener('popstate', function () {
      readUrl();
      if (input) input.value = state.query;
      syncClearButton();
      selectChip(state.savedOnly ? 'saved' : state.filter);
      if (sortSelect) sortSelect.value = state.sort;
      apply();
    });

    /* ── Boot ──────────────────────────────────────────────────────── */
    readUrl();
    if (input) input.value = state.query;
    selectChip(state.savedOnly ? 'saved' : state.filter);
    if (sortSelect) sortSelect.value = state.sort;
    syncClearButton();
    apply();
    writeUrl();

    if (toolbar && 'IntersectionObserver' in window) {
      var sentinel = document.querySelector('[data-schemes-toolbar-sentinel]');
      if (sentinel) {
        new IntersectionObserver(function (entries) {
          toolbar.classList.toggle('is-stuck', !entries[0].isIntersecting);
        }, { threshold: 0 }).observe(sentinel);
      }
    }

    /* The sticky bar needs the header's real height: --ds-navbar-h is a few
       pixels short of it once the header's own padding is counted, which would
       let the bar slide under the navbar. */
    function measureHeader() {
      var header = document.querySelector('.nav-aq');
      if (!header) return;
      var height = Math.round(header.getBoundingClientRect().height);
      if (height > 0) {
        document.documentElement.style.setProperty('--as-nav-h', height + 'px');
      }
    }

    if (toolbar) {
      measureHeader();
      window.addEventListener('resize', measureHeader);
    }
  }

  /* ── Inert CTAs ─────────────────────────────────────────────────────
     Placeholder cards have no official URL, so the button cannot be a real
     outbound link. It stays a button and states the truth instead. */
  function initCtas() {
    var status = document.querySelector('[data-schemes-cta-status]');
    if (!status) return;

    var template = status.getAttribute('data-pending-template');

    Array.prototype.forEach.call(document.querySelectorAll('[data-schemes-cta]'), function (btn) {
      btn.addEventListener('click', function () {
        status.textContent = fill(template, { name: btn.getAttribute('data-scheme-name') || '' });
        status.hidden = false;
      });
    });
  }

  function boot() {
    initDirectory();
    initCtas();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();