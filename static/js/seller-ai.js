// static/js/seller-ai.js
class SellerAI {
  constructor(config) {
    this.config = config;
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
    
    // If switching to form mode from AI modes, sync session data to form
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
    if (!text) return alert('Please enter a description');

    this.showLoading('sl-text-loading');
    const result = await this.apiCall(this.config.catalog_url + '/text', { text, language });
    this.hideLoading('sl-text-loading');

    if (result.error) return alert('Error: ' + result.error);
    
    this.sessionData = { ...this.sessionData, ...result, inputMode: 'text' };
    this.switchMode('form');
    this.populateForm(this.sessionData);
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
      let seconds = 0;

      this.mediaRecorder.ondataavailable = e => this.audioChunks.push(e.data);
      this.mediaRecorder.onstop = () => this.onRecordingStop();

      this.mediaRecorder.start(100);
      btn.innerHTML = '<i class="fas fa-stop"></i><span>Stop Recording</span>';
      btn.classList.add('recording');
      wave.hidden = false;
      timer.hidden = false;
      
      this.timerInterval = setInterval(() => {
        seconds++;
        timer.textContent = String(Math.floor(seconds/60)).padStart(2,'0') + ':' + String(seconds%60).padStart(2,'0');
      }, 1000);
    } catch (err) {
      alert('Microphone access denied. Please enable in browser settings.');
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

    // Create audio blob
    const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
    this.recordedAudio = audioBlob;
    
    // Mock transcript for demo
    transcript.textContent = 'Transcript: "लाल हैंडलूम कॉटन साड़ी, 5.5 मीटर, जरी बॉर्डर"';
    transcript.hidden = false;
  }

  resetVoiceRecorder() {
    document.getElementById('sl-voice-retry').hidden = true;
    document.getElementById('sl-voice-submit').hidden = true;
    document.getElementById('sl-voice-transcript').hidden = true;
    this.recordedAudio = null;
  }

  async processVoiceInput() {
    if (!this.recordedAudio) return alert('Please record first');
    
    const language = document.getElementById('sl-voice-language').value;
    const formData = new FormData();
    formData.append('audio', this.recordedAudio, 'recording.webm');
    formData.append('language', language);

    this.showLoading('sl-voice-btn');
    const result = await this.apiCallForm(this.config.catalog_url + '/voice', formData);
    this.hideLoading('sl-voice-btn');

    if (result.error) return alert('Error: ' + result.error);
    
    this.sessionData = { ...this.sessionData, ...result, inputMode: 'voice' };
    this.switchMode('form');
    this.populateForm(this.sessionData);
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
    const formData = new FormData();
    formData.append('image', file);
    formData.append('preset', 'textile');

    const loadingEl = target === 'main' ? 'sl-enhance-main' : 'sl-enhance-gallery';
    this.showLoading(loadingEl);

    const result = await this.apiCallForm(this.config.image_url + '/enhance', formData);
    this.hideLoading(loadingEl);

    if (result.error) return alert('Error: ' + result.error);
    
    if (target === 'main') {
      this.sessionData.enhanced_main = result.enhanced_url;
      document.getElementById('sl-main-enhanced').src = result.enhanced_url;
      document.getElementById('sl-main-original').src = URL.createObjectURL(file);
      document.getElementById('sl-main-compare').hidden = false;
      document.getElementById('sl-enhance-main').hidden = true;
    }
  }

  async enhanceBatch(files) {
    // For demo: enhance first file only
    if (files.length) await this.enhanceImage(files[0], 'gallery');
    this.showToast(`${files.length} photos queued for enhancement`);
  }

  applyEnhancedImage(target) {
    const enhancedUrl = this.sessionData.enhanced_main;
    this.showToast('Enhanced photo applied! Original preserved.');
    document.getElementById('sl-main-compare').hidden = true;
    document.getElementById('sl-main-preview').innerHTML = `<img src="${enhancedUrl}" alt="Enhanced">`;
  }

  // ── Pricing ──
  bindPricing() {
    document.getElementById('sl-get-price')?.addEventListener('click', () => this.getPriceSuggestion());
    document.getElementById('sl-price-accept')?.addEventListener('click', () => this.acceptPrice());
  }

  async getPriceSuggestion() {
    const btn = document.getElementById('sl-get-price');
    btn.hidden = true;
    document.getElementById('sl-price-loading').hidden = false;

    // Collect current form data
    const productData = this.collectProductData();
    const result = await this.apiCall(this.config.pricing_url + '/analyze', { product: productData });

    document.getElementById('sl-price-loading').hidden = true;
    btn.hidden = false;

    if (result.error) return alert('Error: ' + result.error);

    this.sessionData.pricing = result;
    this.renderPriceResult(result);
    document.getElementById('sl-price-result').hidden = false;
  }

  renderPriceResult(data) {
    document.getElementById('sl-floor-price').textContent = '₹' + data.floor_price.toLocaleString();
    document.getElementById('sl-rec-price').textContent = '₹' + data.recommended_price.toLocaleString();
    document.getElementById('sl-premium-price').textContent = '₹' + data.premium_price.toLocaleString();
    document.getElementById('sl-price-confidence').textContent = Math.round(data.confidence * 100) + '% confident';
    
    const reasoningEl = document.getElementById('sl-price-reasoning');
    reasoningEl.innerHTML = '<h4>Why this price?</h4><ul>' + 
      data.reasoning.map(r => '<li>' + r + '</li>').join('') + '</ul>';
  }

  acceptPrice() {
    document.getElementById('id_price').value = this.sessionData.pricing.recommended_price;
    document.getElementById('sl-price-result').hidden = true;
    this.showToast('Recommended price applied!');
    // Trigger preview update
    document.getElementById('id_price').dispatchEvent(new Event('input'));
  }

  // ── Blogs ──
  bindBlogs() {
    document.getElementById('sl-gen-blogs')?.addEventListener('click', () => this.generateBlogs());
  }

  async generateBlogs() {
    const btn = document.getElementById('sl-gen-blogs');
    btn.hidden = true;
    document.getElementById('sl-blogs-loading').hidden = false;

    const result = await this.apiCall(this.config.catalog_url.replace('/catalog', '') + '/catalog/generate-blogs', {
      session_data: this.sessionData
    });

    document.getElementById('sl-blogs-loading').hidden = true;
    btn.hidden = false;

    if (result.error) return alert('Error: ' + result.error);

    this.renderBlogs(result.blogs);
    document.getElementById('sl-blogs-list').hidden = false;
  }

  renderBlogs(blogs) {
    const container = document.getElementById('sl-blogs-list');
    container.innerHTML = blogs.map((blog, i) => `
      <div class="sl-blog-draft">
        <h4>${blog.title}</h4>
        <span class="sl-blog-type">${blog.type}</span>
        <div class="sl-blog-preview">${blog.body.substring(0, 150)}...</div>
        <label class="sp-field-check">
          <input type="checkbox" name="publish_blog_${i}" checked>
          <span>Publish with product</span>
        </label>
      </div>
    `).join('');
  }

  // ── Form Population ──
  populateForm(data) {
    const attrs = data.attributes || {};
    const desc = data.descriptions || {};
    const tags = data.seo_tags || [];

    // Fill form fields
    document.getElementById('id_name').value = `${attrs.color || ''} ${attrs.material || ''} ${attrs.subcategory || 'Product'}`.trim();
    document.getElementById('id_name').dispatchEvent(new Event('input'));
    
    const descriptionValue = desc.en || desc.original || '';
    document.getElementById('id_description').value = descriptionValue;
    // Trigger CKEditor update
    if (window.CKEDITOR && CKEDITOR.instances['id_description']) {
      CKEDITOR.instances['id_description'].setData(descriptionValue);
    }

    // Category
    const catSelect = document.getElementById('id_category');
    if (catSelect && data.suggested_category) {
      for (let opt of catSelect.options) {
        if (opt.text.toLowerCase().includes(data.suggested_category.split('>')[1]?.trim().toLowerCase() || '')) {
          catSelect.value = opt.value;
          break;
        }
      }
    }

    // Brand from origin
    if (attrs.origin_story) {
      document.getElementById('id_brand').value = 'Artisan Made';
    }

    // Update readiness checklist
    if (window.evalChecklist) window.evalChecklist();
  }

  collectProductData() {
    return {
      images: [this.sessionData.enhanced_main].filter(Boolean),
      description: document.getElementById('id_description').value,
      category: document.getElementById('id_category').options[document.getElementById('id_category').selectedIndex]?.text || '',
      attributes: this.sessionData.attributes || {}
    };
  }

  // ── Utilities ──
  apiCall(url, data) {
    return fetch(url, {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json', 
        'X-AI-Action': 'true',
        'X-CSRFToken': this.getCsrfToken()
      },
      body: JSON.stringify(data)
    }).then(r => r.json());
  }

  apiCallForm(url, formData) {
    formData.append('csrfmiddlewaretoken', this.getCsrfToken());
    return fetch(url, {
      method: 'POST',
      headers: { 'X-AI-Action': 'true' },
      body: formData
    }).then(r => r.json());
  }

  getCsrfToken() {
    const cookie = document.cookie.split('; ').find(row => row.startsWith('csrftoken='));
    return cookie ? cookie.split('=')[1] : '';
  }

  showLoading(elId) {
    const el = document.getElementById(elId);
    if (el) el.hidden = false;
  }

  hideLoading(elId) {
    const el = document.getElementById(elId);
    if (el) el.hidden = true;
  }

  showToast(msg) {
    const toast = document.createElement('div');
    toast.className = 'sl-toast';
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
  }

  showImagePreview(file, containerId) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = e => {
      document.getElementById(containerId).innerHTML = `<img src="${e.target.result}" alt="Preview">`;
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
      });
      reader.readAsDataURL(file);
    });
    container.hidden = container.childElementCount === 0;
  }

  bindFormSync() {
    // Sync form changes back to sessionData for AI Assist mode
    ['id_name', 'id_price', 'id_brand', 'id_category'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.addEventListener('change', () => {
        this.sessionData[id.replace('id_', '')] = el.value;
      });
    });
  }
}

// Initialize when DOM ready
document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('sl-form')) {
    const configScript = document.getElementById('ai-config');
    if (configScript) {
      const config = JSON.parse(configScript.textContent);
      window.sellerAI = new SellerAI(config);
    }
  }
});