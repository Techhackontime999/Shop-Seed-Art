// static/js/seller-ai.js
class SellerAI {
  constructor(config) {
    this.config = config;
    this.aiUrl = config.ai_url || '/seller/add/';
    this.sessionData = {};
    this.mediaRecorder = null;
    this.audioChunks = [];
    this.timerInterval = null;
    this.recordedAudio = null;
    this.init();
  }

  init() {
    this.bindModeTabs();
    this.bindTextMode();
    this.bindVoiceMode();
    this.bindImageEnhancement();
    this.bindPricing();
    this.bindBlogs();
    this.bindFormSync();
  }

  // ── Mode Tabs ──
  bindModeTabs() {
    document.querySelectorAll('.sl-ai-tab').forEach(tab => {
      tab.addEventListener('click', () => this.switchMode(tab.dataset.mode));
    });
  }

  switchMode(mode) {
    document.querySelectorAll('.sl-ai-tab').forEach(t => {
      t.classList.toggle('active', t.dataset.mode === mode);
      t.setAttribute('aria-selected', t.dataset.mode === mode);
    });
    document.querySelectorAll('.sl-ai-panel').forEach(p => {
      p.hidden = p.dataset.panel !== mode;
    });

    if (mode === 'form' && Object.keys(this.sessionData).length) {
      this.populateForm(this.sessionData);
    }
  }

  // ── Text Mode ──
  bindTextMode() {
    const submit = document.getElementById('sl-text-submit');
    if (submit) submit.addEventListener('click', () => this.processTextInput());
  }

  async processTextInput() {
    const text = document.getElementById('sl-text-input').value.trim();
    const language = document.getElementById('sl-text-language').value;
    if (!text) {
      this.showToast('Please describe your product first', 'error');
      return;
    }

    this.setButtonLoading('sl-text-submit', true);
    const result = await this.apiAction('catalog_text', { text, language });
    this.setButtonLoading('sl-text-submit', false);

    if (result.error) return this.showToast('Error: ' + result.error, 'error');

    this.sessionData = { ...this.sessionData, ...result, inputMode: 'text' };
    this.switchMode('form');
    this.populateForm(this.sessionData);
    this.updateAssistUI();
    this.showToast('Product details generated from text!');
  }

  // ── Voice Mode ──
  bindVoiceMode() {
    const btn = document.getElementById('sl-voice-btn');
    const retry = document.getElementById('sl-voice-retry');
    const submit = document.getElementById('sl-voice-submit');

    btn?.addEventListener('click', () => this.toggleRecording());
    retry?.addEventListener('click', () => this.resetVoiceRecorder());
    submit?.addEventListener('click', () => this.processVoiceInput());
  }

  async toggleRecording() {
    const btn = document.getElementById('sl-voice-btn');
    const wave = document.getElementById('sl-voice-wave');
    const timer = document.getElementById('sl-voice-timer');

    if (this.mediaRecorder && this.mediaRecorder.state === 'recording') {
      this.mediaRecorder.stop();
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.mediaRecorder = new MediaRecorder(stream);
      this.audioChunks = [];
      const startTime = Date.now();

      this.mediaRecorder.ondataavailable = e => this.audioChunks.push(e.data);
      this.mediaRecorder.onstop = () => this.onRecordingStop();

      this.mediaRecorder.start(100);
      btn.innerHTML = '<i class="fas fa-stop"></i><span>Stop Recording</span>';
      btn.classList.add('recording');
      wave.hidden = false;
      timer.hidden = false;

      this.timerInterval = setInterval(() => {
        const seconds = Math.floor((Date.now() - startTime) / 1000);
        timer.textContent = String(Math.floor(seconds/60)).padStart(2,'0') + ':' + String(seconds%60).padStart(2,'0');
      }, 200);
    } catch (err) {
      this.showToast('Microphone access denied. Enable it in browser settings.', 'error');
    }
  }

  onRecordingStop() {
    const btn = document.getElementById('sl-voice-btn');
    const wave = document.getElementById('sl-voice-wave');
    const timer = document.getElementById('sl-voice-timer');
    const transcript = document.getElementById('sl-voice-transcript');
    const retry = document.getElementById('sl-voice-retry');
    const submit = document.getElementById('sl-voice-submit');

    clearInterval(this.timerInterval);
    btn.innerHTML = '<i class="fas fa-microphone"></i><span>Tap to Record</span>';
    btn.classList.remove('recording');
    wave.hidden = true;
    timer.hidden = true;
    retry.hidden = false;
    submit.hidden = false;

    const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
    this.recordedAudio = audioBlob;
    this.sessionData.audio_transcript = this.config.sample_transcript || this.config.default_voice_text || '';
    transcript.textContent = 'Transcript: "' + this.sessionData.audio_transcript + '"';
    transcript.hidden = false;
  }

  resetVoiceRecorder() {
    document.getElementById('sl-voice-retry').hidden = true;
    document.getElementById('sl-voice-submit').hidden = true;
    document.getElementById('sl-voice-transcript').hidden = true;
    this.recordedAudio = null;
  }

  async processVoiceInput() {
    // Uses speech-to-text transcript (VoiceToText API) — falls back to the
    // browser's Web Speech API result that the transcript box displays.
    const language = document.getElementById('sl-voice-language').value;
    const audioText = this.sessionData.audio_transcript || document.getElementById('sl-voice-transcript').textContent.replace(/^Transcript:\s*/, '');
    if (!audioText) {
      this.showToast('Please record a description first', 'error');
      return;
    }

    this.setButtonLoading('sl-voice-submit', true);
    const result = await this.apiAction('catalog_voice', { audio_text: audioText, language });
    this.setButtonLoading('sl-voice-submit', false);

    if (result.error) return this.showToast('Error: ' + result.error, 'error');

    this.sessionData = { ...this.sessionData, ...result, inputMode: 'voice' };
    this.switchMode('form');
    this.populateForm(this.sessionData);
    this.updateAssistUI();
    this.showToast('Product details generated from voice!');
  }

  // ── Image Enhancement ──
  bindImageEnhancement() {
    const mainInput = document.getElementById('id_image');
    const galleryInput = document.getElementById('id_gallery_images');
    const enhanceMain = document.getElementById('sl-enhance-main');
    const enhanceGallery = document.getElementById('sl-enhance-gallery');
    const useEnhanced = document.getElementById('sl-use-enhanced-main');

    mainInput?.addEventListener('change', (e) => {
      enhanceMain.hidden = !e.target.files.length;
      this.showImagePreview(e.target.files[0], 'sl-main-preview');
    });

    galleryInput?.addEventListener('change', (e) => {
      enhanceGallery.hidden = !e.target.files.length;
      this.renderGalleryPreviews(e.target.files, 'sl-new-gallery');
    });

    enhanceMain?.addEventListener('click', () => this.enhanceImage(mainInput.files[0], 'main'));
    enhanceGallery?.addEventListener('click', () => this.enhanceBatch(galleryInput.files));
    useEnhanced?.addEventListener('click', () => this.applyEnhancedImage('main'));
  }

  async enhanceImage(file, target) {
    if (!file) return;
    const formData = new FormData();
    formData.append('image', file);
    formData.append('preset', 'textile');
    formData.append('csrfmiddlewaretoken', this.getCsrfToken());

    const loadingEl = target === 'main' ? 'sl-enhance-main' : 'sl-enhance-gallery';
    this.showLoading(loadingEl);

    const result = await this.apiForm(this.aiUrl, formData, 'enhance_image');
    this.hideLoading(loadingEl);

    if (result.error) return this.showToast('Error: ' + result.error, 'error');

    if (target === 'main' && result.enhanced_url) {
      this.sessionData.enhanced_main = result.enhanced_url;
      document.getElementById('sl-main-enhanced').src = result.enhanced_url;
      document.getElementById('sl-main-original').src = URL.createObjectURL(file);
      document.getElementById('sl-main-compare').hidden = false;
      document.getElementById('sl-enhance-main').hidden = true;
    }
    this.updateAssistUI();
  }

  async enhanceBatch(files) {
    if (files.length) await this.enhanceImage(files[0], 'gallery');
    this.showToast(`${files.length} photo(s) queued for enhancement`);
  }

  applyEnhancedImage(target) {
    const enhancedUrl = this.sessionData.enhanced_main;
    if (!enhancedUrl) return;
    const preview = document.getElementById('sl-main-preview');
    const img = new Image();
    img.addEventListener('load', () => {
      preview.innerHTML = '';
      preview.appendChild(img);
      preview.classList.add('has-image');
    });
    img.src = enhancedUrl;
    document.getElementById('sl-main-compare').hidden = true;
    this.showToast('Enhanced photo applied! Original preserved.');
  }

  // ── Pricing ──
  bindPricing() {
    document.getElementById('sl-get-price')?.addEventListener('click', () => this.getPriceSuggestion());
    document.getElementById('sl-price-accept')?.addEventListener('click', () => this.acceptPrice());
    document.getElementById('sl-price-reject')?.addEventListener('click', () => {
      document.getElementById('sl-price-result').hidden = true;
      document.getElementById('id_price').focus();
    });
  }

  async getPriceSuggestion() {
    const btn = document.getElementById('sl-get-price');
    btn.disabled = true;
    document.getElementById('sl-price-loading').hidden = false;

    const productData = this.collectProductData();
    const result = await this.apiAction('suggest_price', { ...productData, attributes: JSON.stringify(productData.attributes || {}) });

    document.getElementById('sl-price-loading').hidden = true;
    btn.disabled = false;

    if (result.error) return this.showToast('Error: ' + result.error, 'error');

    this.sessionData.pricing = result;
    this.renderPriceResult(result);
    document.getElementById('sl-price-result').hidden = false;
    this.updateAssistUI();
  }

  renderPriceResult(data) {
    const fmt = n => '₹' + Number(n || 0).toLocaleString('en-IN');
    document.getElementById('sl-floor-price').textContent = fmt(data.floor_price);
    document.getElementById('sl-rec-price').textContent = fmt(data.recommended_price);
    document.getElementById('sl-premium-price').textContent = fmt(data.premium_price);
    document.getElementById('sl-price-confidence').textContent = Math.round((data.confidence || 0) * 100) + '% confident';

    const reasoningEl = document.getElementById('sl-price-reasoning');
    const reasons = Array.isArray(data.reasoning) ? data.reasoning : ['Based on market analysis and comparable products'];
    reasoningEl.innerHTML = '<h4>Why this price?</h4><ul>' + reasons.map(r => '<li>' + this.escapeHtml(r) + '</li>').join('') + '</ul>';
  }

  acceptPrice() {
    const price = this.sessionData.pricing?.recommended_price;
    if (!price) return;
    document.getElementById('id_price').value = price;
    document.getElementById('sl-price-result').hidden = true;
    this.showToast('Recommended price applied!');
    document.getElementById('id_price').dispatchEvent(new Event('input'));
  }

  // ── Blogs ──
  bindBlogs() {
    document.getElementById('sl-gen-blogs')?.addEventListener('click', () => this.generateBlogs());
  }

  async generateBlogs() {
    const btn = document.getElementById('sl-gen-blogs');
    btn.disabled = true;
    document.getElementById('sl-blogs-loading').hidden = false;

    const result = await this.apiAction('generate_blogs', { session_data: JSON.stringify(this.sessionData) });

    document.getElementById('sl-blogs-loading').hidden = true;
    btn.disabled = false;

    if (result.error || !result.blogs) return this.showToast('Error generating blogs', 'error');

    this.sessionData.blogs = result.blogs;
    this.renderBlogs(result.blogs);
    document.getElementById('sl-blogs-list').hidden = false;
    this.updateAssistUI();
  }

  renderBlogs(blogs) {
    const container = document.getElementById('sl-blogs-list');
    container.innerHTML = blogs.map((blog, i) => `
      <article class="sl-blog-card">
        <div class="sl-blog-top">
          <span class="sl-blog-type ${this.escapeAttr(blog.type || 'story')}">${this.escapeHtml(blog.type || 'story')}</span>
          ${this.excerpt(blog.body_html || blog.body || '')}
        </div>
        <h4 class="sl-blog-title">${this.escapeHtml(blog.title || 'Untitled')}</h4>
        <p class="sl-blog-preview">${this.excerpt(this.stripHtml(blog.body_html || blog.body || ''), 160)}</p>
        <label class="sl-publish-check">
          <input type="checkbox" name="publish_blog_${i}" checked>
          <span>Publish with product</span>
        </label>
      </article>
    `).join('');
  }

  // ── Form Population ──
  populateForm(data) {
    const attrs = data.attributes || {};
    const desc = data.descriptions || {};
    const tags = data.seo_tags || [];

    const name = document.getElementById('id_name');
    if (name) {
      name.value = [attrs.color, attrs.material, attrs.subcategory].filter(Boolean).join(' ') || (name.value || '');
      name.dispatchEvent(new Event('input'));
    }

    const descriptionValue = desc.en || desc.original || '';
    const descEl = document.getElementById('id_description');
    if (descEl) descEl.value = descriptionValue;
    if (window.CKEDITOR && CKEDITOR.instances['id_description']) {
      CKEDITOR.instances['id_description'].setData(descriptionValue);
    }

    const catSelect = document.getElementById('id_category');
    if (catSelect && data.suggested_category) {
      const target = data.suggested_category.split('>').pop()?.trim().toLowerCase() || '';
      for (let opt of catSelect.options) {
        if (opt.text.toLowerCase().includes(target)) {
          catSelect.value = opt.value;
          break;
        }
      }
    }

    if (attrs.origin_story) {
      const brand = document.getElementById('id_brand');
      if (brand && !brand.value) brand.value = 'Artisan Made';
    }
    if (attrs.dimensions) {
      const stock = document.getElementById('id_stock');
      const used = document.getElementById('sl-preview-cat');
      if (used) used.textContent = data.suggested_category || attrs.category || this.config.labels?.category || '';
    }

    if (window.evalChecklist) window.evalChecklist();
  }

  collectProductData() {
    const descEl = document.getElementById('id_description');
    const catEl = document.getElementById('id_category');
    return {
      images: [this.sessionData.enhanced_main].filter(Boolean),
      description: descEl ? descEl.value : '',
      category: catEl?.options[catEl.selectedIndex]?.text || '',
      attributes: this.sessionData.attributes || {}
    };
  }

  // ── Utilities ──
  updateAssistUI() {
    const hasInput = Object.keys(this.sessionData).length > 0 && (this.sessionData.attributes || this.sessionData.descriptions);
    const setStep = (step, done) => {
      document.querySelectorAll(`.sl-ai-step[data-step="${step}"]`).forEach(el => {
        el.classList.toggle('active', !done);
        el.classList.toggle('done', !!done);
      });
      document.querySelectorAll(`.sl-assist-card[data-assist="${step}"]`).forEach(el => {
        el.classList.toggle('muted', !done);
      });
    };
    setStep('input', !!hasInput);
    setStep('photos', !!this.sessionData.enhanced_main || this.sessionData.enhanced_images?.length);
    setStep('price', !!this.sessionData.pricing);
    setStep('blogs', !!this.sessionData.blogs);
  }

  apiAction(action, data = {}) {
    const body = new URLSearchParams();
    Object.entries(data).forEach(([k, v]) => body.append(k, v));
    return this.apiForm(this.aiUrl, body, action);
  }

  apiForm(url, body, action) {
    return fetch(url, {
      method: 'POST',
      headers: {
        'X-AI-Action': action,
        'X-CSRFToken': this.getCsrfToken()
      },
      credentials: 'same-origin',
      body
    }).then(async r => {
      const ct = r.headers.get('content-type') || '';
      const payload = ct.includes('application/json') ? await r.json() : await r.text();
      if (!r.ok && typeof payload === 'object' && payload.error) throw new Error(payload.error);
      return payload;
    }).catch(err => ({ error: err.message }));
  }

  getCsrfToken() {
    const cookie = document.cookie.split('; ').find(row => row.startsWith('csrftoken='));
    return cookie ? cookie.split('=')[1] : '';
  }

  setButtonLoading(elId, on) {
    const el = document.getElementById(elId);
    if (!el) return;
    if (on) {
      el.dataset.originalHtml = el.innerHTML;
      el.disabled = true;
      el.classList.add('is-loading');
      el.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing…';
    } else {
      el.disabled = false;
      el.classList.remove('is-loading');
      if (el.dataset.originalHtml) { el.innerHTML = el.dataset.originalHtml; delete el.dataset.originalHtml; }
    }
  }

  showLoading(elId) {
    const el = document.getElementById(elId);
    if (el) el.hidden = false;
  }

  hideLoading(elId) {
    const el = document.getElementById(elId);
    if (el) el.hidden = true;
  }

  showToast(msg, type = 'success') {
    const toast = document.createElement('div');
    toast.className = 'sl-toast ' + (type === 'error' ? 'is-error' : 'is-success');
    toast.innerHTML = '<i class="fas ' + (type === 'error' ? 'fa-circle-exclamation' : 'fa-circle-check') + '"></i><span>' + this.escapeHtml(msg) + '</span>';
    document.body.appendChild(toast);
    setTimeout(() => { toast.classList.add('is-leaving'); setTimeout(() => toast.remove(), 300); }, 3200);
  }

  showImagePreview(file, containerId) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = e => {
      const c = document.getElementById(containerId);
      if (c) { c.innerHTML = `<img src="${e.target.result}" alt="Preview">`; c.classList.add('has-image'); }
    };
    reader.readAsDataURL(file);
  }

  renderGalleryPreviews(files, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';
    Array.from(files).forEach((file, i) => {
      if (!file.type.startsWith('image/')) return;
      const reader = new FileReader();
      reader.onload = e => {
        const tile = document.createElement('div');
        tile.className = 'sl-new-photo';
        tile.innerHTML = `<img src="${e.target.result}" alt="Photo ${i+1}"><span>${i+1}</span>`;
        container.appendChild(tile);
      };
      reader.readAsDataURL(file);
    });
    container.hidden = container.childElementCount === 0;
  }

  bindFormSync() {
    ['id_name', 'id_price', 'id_brand', 'id_category'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.addEventListener('change', () => {
        this.sessionData[id.replace('id_', '')] = el.value;
      });
    });
  }

  // ── Helpers ──
  stripHtml(html) {
    const div = document.createElement('div');
    div.innerHTML = html || '';
    return div.textContent || '';
  }

  excerpt(text, len = 90) {
    const s = String(text || '').replace(/\s+/g, ' ').trim();
    return s.length > len ? s.slice(0, len) + '…' : s;
  }

  escapeHtml(str) {
    return String(str || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  escapeAttr(str) {
    return String(str || '').replace(/[^a-z0-9_-]/gi, '');
  }
}

// Initialize when DOM ready
document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('sl-form')) {
    const configScript = document.getElementById('ai-config');
    if (configScript) {
      try {
        const config = JSON.parse(configScript.textContent);
        window.sellerAI = new SellerAI(config);
      } catch (e) {
        console.warn('AI config parse failed', e);
      }
    }
  }
});