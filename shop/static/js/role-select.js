/* ==========================================================================
   Role selection — scroll choreography
   Arms the hidden start states, plays the reveal once the section is on
   screen, and drifts the background wash as the section passes.

   Everything here is additive. If this file never runs, the section renders in
   its final state; if the visitor prefers reduced motion, the section is
   armed and released in the same frame so it appears already settled rather
   than sitting invisible through the staged delays.
   ========================================================================== */
(function () {
  'use strict';

  var section = document.querySelector('.roles-aq');
  if (!section) return;

  var reduceMotion = window.matchMedia
    ? window.matchMedia('(prefers-reduced-motion: reduce)')
    : null;

  var armed = false;
  var played = false;

  function arm() {
    if (armed) return;
    armed = true;
    if (reduceMotion && reduceMotion.matches) {
      section.classList.add('roles-aq-motion-off');
    }
    section.classList.add('is-armed');
  }

  function play() {
    if (played) return;
    played = true;
    arm();
    section.classList.add('is-inview');
  }

  arm();

  // Nothing to choreograph: settle immediately.
  if (reduceMotion && reduceMotion.matches) {
    play();
    return;
  }

  if (!('IntersectionObserver' in window)) {
    play();
    return;
  }

  // rootMargin pulls the trigger up a little so the sequence has begun before
  // the section reaches the middle of the screen, rather than starting when it
  // is already fully in view.
  var observer = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        play();
        observer.disconnect();
      });
    },
    { threshold: 0.2, rootMargin: '0px 0px -12% 0px' }
  );
  observer.observe(section);

  // ── Background wash drift ──
  // One rAF-throttled listener writing a single custom property, so the
  // parallax costs a style recalculation rather than layout.

  var ticking = false;

  function updateWash() {
    ticking = false;
    var rect = section.getBoundingClientRect();
    var vh = window.innerHeight || document.documentElement.clientHeight || 0;
    if (!vh) return;

    // 0 while the section is centred, negative as it leaves upward.
    var progress = (vh / 2 - (rect.top + rect.height / 2)) / vh;
    var shift = Math.max(-1, Math.min(1, progress)) * 40;
    section.style.setProperty('--roles-shift', shift.toFixed(2) + 'px');
  }

  function onScroll() {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(updateWash);
  }

  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll, { passive: true });
  updateWash();
})();
