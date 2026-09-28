/* ═══════════════════════════════════════════════════════════════════════
   AI PRODUCT STUDIO — wizard behaviour
   -----------------------------------------------------------------------
   UI ONLY. No network calls are made and nothing is uploaded, saved or
   published. The image is read in the browser with URL.createObjectURL,
   and every "AI" result is a fixed demo value stored in DEMO below.
   Each capability has a clearly marked seam so a real service can be
   swapped in later:
     1. image enhancement   -> applyEnhancement()   (hook: enhance/use-enhanced)
     2. speech-to-text      -> startRecording()      (hook: record)
     3. LLM catalog         -> generateCatalog()     (hook: generate)
     4. translation         -> setLanguage()        (hook: language seg)
     5. smart pricing       -> readPrice()           (hook: edit-price)
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

  /* Fixed sample values for the demo states. Not derived from any service. */
  var DEMO = {
    transcript: 'This is a handmade Madhubani painting made using traditional techniques. It is painted with natural colours on handmade paper and shows the folk motifs of Mithila.',
    priceMin: 1200,
    priceMax: 1800,
    priceStart: 1499
  };

  var state = {
    step: 1,
    maxStep: 1,      // furthest panel reached, so the stepper can gate its jumps
    tabMemo: {},     // last panel visited per stepper tab, so going back lands where you left
    imageUrl: null,
    enhanced: false,
    hasImage: false,
    shown: true,      // false once we know the browser cannot render the photo
    hasDescription: false,
    price: 0,
    priceChosen: false,
    lang: 'en',
    tearingDown: false
  };

  var el = {
    panels: $$('.ais-step-panel'),
    steppers: $$('[data-goto]'),
    progressFill: $('#aisProgressFill'),
    progressText: $('#aisProgressText'),
    prev: $('#aisPrev'),
    next: $('#aisNext'),
    nav: $('.ais-nav'),
    done: $('#aisDone'),
    file: $('#aisFile'),
    drop: $('#aisDrop'),
    picked: $('#aisPicked'),
    pickedImg: $('#aisPickedImg'),
    pickedStandin: $('#aisPickedStandin'),
    uploadError: $('#aisUploadError'),
    preview: $('#aisPreview'),
    mediaEmpty: $('#aisMediaEmpty'),
    previewStandin: $('#aisPreviewStandin'),
    mediaMeta: $('#aisMediaMeta'),
    mediaMetaText: $('#aisMediaMetaText'),
    mediaActions: $('#aisMediaActions'),
    enhanceState: $('#aisEnhanceState'),
    beforeImg: $('#aisBeforeImg'),
    afterImg: $('#aisAfterImg'),
    mic: $('#aisMic'),
    micLabel: $('#aisMicLabel'),
    recordBtn: $('#aisRecordBtn'),
    timer: $('#aisTimer'),
    transcript: $('#aisTranscript'),
    transcriptText: $('#aisTranscriptText'),
    desc: $('#aisDesc'),
    title: $('#aisTitle'),
    titleCount: $('#aisTitleCount'),
    catalogDesc: $('#aisCatalogDesc'),
    kw: $('.ais-kw'),
    priceRange: $('#aisPriceRange'),
    rangeFill: $('#aisRangeFill'),
    rangeNow: $('#aisRangeNow'),
    priceValue: $('#aisPriceValue'),
    priceEdit: $('#aisPriceEdit'),
    priceInput: $('#aisPriceInput'),
    usePriceBtn: $('#aisUsePriceBtn'),
    cardImg: $('#aisCardImg'),
    cardEmpty: $('#aisCardEmpty'),
    cardStandin: $('#aisCardStandin'),
    enhanceBody: $('#aisEnhanceBody'),
    enhanceBlank: $('#aisEnhanceBlank'),
    cardTitle: $('#aisCardTitle'),
    cardPrice: $('#aisCardPrice'),
    cardDesc: $('#aisCardDesc'),
    cardTags: $('#aisCardTags')
  };

  var rupees = function (n) {
    return '₹' + Number(n).toLocaleString('en-IN');
  };

  var reduced = window.matchMedia
    ? window.matchMedia('(prefers-reduced-motion: reduce)')
    : { matches: false };

  /* ─── Image ───────────────────────────────────────────────────── */

  function showError(msg) {
    if (!msg) {
      el.uploadError.hidden = true;
      el.uploadError.textContent = '';
      return;
    }
    el.uploadError.hidden = false;
    el.uploadError.textContent = msg;
  }

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

  /* Returns a blob URL that is safe to render, or null if we could not read
     the pixels at all. */
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
      var type = /png/i.test(file.type) ? 'image/png' : 'image/jpeg';
      return canvasToBlob(canvas, type, 0.9).then(function (blob) {
        if (source.revoke) URL.revokeObjectURL(source.revoke);
        if (blob) return URL.createObjectURL(blob);
        /* No canvas encoding: fall back to the original bytes. */
        return URL.createObjectURL(file);
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
    el.enhanceBody.hidden = !show;
    el.enhanceBlank.hidden = !standin;
    el.mediaMetaText.textContent = has ? 'Image uploaded' : '';
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

    showError('');
    if (state.imageUrl) URL.revokeObjectURL(state.imageUrl);
    state.imageUrl = null;
    state.hasImage = true;
    state.shown = true;
    state.enhanced = false;

    el.drop.hidden = true;
    el.picked.hidden = false;
    el.mediaMeta.hidden = false;
    el.mediaActions.hidden = false;

    setEnhanced(false);
    syncChecklist();
    renderNav();

    normalize(file).then(function (url) {
      /* The seller may have replaced or removed the photo meanwhile. */
      if (!state.hasImage) {
        URL.revokeObjectURL(url);
        return;
      }
      state.imageUrl = url;
      el.pickedImg.src = url;
      el.preview.src = url;
      el.beforeImg.src = url;
      el.afterImg.src = url;
      el.cardImg.src = url;
      renderPhoto();
      el.file.value = '';
    }).catch(function () {
      if (!state.hasImage) return;
      /* Could not read the pixels: keep the original URL as a last chance
         (some browsers render formats createImageBitmap is fussy about). */
      state.imageUrl = URL.createObjectURL(file);
      el.pickedImg.src = state.imageUrl;
      el.preview.src = state.imageUrl;
      el.beforeImg.src = state.imageUrl;
      el.afterImg.src = state.imageUrl;
      el.cardImg.src = state.imageUrl;
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
    state.hasImage = false;
    state.shown = true;
    state.enhanced = false;

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
    renderPhoto();

    setEnhanced(false);
    syncChecklist();
    renderNav();
  }

  function setEnhanced(on) {
    state.enhanced = on;
    el.enhanceState.hidden = !on;
    el.mediaMetaText.textContent = on ? 'Image ready' : 'Image uploaded';
  }

  /* ─── Steps ───────────────────────────────────────────────────── */

  function tabFor(panel) {
    return Number(panel.getAttribute('data-tab-for')) || 1;
  }

  function stepNames() {
    return el.steppers.map(function (s) {
      return $('.ais-step-name', s).textContent.trim();
    });
  }

  /* First panel belonging to a given stepper tab. */
  function firstPanelOf(tab) {
    for (var i = 0; i < el.panels.length; i++) {
      if (tabFor(el.panels[i]) === tab) return i + 1;
    }
    return 1;
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
    state.tabMemo[tabFor(target)] = next;

    renderStepper();
    renderNav();
    target.focus({ preventScroll: true });
    root.scrollIntoView({ behavior: reduced.matches ? 'auto' : 'smooth', block: 'start' });
  }

  function renderStepper() {
    var tab = tabFor(el.panels[state.step - 1]);
    var pct = (tab / el.steppers.length) * 100;

    el.steppers.forEach(function (s, i) {
      var n = i + 1;
      var visited = n <= state.maxStep;
      s.classList.toggle('is-active', n === tab);
      s.classList.toggle('is-done', visited && n < tab);
      /* Only steps already reached are jump targets. */
      s.disabled = !visited;
      if (n === tab) s.setAttribute('aria-current', 'step');
      else s.removeAttribute('aria-current');
    });

    el.progressFill.style.width = pct + '%';
    el.progressText.textContent =
      'Step ' + tab + ' of ' + el.steppers.length + ' · ' + stepNames()[tab - 1];
  }

  function renderNav() {
    var panel = el.panels[state.step - 1];
    el.prev.disabled = state.step === 1;
    el.next.disabled = state.step === el.panels.length || !canLeave(state.step);
    el.nav.classList.toggle('is-hidden', panel.getAttribute('data-nav') === 'off');
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

  /* ─── Voice (simulated timer, no audio is captured) ───────────── */

  var recTimer = null;
  var recStart = 0;

  function fmtTime(ms) {
    var s = Math.floor(ms / 1000);
    return '00:' + String(s).padStart(2, '0');
  }

  function renderRecordBtn() {
    if (recTimer) {
      el.recordBtn.innerHTML =
        '<i class="fas fa-stop" aria-hidden="true"></i> Stop Recording';
    } else {
      el.recordBtn.innerHTML =
        '<i class="fas fa-microphone" aria-hidden="true"></i> Start Recording';
    }
  }

  function stopRecording() {
    if (!recTimer) return;
    clearInterval(recTimer);
    recTimer = null;
    el.mic.classList.remove('is-live');
    el.micLabel.textContent = 'Tap to record';
    el.timer.hidden = true;
    renderRecordBtn();

    /* Demo transcript — a fixed sample, not speech recognition. */
    el.transcriptText.textContent = DEMO.transcript;
    el.transcript.hidden = false;
    state.hasDescription = true;
    syncChecklist();
  }

  function startRecording() {
    if (recTimer) {
      stopRecording();
      return;
    }
    recStart = Date.now();
    recTimer = setInterval(function () {
      el.timer.textContent = fmtTime(Date.now() - recStart);
    }, 250);
    el.mic.classList.add('is-live');
    el.micLabel.textContent = 'Listening...';
    el.timer.hidden = false;
    el.timer.textContent = fmtTime(0);
    renderRecordBtn();
  }

  /* ─── Catalog + preview sync ──────────────────────────────────── */

  function setLanguage(lang, btn) {
    state.lang = lang;
    $$('.ais-seg-btn').forEach(function (b) {
      var on = b === btn;
      b.classList.toggle('is-active', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    /* Demo only: the listing text is not translated. */
  }

  function paintCatalog() {
    var title = el.title.value.trim();
    var desc = el.catalogDesc.value.trim();
    el.cardTitle.textContent = title || 'Untitled product';
    el.cardDesc.textContent = desc;

    var words = (title + ' ' + desc).toLowerCase();
    var tags = $$('.ais-kw-item').map(function (k) {
      return k.firstChild.textContent.trim();
    }).filter(function (tag) {
      return words.indexOf(tag.toLowerCase()) !== -1;
    });
    el.cardTags.innerHTML = tags.map(function (t) {
      return '<li>' + t + '</li>';
    }).join('');
  }

  function flash(node) {
    node.classList.add('is-busy');
    setTimeout(function () { node.classList.remove('is-busy'); }, 550);
  }

  /* ─── Price ───────────────────────────────────────────────────── */

  function readPrice() {
    return Math.min(Math.max(Number(el.priceRange.value) || DEMO.priceStart, DEMO.priceMin), DEMO.priceMax);
  }

  /* `chosen` is false on first paint so the checklist only lights up once the
     seller has actually moved the slider or committed a price. */
  function renderPrice(chosen) {
    var v = readPrice();
    var pct = ((v - DEMO.priceMin) / (DEMO.priceMax - DEMO.priceMin)) * 100;
    el.rangeFill.style.width = pct + '%';
    el.rangeNow.textContent = rupees(v);
    el.priceValue.textContent = rupees(v);
    el.usePriceBtn.innerHTML =
      'Use ' + rupees(v) + ' <i class="fas fa-arrow-right" aria-hidden="true"></i>';
    el.cardPrice.textContent = rupees(v);
    if (!el.priceEdit.hidden) el.priceInput.value = v;
    state.price = v;
    if (chosen !== false) {
      state.priceChosen = true;
      syncChecklist();
    }
  }

  /* ─── Wiring ──────────────────────────────────────────────────── */

  var HOOKS = {
    'pick-image': function () { el.file.click(); },
    'replace-image': function () { el.file.click(); },
    'remove-image': clearImage,

    /* 1 · image enhancement — demo state only */
    enhance: function () {
      if (state.hasImage) goTo(2);
      else showError('Add a product photo first, then enhance it.');
    },
    'use-enhanced': function () {
      setEnhanced(true);
      goTo(3);
    },
    'keep-original': function () {
      setEnhanced(false);
      goTo(3);
    },

    /* 2 · speech-to-text — simulated, no audio is captured */
    record: startRecording,
    'record-toggle': startRecording,

    /* 3 · LLM catalog — fixed sample listing */
    generate: function () {
      state.hasDescription = true;
      el.desc.value = DEMO.transcript;
      el.transcriptText.textContent = DEMO.transcript;
      el.transcript.hidden = false;
      syncChecklist();
      goTo(4);
      paintCatalog();
    },

    regen: function () { flash(el.kw); },
    'edit-listing': function () { goTo(4, true); },
    'edit-price': function () {
      el.priceEdit.hidden = !el.priceEdit.hidden;
      if (!el.priceEdit.hidden) el.priceInput.focus();
    },
    'use-price': function () {
      if (!el.priceEdit.hidden) {
        var manual = Number(el.priceInput.value);
        if (manual > 0) {
          el.priceRange.value = Math.min(Math.max(manual, DEMO.priceMin), DEMO.priceMax);
          renderPrice();
        }
        el.priceEdit.hidden = true;
      }
      state.priceChosen = true;
      syncChecklist();
      goTo(6);
    },
    publish: function () {
      el.panels[state.step - 1].hidden = true;
      el.nav.classList.add('is-hidden');
      el.done.hidden = false;
    },
    next: function () { goTo(state.step + 1); },
    back: function () { goTo(state.step - 1, true); }
  };

  /* Step 1 has nothing to show without a photo, so Next is gated there. */
  function canLeave(step) {
    return step !== 1 || state.hasImage;
  }

  root.addEventListener('click', function (e) {
    var trigger = e.target.closest('[data-studio-hook]');
    if (!trigger || !root.contains(trigger)) return;
    var fn = HOOKS[trigger.getAttribute('data-studio-hook')];
    if (fn) fn(trigger, e);
  });

  /* Tapping an already-visited step returns to where the seller left it. */
  root.addEventListener('click', function (e) {
    var trigger = e.target.closest('[data-goto]');
    if (!trigger || trigger.disabled || !root.contains(trigger)) return;
    var tab = Number(trigger.getAttribute('data-goto'));
    goTo(state.tabMemo[tab] || firstPanelOf(tab), tab < tabFor(el.panels[state.step - 1]));
  });

  el.file.addEventListener('change', function () { useImage(el.file.files[0]); });

  /* A file can pass the type check and still be undecodable here. Treat that
     as a first-class outcome rather than a blank frame. */
  [el.pickedImg, el.preview, el.beforeImg, el.afterImg, el.cardImg].forEach(function (img) {
    img.addEventListener('error', function () {
      if (state.imageUrl && !state.tearingDown) previewFailed();
    });
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

  /* The mic and the stepper nav are handled by the delegated
     data-studio-hook listener above — no second listener here, or the
     toggle/advance would fire twice. */

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
    $('#aisVoice').hidden = key !== 'voice';
    $('#aisType').hidden = key !== 'type';
    if (focus) tab.focus();
    if (key === 'type' && focus) el.desc.focus();
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

  /* Language segmented control */
  $$('.ais-seg-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      setLanguage(btn.getAttribute('data-lang'), btn);
    });
  });

  el.priceRange.addEventListener('input', function () { renderPrice(true); });
  el.title.addEventListener('input', function () {
    el.titleCount.textContent = el.title.value.length + ' / 120';
    paintCatalog();
  });
  el.catalogDesc.addEventListener('input', paintCatalog);

  /* ─── Init ───────────────────────────────────────────────────── */

  el.titleCount.textContent = el.title.value.length + ' / 120';
  paintCatalog();
  renderPrice(false);
  renderStepper();
  renderNav();
  syncChecklist();
  renderRecordBtn();
})();
