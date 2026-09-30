/* ═══════════════════════════════════════════════════════════════════════
   AI PRODUCT STUDIO — wizard behaviour
   -----------------------------------------------------------------------
   Every button in the studio is wired to something that really happens:

     image      POST /ai/image/enhance/          Pillow/NumPy pipeline
     choice     POST /ai/image/select/           records the seller's pick
     voice      POST /ai/voice/transcribe/       local Whisper on our server
     copy       POST /ai/text/product/catalog/   one call: title, body, terms
     publish    POST /ai/publish/                a real, unpublished Product

   The photo is normalised in the browser first (see normalize()) so that
   whatever the phone hands over is decodable and upright by the time it is
   uploaded. Every AI action is single-flighted through withBusy(), because
   a double click on a billed endpoint is a real cost.

   The panel index and the stepper index are the same number: six panels,
   six pills, no mapping table.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var root = document.getElementById('ais');
  if (!root) return;

  var $ = function (sel, ctx) { return (ctx || root).querySelector(sel); };
  var $$ = function (sel, ctx) {
    return Array.prototype.slice.call((ctx || root).querySelectorAll(sel));
  };

  /* A seller should never be told which formats are acceptable — they don't
     know, and the phone in their hand decides. Every image is accepted and
     then re-encoded (see normalize()) to something the browser can show.
     MAX_EDGE keeps a 100 MP phone photo from exhausting memory on a canvas;
     the byte ceiling is a crash guard, not a quality rule, since re-encoding
     brings virtually anything back under it. */
  var MAX_EDGE = 2000;
  var MAX_BYTES = 25 * 1024 * 1024;

  /* Price is a suggestion, not a quote: there is no market data behind it, so
     it is derived from the category the seller picked and the copy says so.
     The slider is always rebuilt around the current value, which is what
     makes the thumb, the fill bar, the label and the manual input agree. */
  var PRICE_FLOOR_RATIO = 0.4;
  var PRICE_CEIL_RATIO = 2.5;
  var PRICE_DEFAULT = 1499;

  var state = {
    step: 1,
    maxStep: 1,

    imageUrl: null,
    imageBlob: null,
    hasImage: false,
    shown: true,          // false once we know the browser cannot paint it
    enhanced: false,
    enhanceJob: null,
    enhancedUrl: null,
    originalUrl: null,
    enhanceBackground: 'white',
    enhancing: false,

    transcript: '',
    hasDescription: false,
    // Which of the on-screen dictation steps the seller has completed, so the
    // panel can say what to do next instead of only reacting to the mic.
    guideDone: { start: false, stop: false, generate: false },
    // The shop's own category tree, read from the page. Placement pickers and
    // the publish check both come from the database, never from this list.
    taxonomy: [],

    price: PRICE_DEFAULT,
    recommended: PRICE_DEFAULT,
    priceChosen: false,
    stock: 1,

    lang: 'en',           // the language the listing is written in
    sttLanguage: 'hi',    // the language the seller is speaking in

    keywords: [],

    recognising: false,
    processing: false,
    publishing: false,
    speechRecognition: null,
    mediaRecorder: null,
    micStream: null,
    recordChunks: [],
    recordStartedAt: 0,
    timerId: null,
    // Set once the server has told us it cannot transcribe, so we stop
    // re-trying on every recording and just use the browser instead.
    speechFallback: false,

    tearingDown: false
  };

  var el = {
    panels: $$('.ais-step-panel'),
    steppers: $$('[data-goto]'),
    stepper: $('.ais-stepper'),
    progress: $('.ais-progress'),
    progressFill: $('#aisProgressFill'),
    progressText: $('#aisProgressText'),
    workspace: $('#aisWorkspace'),
    prev: $('#aisPrev'),
    next: $('#aisNext'),
    nav: $('.ais-nav'),
    done: $('#aisDone'),

    error: $('#aisGlobalError'),
    csrf: $('#aisCsrf'),

    file: $('#aisFile'),
    drop: $('#aisDrop'),
    picked: $('#aisPicked'),
    pickedImg: $('#aisPickedImg'),
    pickedStandin: $('#aisPickedStandin'),
    preview: $('#aisPreview'),
    mediaEmpty: $('#aisMediaEmpty'),
    previewStandin: $('#aisPreviewStandin'),
    mediaMeta: $('#aisMediaMeta'),
    mediaMetaText: $('#aisMediaMetaText'),
    mediaActions: $('#aisMediaActions'),
    enhanceState: $('#aisEnhanceState'),
    beforeImg: $('#aisBeforeImg'),
    afterImg: $('#aisAfterImg'),
    afterWrap: $('#aisAfterWrap'),
    enhanceBody: $('#aisEnhanceBody'),
    enhanceBlank: $('#aisEnhanceBlank'),
    enhanceBusy: $('#aisEnhanceBusy'),

    mic: $('#aisMic'),
    micLabel: $('#aisMicLabel'),
    micStatus: $('#aisMicStatus'),
    guide: $('#aisGuide'),
    recordBtn: $('#aisRecordBtn'),
    timer: $('#aisTimer'),
    transcript: $('#aisTranscript'),
    transcriptText: $('#aisTranscriptText'),
    desc: $('#aisDesc'),
    sttLang: $('#aisLang'),
    taxonomy: $('#aisTaxonomyJson'),

    title: $('#aisTitle'),
    titleCount: $('#aisTitleCount'),
    catalogDesc: $('#aisCatalogDesc'),
    category: $('#aisCategory'),
    subcategory: $('#aisSubcategory'),
    keywordsList: $('#aisKeywordsList'),

    priceRange: $('#aisPriceRange'),
    priceBasis: $('#aisPriceBasis'),
    rangeFill: $('#aisRangeFill'),
    rangeMin: $('#aisRangeMin'),
    rangeMax: $('#aisRangeMax'),
    rangeNow: $('#aisRangeNow'),
    priceLabel: $('#aisPriceLabel'),
    priceValue: $('#aisPriceValue'),
    priceEdit: $('#aisPriceEdit'),
    priceInput: $('#aisPriceInput'),
    editPriceBtn: $('#aisEditPriceBtn'),
    usePriceBtn: $('#aisUsePriceBtn'),
    usePriceValue: $('#aisUsePriceValue'),

    cardImg: $('#aisCardImg'),
    cardEmpty: $('#aisCardEmpty'),
    cardStandin: $('#aisCardStandin'),
    cardTitle: $('#aisCardTitle'),
    cardPrice: $('#aisCardPrice'),
    cardDesc: $('#aisCardDesc'),
    cardTags: $('#aisCardTags'),
    publishBtn: $('#aisPublishBtn'),
    done: $('#aisDone'),
    doneLink: $('#aisDoneLink')
  };

  /* Read an optional input's value without throwing when it is not rendered. */
  function val(node) {
    return node && typeof node.value === 'string' ? node.value.trim() : '';
  }

  function rupees(n) {
    return '₹' + Number(n).toLocaleString('en-IN');
  }

  var reduced = window.matchMedia
    ? window.matchMedia('(prefers-reduced-motion: reduce)')
    : { matches: false };

  /* ─── Messages ─────────────────────────────────────────────────────
     One alert, above the stepper, so a failure on step 4 is as visible as a
     failure on step 1. The previous version wrote into a node inside the
     first panel, which meant every error after the photo was silent. */

  function showError(msg) {
    if (!msg) {
      el.error.hidden = true;
      el.error.textContent = '';
      return;
    }
    el.error.textContent = msg;
    el.error.hidden = false;
  }

  function clearError() {
    showError('');
  }

  /* ─── API ──────────────────────────────────────────────────────────── */

  var apiBase = '/ai/';

  function hasFetch() {
    return typeof fetch === 'function';
  }

  function getCookie(name) {
    var match = document.cookie.match(
      new RegExp('(^|;\\s*)' + name + '=([^;]*)')
    );
    return match ? decodeURIComponent(match[2]) : '';
  }

  /* The hidden {% csrf_token %} input is the source of truth: it is rendered
     into this page, so it is always present even when the csrftoken cookie is
     not (HttpOnly, a cookie-less first hit, a proxy that strips it). */
  function csrfToken() {
    return (el.csrf && el.csrf.value) || getCookie('csrftoken') || '';
  }

  /* A Django view answers a missing or wrong token with a 403 HTML page, so
     the JSON parse fails and there is no error message to show. Saying so is
     far more useful than a generic failure. */
  function reportFailure(response, data, fallback) {
    if (response.status === 403) {
      return {
        ok: false,
        code: 'csrf',
        error: 'Your session expired. Please refresh the page and try again.'
      };
    }
    var body = data && data.error;
    return {
      ok: false,
      code: body && body.code,
      error: (body && body.message) || fallback
    };
  }

  async function apiPost(endpoint, payload) {
    if (!hasFetch()) {
      return { ok: false, code: 'no_fetch', error: 'This browser cannot make network requests.' };
    }
    var response;
    try {
      response = await fetch(apiBase + endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'X-CSRFToken': csrfToken(),
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify(payload),
        credentials: 'same-origin'
      });
    } catch (err) {
      return { ok: false, code: 'network', error: 'Could not reach the server. Please check your connection.' };
    }
    var data = {};
    try {
      data = await response.json();
    } catch (err) {
      /* Fall through: reportFailure turns a non-JSON body into a message. */
    }
    if (!response.ok) return reportFailure(response, data, 'Something went wrong. Please try again.');
    return { ok: true, data: data };
  }

  async function apiUpload(endpoint, formData) {
    if (!hasFetch()) {
      return { ok: false, code: 'no_fetch', error: 'This browser cannot make network requests.' };
    }
    var response;
    try {
      response = await fetch(apiBase + endpoint, {
        method: 'POST',
        /* No Content-Type: the browser has to set the multipart boundary. */
        headers: {
          'Accept': 'application/json',
          'X-CSRFToken': csrfToken(),
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: formData,
        credentials: 'same-origin'
      });
    } catch (err) {
      return { ok: false, code: 'network', error: 'Could not reach the server. Please check your connection.' };
    }
    var data = {};
    try {
      data = await response.json();
    } catch (err) {
      /* As above. */
    }
    if (!response.ok) return reportFailure(response, data, 'Something went wrong. Please try again.');
    return { ok: true, data: data };
  }

  /* Run an async action with a spinner on the button that was actually
     clicked, and refuse a second click while it runs. The delegated click
     handler below passes the trigger element, so this guard is what stops a
     double click from billing two completions. */
  function withBusy(btn, work) {
    if (btn && btn.disabled) return Promise.resolve();
    var label = btn ? btn.innerHTML : '';
    if (btn) {
      btn.disabled = true;
      btn.setAttribute('aria-busy', 'true');
      btn.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> Working…';
    }
    var restore = function () {
      if (!btn) return;
      btn.disabled = false;
      btn.removeAttribute('aria-busy');
      btn.innerHTML = label;
    };
    return Promise.resolve()
      .then(work)
      .then(
        function (value) { restore(); return value; },
        function (err) { restore(); throw err; }
      );
  }

  /* ─── Image ───────────────────────────────────────────────────── */

  function isUsableImage(file) {
    /* Empty type = the OS didn't report one; attempt it and let the decode
       step below be the real judge. */
    return !file.type || file.type.indexOf('image/') === 0;
  }

  /* ─── Normalising the photo ──────────────────────────────────────
     Sellers do not know or care what a "format" is, and phones hand us
     HEIC, EXIF-rotated shots and 12 MP files. So the file is never judged,
     it is repaired: decode whatever arrived, apply the camera's rotation,
     cap the long edge, and re-encode to a format every browser can show.
     That also gives the preview a guaranteed-decodable URL. */

  function loadViaImg(file) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () { resolve({ img: img, revoke: url }); };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error('decode')); };
      img.src = url;
    });
  }

  function loadBitmap(file) {
    if (window.createImageBitmap) {
      /* imageOrientation fixes photos that would otherwise appear sideways. */
      return createImageBitmap(file, { imageOrientation: 'from-image' })
        .catch(function () { return loadViaImg(file); });
    }
    return loadViaImg(file);
  }

  function canvasToBlob(canvas, type, quality) {
    return new Promise(function (resolve) {
      if (canvas.toBlob) canvas.toBlob(resolve, type, quality);
      else resolve(null);
    });
  }

  /* Returns {blob, url, name} for bytes the browser can definitely paint, or
     rejects if the pixels cannot be read at all. */
  function normalize(file) {
    return loadBitmap(file).then(function (source) {
      var img = source.img || source;
      var w = img.naturalWidth || img.width;
      var h = img.naturalHeight || img.height;
      if (!w || !h) throw new Error('empty');

      var scale = Math.min(1, MAX_EDGE / Math.max(w, h));
      var canvas = document.createElement('canvas');
      canvas.width = Math.round(w * scale);
      canvas.height = Math.round(h * scale);

      var ctx = canvas.getContext('2d');
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

      /* Keep transparency for PNG sources, otherwise JPEG is far smaller. */
      var isPng = /png/i.test(file.type);
      var type = isPng ? 'image/png' : 'image/jpeg';
      return canvasToBlob(canvas, type, 0.9).then(function (blob) {
        if (source.revoke) URL.revokeObjectURL(source.revoke);
        if (blob) {
          return {
            blob: blob,
            url: URL.createObjectURL(blob),
            /* The name has to match the bytes: the server sniffs content, but
               a .jpg name on PNG bytes is the kind of thing that only shows
               up as a support ticket. */
            name: isPng ? 'product.png' : 'product.jpg'
          };
        }
        /* No canvas encoding: fall back to the original bytes. */
        return {
          blob: file,
          url: URL.createObjectURL(file),
          name: file.name || 'product.jpg'
        };
      });
    });
  }

  /* One place decides how the photo appears everywhere.
     has  = the seller chose a photo at all
     show = the browser can actually paint it
     "not yet" placeholders belong to `has`; the quiet "Photo added" tiles
     belong to `has && !show`. Never show both, and never a broken image. */
  function renderPhoto() {
    var has = state.hasImage;
    var show = has && state.shown;
    var none = !has;
    var standin = has && !show;

    el.pickedImg.hidden = !show;
    el.pickedStandin.hidden = !standin;
    el.preview.hidden = !show;
    el.previewStandin.hidden = !standin;
    el.mediaEmpty.hidden = !none;
    el.cardImg.hidden = !show;
    el.cardEmpty.hidden = !none;
    el.cardStandin.hidden = !standin;
    /* With no paintable photo there is nothing to compare, so the compare
       step explains itself instead of showing two blank frames. */
    if (!state.enhancing) {
      el.enhanceBody.hidden = !show;
      el.enhanceBlank.hidden = !standin;
    }
  }

  function previewFailed() {
    /* All five preview surfaces fire onerror for the same file; report once. */
    if (!state.shown) return;
    state.shown = false;
    renderPhoto();
    showError(
      'We can\u2019t show this photo in your browser, but you can carry on. ' +
      'It will be prepared for your listing when you publish.'
    );
  }

  /* Every visible surface shows the same photo. Keeping this in one function
     is what stops the rail and the preview card disagreeing. */
  function paintPhoto(url) {
    el.pickedImg.src = url;
    el.preview.src = url;
    el.beforeImg.src = url;
    el.cardImg.src = url;
  }

  function useImage(file) {
    if (!file) return;

    if (!isUsableImage(file)) {
      showError('That doesn\u2019t look like a photo. Please choose a photo of your product.');
      el.file.value = '';
      return;
    }
    if (file.size > MAX_BYTES) {
      showError('That photo is too large to open here. Please choose a smaller one.');
      el.file.value = '';
      return;
    }

    clearError();
    if (state.imageUrl) URL.revokeObjectURL(state.imageUrl);
    state.imageUrl = null;
    state.imageBlob = null;
    state.imageName = 'product.jpg';
    state.hasImage = true;
    state.shown = true;
    /* A new photo invalidates the old enhancement: its job id points at
       artefacts of a picture the seller just replaced. */
    state.enhanced = false;
    state.enhanceJob = null;
    state.enhancedUrl = null;
    state.originalUrl = null;

    el.drop.hidden = true;
    el.picked.hidden = false;
    el.mediaMeta.hidden = false;
    el.mediaActions.hidden = false;

    setEnhanced(false);
    resetEnhanceStep();
    syncChecklist();
    renderNav();

    normalize(file).then(function (result) {
      /* The seller may have replaced or removed the photo meanwhile. */
      if (!state.hasImage) {
        URL.revokeObjectURL(result.url);
        return;
      }
      state.imageBlob = result.blob;
      state.imageName = result.name;
      state.imageUrl = result.url;
      paintPhoto(result.url);
      renderPhoto();
      el.file.value = '';
    }).catch(function () {
      if (!state.hasImage) return;
      /* Could not read the pixels: keep the original URL as a last chance
         (some browsers render formats createImageBitmap is fussy about). */
      state.imageBlob = file;
      state.imageName = file.name || 'product.jpg';
      state.imageUrl = URL.createObjectURL(file);
      paintPhoto(state.imageUrl);
      renderPhoto();
      el.file.value = '';
    });
  }

  function clearImage() {
    /* Tearing down the src can itself raise an error event, so mute the
       decode guard while we strip the previews. */
    state.tearingDown = true;
    if (state.imageUrl) {
      URL.revokeObjectURL(state.imageUrl);
      state.imageUrl = null;
    }
    state.imageBlob = null;
    state.hasImage = false;
    state.shown = true;
    state.enhanced = false;
    state.enhanceJob = null;
    state.enhancedUrl = null;
    state.originalUrl = null;

    el.pickedImg.removeAttribute('src');
    el.preview.removeAttribute('src');
    el.beforeImg.removeAttribute('src');
    el.afterImg.removeAttribute('src');
    el.cardImg.removeAttribute('src');
    /* Let the seller re-pick the same file after a rejected attempt. */
    el.file.value = '';
    state.tearingDown = false;

    el.picked.hidden = true;
    el.drop.hidden = false;
    el.mediaMeta.hidden = true;
    el.mediaActions.hidden = true;

    resetEnhanceStep();
    renderPhoto();
    setEnhanced(false);
    syncChecklist();
    renderNav();

    /* A wizard whose first step is now empty should not still offer a jump
       to a step six. */
    if (state.step > 1) goTo(1, true);
  }

  function setEnhanced(on) {
    state.enhanced = on;
    el.enhanceState.hidden = !on;
    el.mediaMetaText.textContent = on ? 'Image ready' : 'Image uploaded';
  }

  /* ─── Steps ───────────────────────────────────────────────────── */

  function stepNames() {
    return el.steppers.map(function (s) {
      var name = $('.ais-step-name', s);
      return name ? name.textContent.trim() : '';
    });
  }

  function goTo(next, viaBack) {
    next = Math.min(Math.max(next, 1), el.panels.length);
    if (next === state.step) return;

    var from = el.panels[state.step - 1];
    var target = el.panels[next - 1];

    from.classList.remove('is-active', 'is-entering', 'is-entering-back');
    from.hidden = true;

    target.hidden = false;
    target.classList.remove('is-entering', 'is-entering-back');
    /* Restart the entrance animation on every visit. */
    void target.offsetWidth;
    target.classList.add('is-active');
    if (!reduced.matches) {
      target.classList.add(viaBack ? 'is-entering-back' : 'is-entering');
    }

    state.step = next;
    if (next > state.maxStep) state.maxStep = next;

    renderStepper();
    renderNav();
    target.focus({ preventScroll: true });
    root.scrollIntoView({
      behavior: reduced.matches ? 'auto' : 'smooth',
      block: 'start'
    });
  }

  function renderStepper() {
    var n = state.step;
    var pct = (n / el.steppers.length) * 100;

    el.steppers.forEach(function (s, i) {
      var index = i + 1;
      var visited = index <= state.maxStep;
      s.classList.toggle('is-active', index === n);
      /* "Done" means reached, not left-behind: walking back to step 1 to
         re-read something must not erase the marks on steps 2 to 6, which
         is exactly when the seller is checking how far they got. */
      s.classList.toggle('is-done', visited);
      /* Only steps already reached are jump targets. */
      s.disabled = !visited;
      if (index === n) s.setAttribute('aria-current', 'step');
      else s.removeAttribute('aria-current');
    });

    el.progressFill.style.width = pct + '%';
    el.progressText.textContent =
      'Step ' + n + ' of ' + el.steppers.length + ' · ' + stepNames()[n - 1];
  }

  /* A step is only leaveable once it holds what it is for, so "Next" can
     never walk the seller into an empty panel they then have to notice. The
     preview step is excluded: publishing is its own action, and the shared
     nav bar is hidden there. */
  function canLeave(step) {
    switch (step) {
      case 1: return state.hasImage;
      /* The price step has a price from the first render, so requiring one
         would be theatre; what it actually needs is a decision. */
      case 4: return !!val(el.title);
      case 5: return state.priceChosen;
      default: return true;
    }
  }

  function blockReason(step) {
    switch (step) {
      case 1: return 'Add a product photo to continue.';
      case 4: return 'The listing needs a title before you can continue.';
      case 5: return 'Confirm your price to continue.';
      default: return '';
    }
  }

  function renderNav() {
    var last = state.step === el.panels.length;
    el.prev.disabled = state.step === 1;
    el.next.disabled = last || !canLeave(state.step);
    /* On the preview step the panel's own buttons are the actions, so the
       shared bar would be a second, redundant way to move on. */
    el.nav.classList.toggle('is-hidden', last);
  }

  function syncChecklist() {
    setCheck('image', state.hasImage);
    setCheck('description', state.hasDescription);
    setCheck('price', state.priceChosen);
  }

  function setCheck(key, on) {
    var node = $('[data-check="' + key + '"]');
    if (node) node.classList.toggle('is-ready', !!on);
  }

  /* ─── Voice — speech to text ───────────────────────────────────────
     The server runs a local Whisper model, so dictation is free, works in
     every browser, needs no API key and has no rate limit. The recording is
     posted when the seller stops, so there are no interim words on screen
     while recording.

     If the server has no model (a small deployment that did not install it),
     the first attempt comes back with 'speech_unavailable' and we fall back
     to the browser's own SpeechRecognition for the rest of the session. */

  function renderRecordBtn() {
    var icon, label;
    if (state.processing) {
      icon = 'fa-spinner fa-spin';
      label = 'Transcribing…';
    } else if (state.recognising) {
      icon = 'fa-stop';
      label = 'Stop Recording';
    } else {
      icon = 'fa-microphone';
      label = 'Start Recording';
    }
    el.recordBtn.innerHTML =
      '<i class="fas ' + icon + '" aria-hidden="true"></i> ' + label;
    el.recordBtn.disabled = !!state.processing;
    el.mic.disabled = !!state.processing;
  }

  /* ── Dictation guidance ───────────────────────────────────────────────
     Record-to-text is easy to get wrong from the seller's side: tap once and
     nothing seems to happen, tap twice quickly and two recordings overlap, and
     a failed transcription used to look like the studio was simply ignoring
     them. So every phase says which move is next, the visible checklist ticks
     itself off, and a failure says what to do rather than just what went
     wrong. */

  var GUIDE_IDLE = 'Nothing is recorded until you tap the mic.';
  var GUIDE_RECORDING =
    'Recording — speak about the product, then tap the mic again to stop.';
  var GUIDE_WORKING =
    'Writing your words down. Stay on this step, it only takes a moment.';
  var GUIDE_DONE =
    'That is your description. Now press “Generate with AI” below to write the listing.';

  function setMicStatus(text) {
    if (el.micStatus) el.micStatus.textContent = text;
  }

  function renderGuide() {
    if (!el.guide) return;
    /* Only the two things a seller *does* are ticked: starting a recording
       and pressing Generate. "Speak" and "tap again to stop" are not
       achievements, they are part of the same tap, so highlighting one of
       them as outstanding would send the seller looking for a button that
       does not exist. What is highlighted is simply the next move. */
    var recorded = state.guideDone.stop;
    var next = null;
    if (state.recognising) {
      next = 'stop';
    } else if (state.guideDone.generate) {
      next = null;
    } else if (recorded || state.hasDescription) {
      next = 'generate';
    } else {
      next = 'start';
    }
    var done = {
      start: state.guideDone.start,
      speak: false,
      stop: recorded,
      generate: state.guideDone.generate,
    };
    var steps = el.guide.querySelectorAll('.ais-guide-step');
    for (var i = 0; i < steps.length; i++) {
      var key = steps[i].getAttribute('data-guide');
      var isDone = !!done[key];
      var isNext = key === next;
      steps[i].classList.toggle('is-done', isDone);
      steps[i].classList.toggle('is-next', isNext);
      var icon = steps[i].querySelector('i');
      if (icon) {
        icon.className = isDone ? 'fas fa-check-circle' :
          (isNext ? 'fas fa-circle-dot' : 'fas fa-circle');
      }
    }
  }

  function resetGuide() {
    state.guideDone = { start: false, stop: false, generate: false };
    renderGuide();
    setMicStatus(GUIDE_IDLE);
  }

  function markRecordingStarted() {
    state.recognising = true;
    state.guideDone.start = true;
    el.mic.classList.add('is-live');
    el.micLabel.textContent = 'Listening…';
    setMicStatus(GUIDE_RECORDING);
    renderGuide();
    startTimer();
    renderRecordBtn();
  }

  function startTimer() {
    state.recordStartedAt = Date.now();
    el.timer.hidden = false;
    stopTimer();
    state.timerId = setInterval(function () {
      var seconds = Math.floor((Date.now() - state.recordStartedAt) / 1000);
      el.timer.textContent = padTime(seconds);
    }, 500);
  }

  function stopTimer() {
    if (state.timerId) {
      clearInterval(state.timerId);
      state.timerId = null;
    }
  }

  function padTime(total) {
    var minutes = Math.floor(total / 60);
    var seconds = total % 60;
    return (minutes < 10 ? '0' : '') + minutes + ':' +
           (seconds < 10 ? '0' : '') + seconds;
  }

  function releaseStream(stream) {
    if (!stream) return;
    stream.getTracks().forEach(function (track) { track.stop(); });
  }

  function resetRecordingUi() {
    state.recognising = false;
    state.processing = false;
    stopTimer();
    el.timer.hidden = true;
    el.mic.classList.remove('is-live');
    el.micLabel.textContent = 'Tap to record';
    /* The status line keeps whatever it last said: if a take just failed,
       the reason is still the most useful thing on screen. */
    if (!el.micStatus || !el.micStatus.dataset.sticky) setMicStatus(GUIDE_IDLE);
    renderGuide();
    renderRecordBtn();
  }

  /* Stopping must not kill the tracks before the recorder has flushed its
     final chunk, so the stream is released from onstop, not from here. */
  function stopRecording() {
    if (state.mediaRecorder && state.recognising) {
      try {
        state.mediaRecorder.stop();
      } catch (err) {
        /* Already stopped; releasing the tracks is all that is left. */
        releaseStream(state.micStream);
        state.micStream = null;
        resetRecordingUi();
      }
      return;
    }
    if (state.speechRecognition && state.recognising) {
      try {
        state.speechRecognition.stop();
      } catch (err) {
        /* Ignore: onend will still reset the UI. */
      }
      state.recognising = false;
    }
    releaseStream(state.micStream);
    state.micStream = null;
    resetRecordingUi();
  }

  async function transcribeAudio() {
    if (state.processing) return;
    if (state.recognising) {
      stopRecording();
      return;
    }
    clearError();

    if (canRecordLocally()) {
      await startLocalRecording();
    } else {
      startBrowserRecognition();
    }
  }

  function canRecordLocally() {
    if (state.speechFallback) return false;
    if (!hasFetch()) return false;
    return !!(navigator.mediaDevices &&
              navigator.mediaDevices.getUserMedia &&
              window.MediaRecorder);
  }

  async function startLocalRecording() {
    var stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      /* A denied or missing microphone is not a server problem, and the
         browser recogniser needs the same permission, so report it directly. */
      showError(err && err.name === 'NotAllowedError'
        ? 'Microphone permission denied.'
        : 'Microphone not accessible.');
      return;
    }

    var recorder;
    try {
      recorder = pickRecorder(stream);
    } catch (err) {
      releaseStream(stream);
      startBrowserRecognition();
      return;
    }

    state.micStream = stream;
    state.mediaRecorder = recorder;
    state.recordChunks = [];

    recorder.ondataavailable = function (event) {
      if (event.data && event.data.size) state.recordChunks.push(event.data);
    };
    recorder.onstop = function () {
      var chunks = state.recordChunks;
      state.recordChunks = [];
      state.mediaRecorder = null;
      /* Released only now, so the last chunk is not cut off. */
      releaseStream(state.micStream);
      state.micStream = null;
      state.recognising = false;
      stopTimer();
      el.mic.classList.remove('is-live');
      var blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
      sendRecording(blob);
    };
    recorder.onerror = function () {
      state.mediaRecorder = null;
      releaseStream(state.micStream);
      state.micStream = null;
      resetRecordingUi();
      showError('Recording stopped unexpectedly. Please try again.');
    };

    try {
      recorder.start();
    } catch (err) {
      state.mediaRecorder = null;
      releaseStream(stream);
      state.micStream = null;
      showError('Could not start recording on this browser.');
      return;
    }
    markRecordingStarted();
  }

  /* Chrome and Firefox disagree on which container they can record, and the
     server decodes all of these, so use the first the browser admits. */
  function pickRecorder(stream) {
    if (typeof MediaRecorder.isTypeSupported === 'function') {
      var types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'];
      for (var i = 0; i < types.length; i++) {
        if (MediaRecorder.isTypeSupported(types[i])) {
          return new MediaRecorder(stream, { mimeType: types[i] });
        }
      }
    }
    return new MediaRecorder(stream);
  }

  async function sendRecording(blob) {
    if (!blob || !blob.size) {
      showError('Nothing was recorded. Please try again.');
      resetRecordingUi();
      return;
    }

    state.processing = true;
    el.micLabel.textContent = 'Transcribing\u2026';
    setMicStatus(GUIDE_WORKING);
    renderRecordBtn();

    var form = new FormData();
    form.append('audio', blob, 'clip.webm');
    form.append('language', state.sttLanguage || 'hi');

    var result = await apiUpload('voice/transcribe/', form);

    state.processing = false;
    el.micLabel.textContent = 'Tap to record';
    renderRecordBtn();

    if (result.ok) {
      var said = (result.data.text || '').trim();
      if (said) {
        state.guideDone.stop = true;
        appendTranscript(said);
      } else {
        /* A 200 with no words in it is still nothing to write a listing
           from, so it takes the same path as a failed take. */
        speechFailed('empty',
          'We could not hear any words in that recording. Hold the phone closer, speak a little louder, and tap record again.');
      }
      return;
    }
    /* 503 speech_unavailable is the server saying it has no model. The
       browser becomes the engine and the seller records again. */
    if (result.code === 'speech_unavailable' || result.code === 'speech_busy') {
      state.speechFallback = true;
      state.guideDone.stop = true;
      speechFailed(result.code,
        'Voice typing is unavailable on our server right now, so your browser will do it instead. Tap record once more.');
      startBrowserRecognition();
      return;
    }
    speechFailed(result.code, speechAdvice(result.code));
  }

  /* What to actually do about a failed take. The server already sends a
     readable message; these add the next move, which is the part that was
     missing when a failed recording read only as "Voice typing failed". */
  /* Keys must match the codes in ai_services.services.speech_to_text exactly:
     a typo here silently falls through to the generic sentence below, which
     is the one thing this table exists to avoid. */
  var SPEECH_ADVICE = {
    no_speech: 'We could not hear any words. Tap record again and speak as soon as it turns red.',
    too_short: 'That was too short to understand. Keep recording until you have said a whole sentence.',
    unreadable_audio: 'We could not read that recording. Use the Type tab and write it instead.',
    audio_too_large: 'That recording was too long. Keep it to about a minute.',
    missing_audio: 'Nothing was sent. Tap record again and speak once it turns red.',
    transcription_failed: 'We could not write that down. Please try once more.',
    microphone_busy: 'Your microphone is in use by another app. Close it and try again.',
    rate_limited: 'Too many recordings in a row. Wait a minute and tap record again.',
  };

  function speechAdvice(code) {
    if (SPEECH_ADVICE[code]) return SPEECH_ADVICE[code];
    return 'Voice typing did not work. Tap record again, or use the Type tab and write it instead.';
  }

  function speechFailed(code, message) {
    /* A take that produced no words is not progress, so the guide rolls back
       to "start" and the status line keeps the reason until the next tap. */
    state.guideDone.stop = false;
    renderGuide();
    if (el.micStatus) {
      el.micStatus.dataset.sticky = '1';
      el.micStatus.textContent = message;
    }
    showError(message);
  }

  function appendTranscript(text) {
    if (!text) return;
    state.transcript = (state.transcript + ' ' + text).trim();
    el.transcriptText.textContent = state.transcript;
    el.transcript.hidden = false;
    if (el.micStatus) {
      delete el.micStatus.dataset.sticky;
      setMicStatus(GUIDE_DONE);
    }
    state.guideDone.start = true;
    state.guideDone.stop = true;
    renderGuide();
    /* A finished description is the cue to leave this step, so the way on is
       named rather than left for the seller to spot. */
    var generate = document.querySelector('[data-studio-hook="generate"]');
    if (generate && !generate.dataset.hinted) {
      generate.dataset.hinted = '1';
      generate.classList.add('ais-btn-nudge');
    }
    markDescriptionReady();
  }

  function markDescriptionReady() {
    state.hasDescription = true;
    syncChecklist();
  }

  /* Fallback path: the browser's own recogniser, used only when the server
     has no speech model. It streams words, so the seller sees live text. */
  function startBrowserRecognition() {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      showError('Voice typing is not supported in this browser. Use the Type tab instead.');
      return;
    }
    var Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    var recognition = new Recognition();
    state.speechRecognition = recognition;
    recognition.lang = state.sttLanguage === 'en' ? 'en-IN' : 'hi-IN';
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onstart = function () {
      if (state.speechFallback) {
        el.micLabel.textContent = 'Listening\u2026';
        startTimer();
        renderRecordBtn();
      }
      markRecordingStarted();
    };

    recognition.onresult = function (event) {
      var interim = '';
      var final = '';
      for (var i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) {
          final += event.results[i][0].transcript;
        } else {
          interim += event.results[i][0].transcript;
        }
      }
      if (final) {
        appendTranscript(final);
      } else if (interim) {
        el.transcriptText.textContent = (state.transcript + ' ' + interim).trim();
        el.transcript.hidden = false;
      }
    };

    recognition.onerror = function (event) {
      /* Chrome reports its own codes here, and 'no-speech' in particular is
         the one a seller hits most often: it is what happens when the mic
         opens before they have said anything. Saying what to do is the whole
         difference between that and an apparently dead button. */
      if (event.error === 'no-speech') {
        speechFailed('no_speech', SPEECH_ADVICE.no_speech);
      } else if (event.error === 'audio-capture') {
        speechFailed('audio_capture', 'Your microphone is not available. Close any other app that may be using it, or use the Type tab.');
      } else if (event.error === 'not-allowed') {
        speechFailed('not_allowed', 'Microphone permission was denied. Allow it in your browser settings, or use the Type tab.');
      } else if (event.error !== 'aborted') {
        speechFailed(event.error,
          'Voice typing in this browser stopped working. Use the Type tab, or tap record to try again.');
      }
      state.recognising = false;
      resetRecordingUi();
    };

    recognition.onend = function () {
      state.speechRecognition = null;
      /* Chrome ends the session every so often; restart while still recording. */
      if (state.recognising) {
        try {
          recognition.start();
        } catch (err) {
          state.recognising = false;
          resetRecordingUi();
        }
      } else {
        resetRecordingUi();
      }
    };

    try {
      recognition.start();
    } catch (err) {
      state.speechRecognition = null;
      showError('Could not start voice typing on this browser.');
    }
  }

  /* ─── Image enhancement ────────────────────────────────────────────
     The pipeline is a real request: it decodes, straightens, levels, centres
     and re-encodes the photo on our server and returns both versions. So the
     compare step has to wait for it, and the seller has to be the one who
     picks which file the listing uses. */

  function resetEnhanceStep() {
    if (el.enhanceBusy) el.enhanceBusy.hidden = true;
    state.enhancing = false;
    /* The "after" frame must not keep showing a previous run's result. */
    el.afterImg.removeAttribute('src');
    el.afterImg.hidden = false;
  }

  function setEnhanceBusy(on) {
    state.enhancing = on;
    if (!el.enhanceBusy) return;
    el.enhanceBusy.hidden = !on;
    el.enhanceBody.classList.toggle('is-busy', on);
  }

  async function enhanceImage(btn) {
    if (state.enhancing) return;
    if (!state.hasImage) {
      showError('Add a product photo first, then enhance it.');
      return;
    }
    /* The photo is still being decoded and re-encoded. Sending now would
       upload a null blob, which the server rejects with a bare 400. */
    if (!state.imageBlob) {
      showError('Your photo is still loading. Try again in a moment.');
      return;
    }

    clearError();
    goTo(2);
    setEnhanceBusy(true);
    renderNav();

    var form = new FormData();
    form.append('image', state.imageBlob, state.imageName || 'product.jpg');
    form.append('background', state.enhanceBackground || 'white');
    /* The background preset is a presentation choice for the photo. The
       seller's department is a fact about the product and is sent when the
       listing is written, not here, where it would only bias the matting. */
    form.append('category', 'generic');

    var result = await apiUpload('image/enhance/', form);

    setEnhanceBusy(false);
    renderNav();

    if (!result.ok) {
      showError(result.error || 'We could not enhance that photo. You can keep the original and carry on.');
      /* Put the seller back on the step they can act on. */
      goTo(1, true);
      return;
    }

    var job = result.data.job;
    state.enhanceJob = job;
    state.originalUrl = job.original_url || null;
    state.enhancedUrl = job.enhanced_url || null;

    if (!state.enhancedUrl) {
      showError('The enhancement produced no new image, so your original will be used.');
      keepOriginal();
      return;
    }

    /* Wait for the enhanced file to actually decode before claiming it is
       ready: swapping in a URL the browser then fails on is the same blank
       frame this screen exists to avoid. */
    var probe = new Image();
    probe.onload = function () {
      el.afterImg.src = state.enhancedUrl;
      renderPhoto();
    };
    probe.onerror = function () {
      showError('The enhanced preview could not be loaded. Keeping your original photo.');
      keepOriginal();
    };
    probe.src = state.enhancedUrl;
  }

  /* Swapping the visible photo is the whole point of "Use Enhanced Image":
     without this the rail keeps showing the original next to a badge that
     claims the listing image was changed. */
  function applyEnhanced() {
    if (!state.enhancedUrl) {
      keepOriginal();
      return;
    }
    setEnhanced(true);
    el.pickedImg.src = state.enhancedUrl;
    el.preview.src = state.enhancedUrl;
    el.cardImg.src = state.enhancedUrl;
    recordSelection('enhanced');
    goTo(3);
  }

  function keepOriginal() {
    setEnhanced(false);
    if (state.imageUrl) {
      el.pickedImg.src = state.imageUrl;
      el.preview.src = state.imageUrl;
      el.cardImg.src = state.imageUrl;
    }
    recordSelection('original');
    goTo(3);
  }

  /* The server records the seller's pick so that publish cannot second-guess
     it. A failure here is not worth blocking on: publish also receives the
     choice, so the worst case is a stored draft preference that was not
     written down. */
  function recordSelection(choice) {
    if (!state.enhanceJob) return;
    var form = new FormData();
    form.append('job_id', state.enhanceJob.id);
    form.append('selection', choice);
    apiUpload('image/select/', form);
  }

  /* ─── Listing copy ──────────────────────────────────────────────────
     One request writes the title, the description and the search terms. The
     seller's own words are the seed: without them the model has a category
     and nothing to describe, and writes a listing for a product it has never
     seen. */

  function sellerNotes() {
    /* Both tabs can hold input: dictation and typing are not exclusive, and
       whichever has something in it is what the seller meant to say. */
    var typed = val(el.desc);
    var spoken = state.transcript.trim();
    if (typed && spoken) return typed + '\n' + spoken;
    return typed || spoken;
  }

  function productFacts() {
    var facts = {
      title: val(el.title),
      seller_notes: sellerNotes(),
      category: val(el.category),
      subcategory: val(el.subcategory),
      language: state.lang
    };
    /* A working title that is really the first line of the seller's notes
       would read as a fact the model then repeats back. */
    if (facts.title && facts.seller_notes.indexOf(facts.title) !== -1) {
      delete facts.title;
    }
    if (state.price) facts.price_range = rupees(state.price);
    return facts;
  }

  /* Three different situations, three different messages. "Nothing here yet"
     and "the model came back with nothing" are not the same thing, and
     showing the second before anything has been asked for is a lie. */
  function paintKeywords(words, generated) {
    if (!el.keywordsList) return;
    el.keywordsList.innerHTML = '';

    if (!words || !words.length) {
      var empty = document.createElement('li');
      empty.className = 'ais-kw-empty';
      empty.textContent = generated
        ? 'No keywords came back. You can still publish \u2014 they only help with search.'
        : 'Keywords will appear here once you generate the listing.';
      el.keywordsList.appendChild(empty);
      return;
    }
    words.forEach(function (word) {
      var chip = document.createElement('li');
      chip.className = 'ais-kw-item';
      chip.textContent = word;
      el.keywordsList.appendChild(chip);
    });
  }

  function paintCatalog() {
    var title = val(el.title);
    el.cardTitle.textContent = title || 'Untitled product';
    el.cardDesc.textContent = val(el.catalogDesc);

    /* Show only the keywords that actually appear in the listing text, so the
       card never advertises a term the copy does not support. */
    var haystack = (title + ' ' + val(el.catalogDesc)).toLowerCase();
    var tags = (state.keywords || []).filter(function (word) {
      return haystack.indexOf(String(word).toLowerCase()) !== -1;
    }).slice(0, 6);

    el.cardTags.innerHTML = '';
    tags.forEach(function (word) {
      var li = document.createElement('li');
      li.textContent = word;
      el.cardTags.appendChild(li);
    });
    el.cardTags.hidden = tags.length === 0;
  }

  function flash(node) {
    if (!node) return;
    node.classList.add('is-busy');
    setTimeout(function () { node.classList.remove('is-busy'); }, 600);
  }

  /* Fills the reviewable fields. Never overwrites something the seller
     already edited unless asked to. */
  function applyCatalog(data, overwrite) {
    var changed = false;

    if (data.title && (overwrite || !val(el.title))) {
      el.title.value = String(data.title).slice(0, 120);
      changed = true;
    }
    if (data.description && (overwrite || !val(el.catalogDesc))) {
      el.catalogDesc.value = String(data.description);
      changed = true;
    }
    if (Array.isArray(data.keywords) && data.keywords.length) {
      state.keywords = data.keywords;
      paintKeywords(state.keywords, true);
    } else if (overwrite) {
      /* An explicit regenerate that returns nothing should clear the old
         chips rather than leave stale ones on screen. */
      state.keywords = [];
      paintKeywords([], true);
    }

    if (changed) el.titleCount.textContent = el.title.value.length + ' / 120';
    /* The model also places the product. It is only ever asked to choose from
       the shop's real taxonomy, so a returned name is applied by matching it
       against that list rather than being trusted as free text. */
    if (data.category) selectCategory(data.category, overwrite);
    if (data.subcategory) selectSubcategory(data.subcategory, overwrite);
    if (val(el.catalogDesc)) markDescriptionReady();
    paintCatalog();
    return changed;
  }

  /* ─── Placement pickers ─────────────────────────────────────────────
     Both selects are filled from the taxonomy rendered into the page, which
     comes from the database. The subcategory list is rebuilt whenever the
     category changes so it can never offer a subcategory from another
     department, which is exactly what the publish check rejects. */

  function loadTaxonomy() {
    if (!el.taxonomy) return;
    try {
      var parsed = JSON.parse(el.taxonomy.textContent || '[]');
      state.taxonomy = Array.isArray(parsed) ? parsed : [];
    } catch (err) {
      state.taxonomy = [];
    }
  }

  function categoryEntry(name) {
    var wanted = String(name || '').trim().toLowerCase();
    var found = null;
    state.taxonomy.forEach(function (entry) {
      if (found) return;
      if (String(entry.name).toLowerCase() === wanted) found = entry;
    });
    if (!found) return null;
    state.taxonomy.forEach(function (entry) {
      if (found) return;
      if (String(entry.name).toLowerCase().replace(/&/g, 'and') ===
          wanted.replace(/&/g, 'and')) {
        found = entry;
      }
    });
    return found;
  }

  function renderSubcategories(keep) {
    if (!el.subcategory) return;
    var previous = keep === undefined ? val(el.subcategory) : keep;
    var entry = categoryEntry(val(el.category));
    var previousSub = null;
    state.taxonomy.forEach(function (item) {
      item.subcategories.forEach(function (sub) {
        if (String(sub.name).toLowerCase() === String(previous || '').toLowerCase()) {
          previousSub = sub.name;
        }
      });
    });

    el.subcategory.innerHTML = '';
    if (!entry) {
      addOption(el.subcategory, '', 'Choose a category first');
    } else if (!entry.subcategories.length) {
      /* Not every department has a second level yet; saying so beats an
         empty box the seller has to guess at. */
      addOption(el.subcategory, '', entry.name + ' has no subcategories');
    } else {
      addOption(el.subcategory, '', 'Select a subcategory');
      entry.subcategories.forEach(function (sub) {
        addOption(el.subcategory, sub.name, sub.name);
      });
      if (previousSub) el.subcategory.value = previousSub;
    }
  }

  function addOption(select, value, label) {
    var option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }

  function selectCategory(name, overwrite) {
    var entry = categoryEntry(name);
    if (!entry) return false;
    if (!overwrite && el.category.value === entry.name) return false;
    el.category.value = entry.name;
    renderSubcategories('');
    reRecommendPrice();
    return true;
  }

  function selectSubcategory(name, overwrite) {
    var entry = categoryEntry(val(el.category));
    if (!entry) return false;
    var wanted = String(name || '').trim().toLowerCase();
    var match = null;
    entry.subcategories.forEach(function (sub) {
      if (!match && String(sub.name).toLowerCase() === wanted) match = sub.name;
    });
    if (!match) return false;
    if (!overwrite && el.subcategory.value === match) return false;
    renderSubcategories(match);
    reRecommendPrice();
    return true;
  }

  async function generateCatalog(btn, overwrite) {
    var facts = productFacts();
    if (!facts.title && !facts.seller_notes) {
      showError('Tell us about your product first — type a few words or use the microphone.');
      return false;
    }

    var result = await apiPost('text/product/catalog/', facts);
    if (!result.ok) {
      showError(result.error || 'We could not write the listing just now. Please try again.');
      return false;
    }

    clearError();
    applyCatalog(result.data, !!overwrite);
    state.guideDone.generate = true;
    renderGuide();
    return true;
  }

  /* ─── Price ─────────────────────────────────────────────────────────
     The slider, the fill bar, the big number, the commit button and the
     manual input are all driven from one value, and the slider's bounds are
     rebuilt around whatever that value is. The previous version clamped the
     slider's reading to a fixed 1200-1800 window while the input itself
     offered 100 to 50000, so the thumb and the label disagreed. */

  function roundPrice(n) {
    /* Nearest ten, for the *bounds* only. The slider itself steps by one
       rupee, so the price it is given is never silently snapped. */
    return Math.max(10, Math.round(n / 10) * 10);
  }

  function sliderBounds() {
    var centre = state.recommended || PRICE_DEFAULT;
    var min = roundPrice(centre * PRICE_FLOOR_RATIO);
    var max = roundPrice(centre * PRICE_CEIL_RATIO);
    if (max - min < 100) max = min + 100;
    return { min: min, max: max };
  }

  /* The text half of the price display. Split out because the manual input
     needs to repaint the card and the commit button while the seller is still
     typing, without waiting for the change event to settle the slider. */
  function paintPriceLabels() {
    var v = state.price;
    el.priceValue.textContent = rupees(v);
    el.rangeNow.textContent = rupees(v);
    el.cardPrice.textContent = rupees(v);
    el.usePriceValue.textContent = rupees(v);
    el.priceLabel.textContent = v === state.recommended ? 'Recommended price' : 'Your price';
  }

  function renderPrice(chosen, keepField) {
    var v = state.price;
    var bounds = sliderBounds();
    /* Widen rather than clamp: a seller who types 60000 must be able to
       publish at 60000, and the slider has to be able to show that. */
    if (v < bounds.min) bounds.min = roundPrice(v * PRICE_FLOOR_RATIO);
    if (v > bounds.max) bounds.max = roundPrice(v * PRICE_CEIL_RATIO);
    if (bounds.max - bounds.min < 100) bounds.max = bounds.min + 100;

    el.priceRange.min = String(bounds.min);
    el.priceRange.max = String(bounds.max);
    el.priceRange.value = String(v);
    el.rangeMin.textContent = rupees(bounds.min);
    el.rangeMax.textContent = rupees(bounds.max);

    var pct = ((v - bounds.min) / (bounds.max - bounds.min)) * 100;
    el.rangeFill.style.width = Math.max(0, Math.min(100, pct)) + '%';

    paintPriceLabels();
    /* keepField is set while the seller is typing: writing the value back
       would eat a trailing decimal point, and the slider, the fill bar and
       the labels still have to move with the keystroke. */
    if (!keepField && !el.priceEdit.hidden) el.priceInput.value = v;

    if (chosen !== false) {
      state.priceChosen = true;
      syncChecklist();
      renderNav();
    }
  }

  function setPrice(value, chosen) {
    var n = Math.round(Number(value));
    if (!isFinite(n) || n <= 0) return false;
    state.price = n;
    renderPrice(chosen);
    return true;
  }

  /* The suggestion is the average price of what this shop already sells in
     the chosen department (and subdepartment, when one is picked), so it moves
     when the catalogue does and it can be explained to the seller instead of
     being an unexplained number. Departments with nothing listed yet fall back
     to a neutral default and say so. */
  function suggestedPrice() {
    var entry = categoryEntry(val(el.category));
    if (!entry) return { price: PRICE_DEFAULT, basis: '' };

    var wanted = val(el.subcategory);
    var sub = null;
    entry.subcategories.forEach(function (item) {
      if (String(item.name).toLowerCase() === String(wanted || '').toLowerCase()) {
        sub = item;
      }
    });

    if (sub && sub.avg_price) {
      return {
        price: sub.avg_price,
        basis: 'the average of ' + sub.live + ' live ' +
               (sub.live === 1 ? 'product' : 'products') + ' in ' +
               sub.name
      };
    }
    if (entry.avg_price) {
      return {
        price: entry.avg_price,
        basis: 'the average of ' + entry.live + ' live ' +
               (entry.live === 1 ? 'product' : 'products') + ' in ' +
               entry.name
      };
    }
    return {
      price: PRICE_DEFAULT,
      basis: 'nothing is listed in ' + entry.name + ' yet, so start where you like'
    };
  }

  function reRecommendPrice() {
    var suggestion = suggestedPrice();
    paintPriceBasis(suggestion.basis);
    if (suggestion.price === state.recommended) return;
    state.recommended = suggestion.price;
    /* Only move the seller's price if they have not committed one. */
    if (!state.priceChosen) setPrice(suggestion.price, false);
  }

  function paintPriceBasis(basis) {
    if (!el.priceBasis) return;
    el.priceBasis.textContent = basis || '';
    el.priceBasis.hidden = !basis;
  }

  /* ─── Publish ───────────────────────────────────────────────────── */

  /* The photo only has to reach the server if no enhancement job already
     holds it. Without this the seller who skipped step 2 would publish a
     product with no image and no error to explain why. */
  async function ensurePhotoOnServer() {
    if (state.enhanceJob) return { ok: true };
    if (!state.imageBlob) {
      return { ok: false, error: 'Your photo is still loading. Please try again in a moment.' };
    }

    var form = new FormData();
    form.append('image', state.imageBlob, state.imageName || 'product.jpg');
    var result = await apiUpload('image/upload/', form);
    if (!result.ok) {
      return { ok: false, error: result.error || 'We could not upload your photo. Please try again.' };
    }
    state.enhanceJob = result.data.job;
    /* The upload stores the photo untouched, so "keep the original" is not
       just a preference here, it is the only artefact there is. */
    state.enhanced = false;
    return { ok: true };
  }

  async function publish(btn) {
    if (state.publishing) return;

    if (!val(el.title)) {
      showError('Your listing needs a title. Go back and add one.');
      goTo(4, true);
      return;
    }
    if (!val(el.catalogDesc)) {
      showError('Your listing needs a description. Go back and add one.');
      goTo(4, true);
      return;
    }
    if (!state.hasImage) {
      showError('Add a product photo before publishing.');
      goTo(1, true);
      return;
    }
    if (!state.priceChosen || state.price <= 0) {
      showError('Confirm your price before publishing.');
      goTo(5, true);
      return;
    }
    /* Publish resolves both against the shop's taxonomy and refuses a name
       that is not a row, so an unfilled picker has to be caught here with a
       message that says which one, instead of coming back as a generic
       "could not create the draft" from the server. */
    if (!val(el.category)) {
      showError('Choose a category for your product.');
      goTo(4, true);
      return;
    }
    if (!val(el.subcategory)) {
      showError('Choose a subcategory for your product.');
      goTo(4, true);
      return;
    }

    clearError();
    state.publishing = true;

    var stored = await ensurePhotoOnServer();
    if (!stored.ok) {
      state.publishing = false;
      showError(stored.error);
      return;
    }

    var payload = {
      title: val(el.title),
      /* The reviewed catalog description, not the raw notes: the seller may
         have corrected the copy on the review step and that is the version
         they agreed to list. */
      description: val(el.catalogDesc),
      category: val(el.category),
      subcategory: val(el.subcategory),
      language: state.lang,
      keywords: (state.keywords || []).join(','),
      price: String(state.price),
      stock: String(state.stock > 0 ? state.stock : 1),
      enhancement_job: state.enhanceJob ? state.enhanceJob.id : null,
      use_enhanced: state.enhanced === true && !!(state.enhanceJob && state.enhanceJob.enhanced_url)
    };

    var result = await apiPost('publish/', payload);
    state.publishing = false;

    if (!result.ok) {
      showError(result.error || 'We could not create the draft. Please try again.');
      return;
    }

    /* Retire the wizard: there is nothing left to edit, and leaving a live
       "Next" button under a success message invites a second draft. */
    el.workspace.classList.add('is-hidden');
    el.nav.classList.add('is-hidden');
    el.stepper.classList.add('is-hidden');
    el.progress.classList.add('is-hidden');
    el.panels.forEach(function (panel) { panel.hidden = true; });
    el.done.hidden = false;
    if (el.doneLink) el.doneLink.href = result.data.product_url;
    el.done.scrollIntoView({
      behavior: reduced.matches ? 'auto' : 'smooth',
      block: 'center'
    });
  }

  /* ─── Wiring ──────────────────────────────────────────────────── */

  var HOOKS = {
    'pick-image': function () { el.file.click(); },
    'replace-image': function () { clearError(); el.file.click(); },
    'remove-image': clearImage,

    /* 1 · image enhancement */
    enhance: function (btn) { enhanceImage(btn); },
    'use-enhanced': applyEnhanced,
    'keep-original': keepOriginal,

    /* 2 · speech-to-text */
    record: transcribeAudio,
    'record-toggle': transcribeAudio,

    /* 3 · listing copy */
    generate: function (btn) {
      withBusy(btn, function () {
        return generateCatalog(btn, true).then(function (ok) {
          if (!ok) return;
          goTo(4);
        });
      });
    },
    regen: function (btn) {
      withBusy(btn, function () {
        /* Regenerate is a second chance at the whole listing, not just the
           keywords: the terms are the part most likely to be unhelpfully
           generic, and they are derived from the rest. */
        return generateCatalog(btn, true).then(function (ok) {
          if (ok) flash(el.keywordsList);
        });
      });
    },
    'edit-listing': function () { goTo(4, true); },

    /* 4 · price */
    'edit-price': function (btn) {
      var open = el.priceEdit.hidden;
      el.priceEdit.hidden = !open;
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) {
        el.priceInput.value = state.price;
        el.priceInput.focus();
        el.priceInput.select();
      }
    },
    'use-price': function () {
      if (!el.priceEdit.hidden) {
        var manual = Number(el.priceInput.value);
        if (!isFinite(manual) || manual <= 0) {
          showError('Please enter a price greater than zero.');
          el.priceInput.focus();
          return;
        }
        el.priceEdit.hidden = true;
        el.editPriceBtn.setAttribute('aria-expanded', 'false');
        setPrice(manual, true);
      }
      state.priceChosen = true;
      syncChecklist();
      clearError();
      goTo(6);
    },

    /* 5 · publish */
    publish: function (btn) {
      withBusy(btn, function () {
        return publish(btn);
      });
    },

    next: function () {
      if (!canLeave(state.step)) {
        showError(blockReason(state.step));
        return;
      }
      clearError();
      goTo(state.step + 1);
    },
    back: function () {
      clearError();
      goTo(state.step - 1, true);
    }
  };

  root.addEventListener('click', function (e) {
    var trigger = e.target.closest('[data-studio-hook]');
    if (!trigger || !root.contains(trigger)) return;
    if (trigger.disabled) return;
    var fn = HOOKS[trigger.getAttribute('data-studio-hook')];
    if (fn) fn(trigger, e);
  });

  /* Tapping an already-visited step jumps straight back to it. */
  root.addEventListener('click', function (e) {
    var trigger = e.target.closest('[data-goto]');
    if (!trigger || trigger.disabled || !root.contains(trigger)) return;
    var target = Number(trigger.getAttribute('data-goto'));
    goTo(target, target < state.step);
  });

  el.file.addEventListener('change', function () { useImage(el.file.files[0]); });

  /* A file can pass the type check and still be undecodable here. Treat that
     as a first-class outcome rather than a blank frame. */
  [el.pickedImg, el.preview, el.beforeImg, el.cardImg].forEach(function (img) {
    img.addEventListener('error', function () {
      if (state.imageUrl && !state.tearingDown) previewFailed();
    });
  });

  /* The enhanced file is a server URL, so its decode failure is an upload
     problem rather than a "this browser cannot show it" problem, and it must
     not flip the whole studio into the stand-in state. */
  el.afterImg.addEventListener('error', function () {
    if (state.enhancedUrl) {
      showError('The enhanced preview could not be loaded. Keeping your original photo.');
      keepOriginal();
    }
  });

  ['dragenter', 'dragover'].forEach(function (type) {
    el.drop.addEventListener(type, function (e) {
      e.preventDefault();
      el.drop.classList.add('is-over');
    });
  });

  ['dragleave', 'dragend'].forEach(function (type) {
    el.drop.addEventListener(type, function () { el.drop.classList.remove('is-over'); });
  });

  el.drop.addEventListener('drop', function (e) {
    e.preventDefault();
    el.drop.classList.remove('is-over');
    if (e.dataTransfer && e.dataTransfer.files) useImage(e.dataTransfer.files[0]);
  });

  /* Tabs — WAI-ARIA tabs pattern: one tab stop, arrows move between tabs. */
  var tabList = $$('.ais-tab');

  function selectTab(tab, focus) {
    var key = tab.getAttribute('data-tab');
    tabList.forEach(function (t) {
      var on = t === tab;
      t.classList.toggle('is-active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
    });
    /* Both the attribute and the class are toggled: the class is what the
       stylesheet keys on, the attribute is what assistive tech reads, and
       leaving one of them behind is how a "hidden" panel stays visible. */
    var panels = { voice: $('#aisVoice'), type: $('#aisType') };
    tabList.forEach(function (t) {
      var panel = panels[t.getAttribute('data-tab')];
      if (!panel) return;
      var on = t === tab;
      panel.hidden = !on;
      panel.classList.toggle('is-active', on);
    });
    if (focus) {
      tab.focus();
      if (key === 'type') el.desc.focus();
    }
  }

  tabList.forEach(function (tab) {
    tab.tabIndex = tab.classList.contains('is-active') ? 0 : -1;
    tab.addEventListener('click', function () { selectTab(tab, false); });
    tab.addEventListener('keydown', function (e) {
      var i = tabList.indexOf(tab);
      var next = null;
      if (e.key === 'ArrowRight') next = tabList[(i + 1) % tabList.length];
      else if (e.key === 'ArrowLeft') next = tabList[(i - 1 + tabList.length) % tabList.length];
      else if (e.key === 'Home') next = tabList[0];
      else if (e.key === 'End') next = tabList[tabList.length - 1];
      if (!next) return;
      e.preventDefault();
      selectTab(next, true);
    });
  });

  /* Dictation language. Switching it while a recording is running would leave
     the model transcribing against a language the seller has changed their
     mind about, so the change is deferred to the next recording. */
  el.sttLang.addEventListener('change', function () {
    state.sttLanguage = el.sttLang.value === 'en' ? 'en' : 'hi';
  });

  /* Listing language. The panel promises the copy comes back in the chosen
     language, so changing it has to actually rewrite the copy rather than
     just move a highlight. */
  var langButtons = $$('.ais-seg-btn');
  langButtons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var lang = btn.getAttribute('data-lang');
      if (lang === state.lang) return;
      setLanguage(lang);
      if (val(el.catalogDesc) || val(el.title)) {
        withBusy(btn, function () {
          return generateCatalog(btn, true);
        });
      }
    });
  });

  function setLanguage(lang) {
    state.lang = lang;
    langButtons.forEach(function (b) {
      var on = b.getAttribute('data-lang') === lang;
      b.classList.toggle('is-active', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  el.priceRange.addEventListener('input', function () {
    setPrice(el.priceRange.value, true);
  });

  /* Typing in the manual field is itself a decision, so the tick and Next
     respond on the keystroke. renderPrice() is deliberately not used here:
     it writes the value back into the field, which would eat a trailing
     decimal point or a leading zero mid-keystroke. */
  el.priceInput.addEventListener('input', function () {
    var n = Number(el.priceInput.value);
    if (!isFinite(n) || n <= 0) return;
    state.price = Math.round(n);
    renderPrice(true, true);
  });

  el.priceInput.addEventListener('change', function () {
    var n = Number(el.priceInput.value);
    if (!isFinite(n) || n <= 0) {
      showError('Please enter a price greater than zero.');
      el.priceInput.value = state.price;
      return;
    }
    clearError();
    setPrice(n, true);
  });

  el.editPriceBtn.setAttribute('aria-expanded', 'false');

  el.title.addEventListener('input', function () {
    el.titleCount.textContent = el.title.value.length + ' / 120';
    if (val(el.title)) markDescriptionReady();
    paintCatalog();
    renderNav();
  });

  el.catalogDesc.addEventListener('input', function () {
    if (val(el.catalogDesc)) markDescriptionReady();
    paintCatalog();
  });

  el.category.addEventListener('change', function () {
    renderSubcategories();
    reRecommendPrice();
  });

  el.subcategory.addEventListener('change', function () {
    reRecommendPrice();
  });

  el.desc.addEventListener('input', function () {
    if (val(el.desc)) markDescriptionReady();
  });

  /* A live MediaRecorder keeps the microphone active after the seller leaves
     the page, so release it explicitly. 'pagehide' also fires on mobile when
     the page is put into the back/forward cache, which 'unload' does not. */
  window.addEventListener('pagehide', function () {
    releaseStream(state.micStream);
    state.micStream = null;
    stopTimer();
  });

  /* ─── Init ───────────────────────────────────────────────────── */

  loadTaxonomy();
  renderSubcategories('');
  el.titleCount.textContent = el.title.value.length + ' / 120';
  var firstSuggestion = suggestedPrice();
  state.recommended = firstSuggestion.price;
  state.price = state.recommended;
  paintPriceBasis(firstSuggestion.basis);
  /* The select is the source of truth for the spoken language, so a
     template that ships a different default is honoured rather than
     silently overridden by a hard-coded 'hi' here. */
  state.sttLanguage = el.sttLang.value === 'en' ? 'en' : 'hi';
  paintPriceLabels();
  paintKeywords([], false);
  paintCatalog();
  renderPrice(false);
  renderStepper();
  renderNav();
  syncChecklist();
  renderRecordBtn();
  renderPhoto();
  resetGuide();
})();
