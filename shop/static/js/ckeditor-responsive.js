/* Keep CKEditor's pixel width in step with the container.
   CKEditor measures the textarea once at startup and writes the result onto
   the chrome as an inline pixel width. ckeditor-responsive.css overrides that
   with `width: 100% !important`, but the editing frame and the dropdown panels
   keep the stale measurement, so they have to be re-measured whenever the
   viewport changes. */
(function () {
  'use strict';

  var MIN_WIDTH = 220;   // below this the toolbar is unusable
  var DEBOUNCE = 120;    // ms

  var timer = null;

  function widthFor(editor) {
    var chrome = editor.container && editor.container.getChild(0);
    var available = chrome && chrome.getBoundingClientRect().width;
    if (!available) {
      available = editor.container.getBoundingClientRect().width;
    }
    return Math.max(MIN_WIDTH, Math.floor(available));
  }

  function reflow() {
    timer = null;
    if (!window.CKEDITOR || !CKEDITOR.instances) {
      return;
    }
    for (var name in CKEDITOR.instances) {
      var editor = CKEDITOR.instances[name];
      // destroy() nulls the container out but can leave the instance listed.
      if (!editor || !editor.container || !editor.element || !editor.element.isConnected) {
        continue;
      }
      try {
        editor.resize(widthFor(editor), null, true);
      } catch (err) {
        /* A mid-teardown instance can throw; nothing useful to do here. */
      }
    }
  }

  function schedule() {
    if (timer) {
      clearTimeout(timer);
    }
    timer = setTimeout(reflow, DEBOUNCE);
  }

  window.addEventListener('resize', schedule);
  window.addEventListener('orientationchange', schedule);

  // Variant rows are added long after load and come back on bfcache restore.
  document.addEventListener('formset:added', schedule);
  window.addEventListener('pageshow', schedule);
}());
