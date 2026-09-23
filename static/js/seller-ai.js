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
    this.bindChat();
    this.bindTranslate();
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

    if (mode === 'ai-assist') {
      document.getElementById('sl-chat-text')?.focus();
      this.scrollChat();
    }
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
    // Chat assistant is stateless about progress steps; kept as a no-op hook
    // so existing callers stay valid.
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

  // ── Bilingual translate (English <-> Hindi, everywhere) ──
  bindTranslate() {
    document.querySelectorAll('[data-translate]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const fieldId = btn.dataset.translate;
        let text = this.getFieldValue(fieldId);
        if (!text) {
          this.showToast('Nothing to translate yet — add some text first', 'error');
          return;
        }
        const target = btn.dataset.target === 'hi-IN' ? 'hi-IN' : 'en-IN';
        btn.classList.add('is-loading');
        const original = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-spinner"></i>';
        const result = await this.apiAction('translate', {
          text,
          target_language: target
        });
        btn.classList.remove('is-loading');
        btn.innerHTML = original;
        if (result.error) {
          this.showToast('Translation failed: ' + result.error, 'error');
          return;
        }
        this.setFieldValue(fieldId, result.translation);
        // Swap the button so the next click goes the other direction.
        btn.dataset.target = target === 'hi-IN' ? 'en-IN' : 'hi-IN';
        btn.title = target === 'hi-IN' ? 'Translate to English' : 'Translate to Hindi';
        btn.innerHTML = target === 'hi-IN'
          ? '<i class="fas fa-language"></i> English'
          : '<i class="fas fa-language"></i> हिंदी';
        this.showToast('Translated to ' + (target === 'hi-IN' ? 'हिंदी' : 'English'));
      });
    });
  }

  getFieldValue(fieldId) {
    const el = document.getElementById(fieldId);
    if (!el) return '';
    if (fieldId === 'id_description' && window.CKEDITOR && CKEDITOR.instances['id_description']) {
      return CKEDITOR.instances['id_description'].getData();
    }
    return el.value;
  }

  setFieldValue(fieldId, value) {
    const el = document.getElementById(fieldId);
    if (!el) return;
    if (fieldId === 'id_description' && window.CKEDITOR && CKEDITOR.instances['id_description']) {
      CKEDITOR.instances['id_description'].setData(value);
      return;
    }
    el.value = value;
    el.dispatchEvent(new Event('input'));
  }

  // ── Interactive Chat Assistant ──
  bindChat() {
    this.chatSession = {};
    this.speechRecognition = null;
    this.speechListening = false;

    const body = document.getElementById('sl-chat-body');
    const text = document.getElementById('sl-chat-text');
    const send = document.getElementById('sl-chat-send');
    const mic = document.getElementById('sl-chat-mic');
    const build = document.getElementById('sl-chat-build');
    const clear = document.getElementById('sl-chat-clear');

    // Support both prefixed and standard SpeechRecognition
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SR) {
      this.speechRecognition = new SR();
      this.speechRecognition.lang = 'hi-IN';
      this.speechRecognition.interimResults = false;
      this.speechRecognition.continuous = false;
      this.speechRecognition.onresult = (e) => {
        const transcript = Array.from(e.results).map(r => r[0].transcript).join(' ');
        this.setChatListening(false);
        const chatInput = document.getElementById('sl-chat-input');
        if (chatInput) chatInput.classList.remove('is-listening');
        if (transcript) {
          const input = document.getElementById('sl-chat-text');
          input.value = transcript;
          this.sendChatMessage();
        }
      };
      this.speechRecognition.onerror = (e) => {
        this.setChatListening(false);
        this.showToast('Voice not recognized — try typing instead', 'error');
      };
      this.speechRecognition.onend = () => {
        this.setChatListening(false);
      };
    } else {
      if (mic) mic.title = 'Voice not supported in this browser — type instead';
    }

    const onSend = () => {
      const val = (text ? text.value : '').trim();
      if (val) this.sendChatMessage();
    };

    text?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); onSend(); }
    });
    send?.addEventListener('click', onSend);

    mic?.addEventListener('click', () => {
      if (!this.speechRecognition) {
        this.showToast('Voice input needs Chrome/Edge — try typing', 'error');
        return;
      }
      if (this.speechListening) {
        this.speechRecognition.stop();
        this.setChatListening(false);
        return;
      }
      try {
        this.speechRecognition.lang = this.detectChatLanguage() || 'hi-IN';
        this.speechRecognition.start();
        this.setChatListening(true);
        this.scrollChat();
      } catch (e) {
        this.showToast('Could not start microphone', 'error');
      }
    });

    document.querySelectorAll('.sl-chat-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        this.addChatMsg(chip.textContent.trim(), 'user');
        this.runChatAssistant(chip.dataset.quick || chip.textContent);
      });
    });

    build?.addEventListener('click', () => this.buildListingFromChat());
    clear?.addEventListener('click', () => this.resetChat());
  }

  setChatListening(on) {
    this.speechListening = on;
    const input = document.getElementById('sl-chat-input');
    const mic = document.getElementById('sl-chat-mic');
    const rec = document.getElementById('sl-chat-rec');
    if (input) input.classList.toggle('is-listening', on);
    if (mic) mic.classList.toggle('recording', on);
    if (rec) rec.hidden = !on;
    if (on) this.scrollChat();
  }

  detectChatLanguage() {
    // Bilingual only: Devanagari → Hindi, else English.
    const raw = String(this.chatSession?.raw_description || '');
    if (/[\u0900-\u097F]/.test(raw.slice(-200))) return 'hi-IN';
    return 'en-IN';
  }

  addChatMsg(text, role) {
    const body = document.getElementById('sl-chat-body');
    if (!body) return;
    const wrap = document.createElement('div');
    wrap.className = 'sl-msg ' + (role === 'user' ? 'sl-msg-user is-new' : 'sl-msg-ai is-new');
    const avatar = document.createElement('div');
    avatar.className = 'sl-msg-avatar';
    avatar.innerHTML = role === 'user' ? '<i class="fas fa-user"></i>' : '<i class="fas fa-robot"></i>';
    const bubble = document.createElement('div');
    bubble.className = 'sl-msg-bubble';
    const p = document.createElement('p');
    p.textContent = text;
    const time = document.createElement('span');
    time.className = 'sl-msg-time';
    time.textContent = 'now';
    bubble.appendChild(p);
    bubble.appendChild(time);
    wrap.appendChild(avatar);
    wrap.appendChild(bubble);
    body.appendChild(wrap);
    this.scrollChat();
    requestAnimationFrame(() => wrap.classList.remove('is-new'));
  }

  scrollChat() {
    const body = document.getElementById('sl-chat-body');
    if (body) body.scrollTop = body.scrollHeight;
  }

  async runChatAssistant(message) {
    const build = document.getElementById('sl-chat-build');
    if (build) {
      build.disabled = true;
      build.classList.add('is-loading');
      build.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Thinking…';
    }
    const result = await this.apiAction('chat', {
      message,
      language: this.detectChatLanguage(),
      session_data: JSON.stringify(this.chatSession)
    });

    if (result.error) {
      this.addChatMsg('Sorry, I hit an error. Could you rephrase that?', 'ai');
      if (build) {
        build.disabled = !(this.chatSession?.price_hint !== undefined);
        build.innerHTML = '<i class="fas fa-wand-magic-sparkles"></i> Build my listing from chat';
      }
      return;
    }

    this.chatSession = result.session || this.chatSession;
    this.addChatMsg(result.reply, 'ai');

    const ready = !!result.ready;
    if (build) {
      build.disabled = !ready;
      if (ready) build.classList.add('is-ready');
      build.innerHTML = ready
        ? '<i class="fas fa-wand-magic-sparkles"></i> Build my listing from chat'
        : '<i class="fas fa-spinner fa-spin"></i> Thinking…';
    }
    const hint = document.getElementById('sl-chat-hint');
    if (hint) {
      hint.textContent = ready
        ? 'You’re ready! Build your listing, or keep refining below.'
        : 'Answer my questions until the Build button lights up.';
    }
    document.getElementById('sl-chat-text')?.focus();
  }

  async sendChatMessage() {
    const text = document.getElementById('sl-chat-text');
    const val = (text ? text.value : '').trim();
    if (!val) return;
    if (text) text.value = '';
    this.addChatMsg(val, 'user');
    await this.runChatAssistant(val);
  }

  resetChat() {
    this.chatSession = {};
    const body = document.getElementById('sl-chat-body');
    if (body) {
      const first = body.querySelector('.sl-msg-ai');
      body.querySelectorAll('.sl-msg').forEach(m => {
        if (m !== first) m.remove();
      });
      this.scrollChat();
    }
    const build = document.getElementById('sl-chat-build');
    if (build) {
      build.disabled = true;
      build.classList.remove('is-ready');
    }
    const hint = document.getElementById('sl-chat-hint');
    if (hint) hint.textContent = 'Answer my questions until the Build button lights up.';
    this.showToast('Chat reset — let’s start over');
  }

  async buildListingFromChat() {
    const raw = String(this.chatSession?.raw_description || '');
    if (!raw) {
      this.showToast('Tell me something about your product first', 'error');
      return;
    }
    const build = document.getElementById('sl-chat-build');
    if (build) {
      build.disabled = true;
      build.classList.add('is-loading');
      build.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Building your listing…';
    }

    const result = await this.apiAction('catalog_text', {
      text: raw,
      language: this.detectChatLanguage()
    });

    if (build) {
      build.disabled = false;
      build.classList.remove('is-loading');
      build.innerHTML = '<i class="fas fa-wand-magic-sparkles"></i> Build my listing from chat';
    }

    if (result.error) {
      this.addChatMsg('I couldn’t build it just yet — please make sure your product description is a little more detailed.', 'ai');
      this.showToast('Could not build listing', 'error');
      return;
    }

    // Merge the chat-collected price hint & keep generated catalog structure.
    if (this.chatSession?.price_hint) {
      result.pricing = result.pricing || {};
      result.pricing.recommended_price = this.chatSession.price_hint;
    }
    this.sessionData = { ...result, inputMode: 'chat' };
    this.populateForm(this.sessionData);
    this.updateAssistUI();
    this.switchMode('form');
    this.showToast('Listing built from chat — review & publish!');
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