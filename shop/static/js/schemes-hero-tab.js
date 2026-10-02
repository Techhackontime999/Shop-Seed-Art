/* ═══════════════════════════════════════════════════════════════════════
   Shop-Seed Art — "Schemes for Artisans" hero tab
   -----------------------------------------------------------------------
   Three jobs, all frontend-only:
     1. Dismiss  — × hides the tab for the rest of the session
                   (sessionStorage) without navigating anywhere.
     2. Lift     — below 1200px the tab is docked to the hero's bottom edge.
                   The hero is exactly one viewport tall but starts below the
                   news ticker, so its bottom edge — and therefore the tab —
                   hangs below the fold and is clipped to a sliver. This
                   measures the strip above the hero and lifts the tab by it,
                   never so far that the tab would cover the hero's CTAs.
     3. Boundary — the tab is already scoped to the hero by CSS; this only
                   hides it a moment earlier, as soon as the hero has scrolled
                   up behind the fixed navbar, so it can never be seen
                   floating over the next section.

   Vanilla JS, no dependencies. Storage failures (private mode, blocked
   cookies) are swallowed: the tab then simply behaves like a normal link.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var EXIT_CLASS = 'is-out-of-hero';
  var DISMISS_CLASS = 'is-dismissed';
  var LIFT_VAR = '--as-tab-lift';
  var JS_FLAG = 'as-tab-js';
  /* Breathing room the lifted tab must leave above the hero's CTA row. */
  var MIN_GAP = 10;

  function storageKey(tab) {
    return tab.getAttribute('data-storage-key') || 'ssArtisanSchemesTabDismissed';
  }

  function readDismissed(key) {
    try {
      return window.sessionStorage.getItem(key) === '1';
    } catch (e) {
      return false;
    }
  }

  function writeDismissed(key) {
    try {
      window.sessionStorage.setItem(key, '1');
    } catch (e) { /* keep working without persistence */ }
  }

  function setUpDismissal(tab) {
    var closeBtn = tab.querySelector('[data-schemes-tab-close]');
    if (!closeBtn) return;

    closeBtn.addEventListener('click', function (e) {
      // A <button> inside the pill: stop the click from ever reaching the
      // surrounding link, so dismissing cannot navigate.
      e.preventDefault();
      e.stopPropagation();
      tab.classList.add(DISMISS_CLASS);
      writeDismissed(storageKey(tab));
      closeBtn.blur();
    });
  }

  /* Hides the tab once the hero's bottom edge passes the fixed header.
     Uses the hero the tab lives in, so it works for both the video and the
     static hero variant. */
  function setUpHeroBoundary(tab) {
    var hero = tab.closest('[data-hero-video]');
    if (!hero) return;

    var ticking = false;

    function update() {
      ticking = false;
      var heroBottom = hero.getBoundingClientRect().bottom;
      var header = document.querySelector('.nav-aq');
      var clearance = header ? header.getBoundingClientRect().height + 8 : 0;
      var gone = heroBottom <= clearance;
      tab.classList.toggle(EXIT_CLASS, gone);
    }

    function onScroll() {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(update);
    }

    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    update();
  }

  /* Publishes how far the tab may be lifted clear of the fold, as a CSS custom
     property. `wanted` is the chrome above the hero — the strip that pushes the
     hero's bottom edge below the viewport. `allowed` is how much of that the
     hero's own content leaves free; on a short viewport the content already
     fills the band under the navbar, so the lift shrinks instead of colliding
     with the CTA row. */
  function setUpLift(tab) {
    var hero = tab.closest('[data-hero-video]');
    if (!hero) return;

    var wide = window.matchMedia('(min-width: 1200px)');

    function update() {
      /* ≥1200px the tab sits in the left gutter, centred vertically — nothing to
         lift, and the variable must not linger if the viewport is resized. */
      if (wide.matches) {
        document.documentElement.style.removeProperty(LIFT_VAR);
        return;
      }

      var tabRect = tab.getBoundingClientRect();
      if (!tabRect.height) return;

      var heroRect = hero.getBoundingClientRect();
      var wanted = Math.max(0, Math.round(heroRect.top + window.scrollY));
      var allowed = wanted;

      var actions = hero.querySelector('.hero-video-aq-actions');
      if (actions) {
        var free = heroRect.bottom - actions.getBoundingClientRect().bottom
                 - tabRect.height - MIN_GAP;
        allowed = Math.min(wanted, Math.max(0, Math.round(free)));
      }

      document.documentElement.style.setProperty(LIFT_VAR, allowed + 'px');
    }

    update();
    window.addEventListener('resize', update, { passive: true });
    window.addEventListener('load', update);
    if (wide.addEventListener) wide.addEventListener('change', update);
    /* Late webfonts and the hero's own height changes move the CTA row. */
    if (window.ResizeObserver) {
      new ResizeObserver(update).observe(hero);
    }
  }

  function init() {
    var tab = document.querySelector('[data-schemes-tab]');
    if (!tab) return;

    /* Lets CSS tell "JS is running, trust --as-tab-lift" from the no-JS
       fallback, so the short-viewport guard cannot fight the measurement. */
    document.documentElement.classList.add(JS_FLAG);

    // The inline snippet in the partial applies a pre-existing dismissal
    // before first paint; this covers the case where it could not run.
    if (readDismissed(storageKey(tab))) {
      tab.classList.add(DISMISS_CLASS);
    }

    setUpDismissal(tab);
    setUpLift(tab);
    setUpHeroBoundary(tab);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();