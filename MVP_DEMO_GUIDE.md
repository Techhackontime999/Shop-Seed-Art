# Shop-Seed Art: AI-Powered Seller MVP Demo

## Quick Start (5 minutes)

### 1. Start Mock AI API Server
```bash
cd worktrees/issue-5
pip install fastapi uvicorn python-multipart
uvicorn mock_ai_api:app --port 8001 --reload
```
Server runs at: `http://localhost:8001`

### 2. Start Django (in another terminal)
```bash
cd worktrees/issue-5
source siteenv/Scripts/activate  # or your venv
python manage.py runserver
```
Django runs at: `http://localhost:8000`

### 3. Create Verified Seller Account
```bash
# Create superuser (if needed)
python manage.py createsuperuser

# Login as seller, go to /seller/dashboard
# Click "Add Product" → Test AI features
```

### 4. Enable HTTPS for Microphone (Required for Voice)
```bash
# Install mkcert
choco install mkcert  # Windows
mkcert -install
mkcert localhost 127.0.0.1 ::1

# Run Django with HTTPS
python manage.py runserver --certificate localhost.pem --key localhost-key.pem
```
Access at: `https://localhost:8000`

---

## Demo Flow (3 minutes)

### Voice Mode Demo
1. Click **"Voice"** tab
2. Select **"हिंदी"**
3. Click **"Tap to Record"**
4. Speak: *"लाल हैंडलूम कॉटन साड़ी, 5.5 मीटर, जरी बॉर्डर, ऑफिस वियर के लिए"*
5. Click **"Stop Recording"**
6. Click **"Generate Listing"**
7. Watch form auto-fill with English + Hindi descriptions

### Text Mode Demo
1. Click **"Text"** tab
2. Type: *"Handloom cotton saree, red, 5.5 meters, zari border, for office wear"*
3. Click **"Generate Listing"**
4. Form fills automatically

### Image Enhancement Demo
1. Upload a photo in **Main Photo**
2. Click **"Enhance with AI"**
3. See before/after comparison
4. Click **"Use Enhanced"**

### Smart Pricing Demo
1. Fill basic details (or use AI-generated)
2. Scroll to **"Smart Pricing"** section
3. Click **"Get AI Price Suggestion"**
4. See Floor/Recommended/Premium with reasoning
5. Click **"Use Recommended Price"**

### Blog Generation Demo
1. Scroll to **"Launch Blogs"** section
2. Click **"Generate Launch Blogs"**
3. See 3 auto-generated blog posts
4. Check boxes to publish with product

### Publish
1. Click **"Publish listing"**
2. Product goes live with blogs!

---

## Key Files Modified

| File | Purpose |
|------|---------|
| `seller/views.py` | Enhanced `add_product` with AI API handlers |
| `seller/templates/seller/add_product.html` | AI tabs, voice recorder, pricing, blogs, enhanced photos |
| `static/js/seller-ai.js` | All AI interactions (voice, text, image, pricing, blogs) |
| `static/css/seller-ai.css` | Styling for AI features |
| `config/settings/local.py` | AI API configuration |
| `mock_ai_api.py` | Standalone mock API server |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Microphone not working | Use HTTPS (`mkcert`), check browser permissions |
| AI API timeout | Increase `AI_API_TIMEOUT` in settings |
| CSRF errors | Ensure `X-CSRFToken` header is sent |
| CKEditor not updating | Check `CKEDITOR.instances['id_description'].setData()` |
| Voice transcript not showing | Mock API returns transcript in response |

---

## For Production (After MVP)

1. Replace mock API with real Triton/TorchServe models
2. Add authentication (JWT) to AI API Gateway
3. Implement async job queue with Celery + Redis
4. Add model versioning and A/B testing
5. Set up monitoring (Prometheus/Grafana)

---

## Demo Credentials
- **Seller Login**: Use any verified seller account
- **Test Data**: Speak/type in Hindi/English for best results
- **Images**: Any product photo works (mock returns placeholder)