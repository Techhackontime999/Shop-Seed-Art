"""AI services layer for the seller platform.

Holds the provider-agnostic image enhancement pipeline that backs the
"Enhance with AI" button in the AI Product Studio, plus the OpenRouter
client used for the vision advisor.

No view in this app contains image-processing or AI logic: views validate the
request, hand off to ``services.image_enhancer`` and serialise the result.
"""
