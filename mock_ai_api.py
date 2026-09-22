#!/usr/bin/env python3
"""
Mock AI API Server for MVP Demo
Run: uvicorn mock_ai_api:app --port 8001 --reload
"""
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import uuid
import uvicorn

app = FastAPI(title="Mock AI API for Shop-Seed Art MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic Models ──
class CatalogTextRequest(BaseModel):
    text: str
    language: str = "en-IN"
    category_hint: Optional[str] = None

class CatalogResponse(BaseModel):
    attributes: dict
    descriptions: dict
    seo_tags: List[str]
    suggested_category: str
    confidence: float
    transcript: Optional[str] = None

class PricingRequest(BaseModel):
    product: dict

class PricingResponse(BaseModel):
    floor_price: int
    recommended_price: int
    premium_price: int
    currency: str = "INR"
    confidence: float
    reasoning: List[str]
    cost_breakdown: dict
    comparables: List[dict]

class EnhanceResponse(BaseModel):
    job_id: str
    enhanced_url: str
    metadata: dict

class BlogDraft(BaseModel):
    title: str
    type: str
    body: str
    featured_image: Optional[str] = None

class BlogsResponse(BaseModel):
    blogs: List[BlogDraft]

# ── Mock Data Generator ──
def generate_mock_catalog(text: str, lang: str, transcript: str = None):
    is_hindi = lang.startswith("hi")
    
    # Parse keywords for demo
    text_lower = text.lower()
    
    # Default values
    attrs = {
        "category": "textiles",
        "subcategory": "sarees" if "saree" in text_lower or "साड़ी" in text else "fabric",
        "material": "cotton" if "cotton" in text_lower or "कॉटन" in text else "silk" if "silk" in text_lower or "सिल्क" in text else "cotton",
        "technique": "handloom" if "handloom" in text_lower or "हैंडलूम" in text or "हाथ" in text else "machine",
        "color": "red" if "red" in text_lower or "लाल" in text else "blue" if "blue" in text_lower or "नीला" in text else "multicolor",
        "dimensions": "5.5m x 1.1m" if "5.5" in text or "५.५" in text else "standard",
        "weight": "300g",
        "care": "dry clean only" if "dry" in text_lower else "gentle wash",
        "occasion": "office, formal" if "office" in text_lower or "ऑफिस" in text else "casual, daily wear",
        "origin_story": "Handwoven by artisans in Varanasi using traditional techniques passed down through generations."
    }
    
    desc_en = f"Elegant {attrs['color']} {attrs['technique']} {attrs['material']} {attrs['subcategory']} featuring intricate details, perfect for {attrs['occasion']}. Made from premium {attrs['material']} with traditional {attrs['technique']} techniques."
    
    desc_hi = f"{attrs['technique']} {attrs['material']} से बनी सुंदर {attrs['color']} {attrs['subcategory']}, {attrs['occasion']} के लिए उत्तम। पारंपरिक {attrs['technique']} तकनीकों से बनी प्रीमियम {attrs['material']}।"
    
    return CatalogResponse(
        attributes=attrs,
        descriptions={
            "en": desc_en,
            "hi": desc_hi,
            "original": text
        },
        seo_tags=[f"{attrs['technique']} {attrs['material']} {attrs['subcategory']}", f"{attrs['color']} {attrs['subcategory']}", f"{attrs['occasion']} {attrs['subcategory']}", "traditional weaving"],
        suggested_category=f"{attrs['category']} > {attrs['subcategory']}",
        confidence=0.92,
        transcript=transcript
    )

# ── API Endpoints ──
@app.post("/api/ai/v1/catalog/text", response_model=CatalogResponse)
async def catalog_text(req: CatalogTextRequest):
    return generate_mock_catalog(req.text, req.language)

@app.post("/api/ai/v1/catalog/voice", response_model=CatalogResponse)
async def catalog_voice(audio: UploadFile = File(...), language: str = Form("hi-IN")):
    # Mock: return same as text but with fake transcript
    mock_text = "लाल हैंडलूम कॉटन साड़ी, 5.5 मीटर, जरी बॉर्डर, ऑफिस वियर के लिए"
    return generate_mock_catalog(mock_text, language, transcript=mock_text)

@app.post("/api/ai/v1/image/enhance", response_model=EnhanceResponse)
async def enhance_image(image: UploadFile = File(...), preset: str = Form("auto")):
    return EnhanceResponse(
        job_id=str(uuid.uuid4()),
        enhanced_url="https://via.placeholder.com/1000x1000/FFFFFF/000000?text=AI+Enhanced+Photo",
        metadata={"preset_used": preset, "processing_time_ms": 1200, "quality_score": 0.94}
    )

@app.post("/api/ai/v1/pricing/analyze", response_model=PricingResponse)
async def analyze_price(req: PricingRequest):
    return PricingResponse(
        floor_price=450,
        recommended_price=799,
        premium_price=1199,
        confidence=0.87,
        reasoning=[
            "Similar handloom cotton sarees sell at 650-950 on GeM/Amazon",
            "Raw cotton cost up 12% this quarter (Cotton Corp. index)",
            "Festival season demand typically +15% (Oct-Dec)",
            "Your craftsmanship quality scores 0.82/1.0 (visual analysis)",
            "Varanasi origin commands 10-15% premium"
        ],
        cost_breakdown={"material": 280, "labor": 120, "overhead": 50, "platform_commission": 80},
        comparables=[
            {"title": "Handloom Cotton Saree Red", "price": 850, "source": "GeM", "similarity": 0.89},
            {"title": "Pure Cotton Handwoven Saree", "price": 720, "source": "Amazon", "similarity": 0.76}
        ]
    )

@app.post("/api/ai/v1/catalog/generate-blogs", response_model=BlogsResponse)
async def generate_blogs(request: dict):
    session_data = request.get("session_data", {})
    attrs = session_data.get("attributes", {})
    desc = session_data.get("descriptions", {})
    images = session_data.get("enhanced_images", [])
    pricing = session_data.get("pricing", {})
    
    drafts = [
        BlogDraft(
            title=f"The Story Behind {attrs.get('color', '').title()} {attrs.get('subcategory', 'Product').title()}",
            type="story",
            body=f"<p>{attrs.get('origin_story', 'Handcrafted with care by our artisans.')}</p>",
            featured_image=images[0] if images else None
        ),
        BlogDraft(
            title=f"How It's Made: {attrs.get('technique', 'Handcrafted').title()} {attrs.get('material', 'Product').title()}",
            type="how_to",
            body=f"<p>Our {attrs.get('subcategory', 'products')} are made using traditional {attrs.get('technique', 'techniques')}...</p>",
            featured_image=images[1] if len(images) > 1 else None
        ),
        BlogDraft(
            title=f"Care Guide for Your {attrs.get('material', '').title()} {attrs.get('subcategory', 'Product').title()}",
            type="care",
            body=f"<p>{attrs.get('care', 'Handle with care. Dry clean recommended.')}</p>",
            featured_image=None
        )
    ]
    return BlogsResponse(blogs=drafts)

@app.get("/api/ai/v1/health")
async def health():
    return {"status": "ok", "service": "mock-ai-api", "version": "1.0.0"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001, reload=True)