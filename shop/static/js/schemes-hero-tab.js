/* ═══════════════════════════════════════════════════════════════════════
   Shop-Seed Art — "Schemes for Artisans" hero tab
   -----------------------------------------------------------------------
   Two jobs, both frontend-only:
     1. Dismiss  — × hides the tab for the rest of the session
                   (sessionStorage) without navigating anywhere.
     2. Boundary — the tab is already scoped to the hero by CSS; this only
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

  function init() {
    var tab = document.querySelector('[data-schemes-tab]');
    if (!tab) return;

    // The inline snippet in the partial applies a pre-existing dismissal
    // before first paint; this covers the case where it could not run.
    if (readDismissed(storageKey(tab))) {
      tab.classList.add(DISMISS_CLASS);
    }

    setUpDismissal(tab);
    setUpHeroBoundary(tab);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();