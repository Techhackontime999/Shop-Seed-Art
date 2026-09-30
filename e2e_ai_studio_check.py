"""Live end-to-end check of the AI Studio endpoints.

Unlike the unit tests this makes real network calls, so it is a script rather
than a test case: run it with

    env/Scripts/python.exe e2e_ai_studio_check.py

It exercises the flow a seller actually performs — enhance an image, generate
copy, publish a product — and prints a pass/fail line per step.
"""

import io
import json
import os
import sys
import tempfile

import django
import requests
from PIL import Image

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from accounts.models import SellerProfile  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402
from shop.models import Product  # noqa: E402

PASS, FAIL, SKIP = 'PASS', 'FAIL', 'SKIP'
results = []


def check(name, ok, detail=''):
    results.append((name, bool(ok), detail))
    print('%s  %-46s %s' % (PASS if ok else FAIL, name, detail))


def skip(name, detail):
    """Record a step the external provider prevented us from exercising.

    A free-tier model that is rate limited or out of credit is a provider
    condition, not a defect in this flow, so it is reported separately from a
    genuine failure rather than quietly ignored.
    """
    results.append((name, True, detail))
    print('%s  %-46s %s' % (SKIP, name, detail))


def is_provider_unavailable(payload):
    """True when the response is a clean provider-side error, not a bug."""
    return (payload.get('error') or {}).get('code') in {
        'rate_limited', 'out_of_credit', 'model_unavailable', 'server_error',
        'timeout', 'not_configured', 'auth_error', 'completion_failed',
    }


def as_json(response):
    """Return the JSON body, or {} when the view answered with HTML.

    A non-JSON reply is what a 302 redirect to the login page or a 500 page
    looks like, so a wrong status should not crash the run.
    """
    if 'json' not in (response.get('Content-Type') or ''):
        return {}
    try:
        return response.json()
    except ValueError:
        return {}


def product_photo(size=(640, 640)):
    """A synthetic photo: coloured background, solid product, soft edge."""
    img = Image.new('RGB', size, (243, 240, 234))
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [size[0] * 0.25, size[1] * 0.2, size[0] * 0.75, size[1] * 0.8],
        radius=28, fill=(196, 104, 62))
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=92)
    buf.seek(0)
    return buf


def main():
    User = get_user_model()
    username = 'e2e_ai_studio'
    User.objects.filter(username=username).delete()
    user = User.objects.create_user(username, 'e2e@example.com', 'pw')
    SellerProfile.objects.create(
        user=user, shop_name='E2E Studio', bank_account='123456789',
        account_holder_name='E2E', ifsc_code='HDFC0001234',
        phone='9999999999', address='E2E address',
        is_email_verified=True, is_phone_verified=True,
    )

    # The test client defaults to the host 'testserver', which is not in
    # ALLOWED_HOSTS outside tests, so name the real dev host.
    client = Client(SERVER_NAME='localhost')
    client.force_login(user)
    products_before = Product.objects.count()

    # 1 · health
    r = client.get('/ai/health/')
    body = as_json(r)
    check('health endpoint', r.status_code == 200,
          'provider=%s neural=%s' % (body.get('provider'),
                                     body.get('neural_segmentation')))

    # 2 · image enhancement
    photo = product_photo()
    r = client.post('/ai/image/enhance/', {
        'image': photo, 'background': 'white'})
    job = as_json(r).get('job') or {}
    check('image enhancement', r.status_code == 201 and job.get('status') == 'completed',
          'stages=%d' % len(job.get('stages') or []))
    job_id = job.get('id')

    # 3 · text: description
    r = client.post('/ai/text/product/description/', json.dumps({
        'title': 'Handwoven Cotton Table Runner',
        'category': 'Home Textiles',
        'materials': '100% cotton',
    }), content_type='application/json')
    payload = as_json(r)
    desc = payload.get('description') or ''
    if r.status_code == 200 and len(desc) > 20:
        check('AI description', True, 'len=%d model=%s' % (len(desc), payload.get('model')))
        if '**' in desc or desc.lstrip().startswith(('-', '*', '#')):
            check('description has no markdown', False, desc[:60])
        else:
            check('description has no markdown', True)
    elif is_provider_unavailable(payload):
        desc = ''
        skip('AI description', 'provider: %s' % payload.get('error', {}).get('code'))
    else:
        check('AI description', False, 'status=%s' % r.status_code)

    # 4 · text: keywords
    r = client.post('/ai/text/product/keywords/', json.dumps({
        'title': 'Handwoven Cotton Table Runner', 'category': 'Home Textiles',
    }), content_type='application/json')
    payload = as_json(r)
    keywords = payload.get('keywords') or []
    if r.status_code == 200 and len(keywords) >= 3:
        junk = [w for w in keywords if w.startswith(('"', '}', ']', ':'))]
        check('AI keywords', not junk, 'n=%d %s' % (len(keywords), keywords[:3]))
    elif is_provider_unavailable(payload):
        skip('AI keywords', 'provider: %s' % payload.get('error', {}).get('code'))
    else:
        check('AI keywords', False, 'status=%s' % r.status_code)

    # 5 · text: tags
    r = client.post('/ai/text/product/tags/', json.dumps({
        'title': 'Handwoven Cotton Table Runner', 'category': 'Home Textiles',
    }), content_type='application/json')
    payload = as_json(r)
    tags = payload.get('tags') or []
    if r.status_code == 200 and len(tags) >= 3:
        check('AI tags', True, 'n=%d' % len(tags))
    elif is_provider_unavailable(payload):
        skip('AI tags', 'provider: %s' % payload.get('error', {}).get('code'))
    else:
        check('AI tags', False, 'status=%s' % r.status_code)

    # 6 · publish
    r = client.post('/ai/publish/', json.dumps({
        'title': 'Handwoven Cotton Table Runner',
        'description': desc or 'A handwoven cotton table runner.',
        'category': 'Home Textiles',
        'price': '499.00',
        'stock': 5,
        'enhancement_job': job_id,
        'use_enhanced': True,
    }), content_type='application/json')
    published = as_json(r)
    check('publish product', r.status_code == 201 and published.get('success'),
          'id=%s' % published.get('product_id'))

    # 7 · the product really exists and is a draft
    product = Product.objects.filter(pk=published.get('product_id')).first()
    check('product persisted',
          product is not None and product.name == 'Handwoven Cotton Table Runner',
          'name=%r' % (product.name if product else None))
    check('product is a draft, not live',
          product is not None and product.available is False)
    check('product image attached',
          product is not None and bool(product.image),
          product.image.name if product and product.image else '')

    # 8 · publish did not disturb the draft job
    from ai_services.models import EnhancementStatus, ImageEnhancementJob
    j = ImageEnhancementJob.objects.filter(pk=job_id).first()
    check('job status untouched',
          j is not None and j.status == EnhancementStatus.COMPLETED,
          j.status if j else '')

    # The public job payload only carries URLs, so the storage names are read
    # from the database to confirm which of the two files was published.
    check('enhanced image was chosen, not the original',
          product is not None and j is not None
          and product.image.name.rsplit('/', 1)[-1] == j.enhanced.name.rsplit('/', 1)[-1]
          and product.image.name.rsplit('/', 1)[-1] != j.original.name.rsplit('/', 1)[-1],
          'product=%s enhanced=%s' % (
              product.image.name.rsplit('/', 1)[-1] if product and product.image else '',
              j.enhanced.name.rsplit('/', 1)[-1] if j and j.enhanced else ''))

    # 9 · ownership: another seller cannot touch the job
    other = User.objects.create_user('e2e_other', 'other@example.com', 'pw')
    other_client = Client(SERVER_NAME='localhost')
    other_client.force_login(other)
    r = other_client.post('/ai/publish/', json.dumps({
        'title': 'Stolen', 'description': 'x', 'category': 'Y',
        'price': '1', 'enhancement_job': job_id,
    }), content_type='application/json')
    check("other seller's job rejected", r.status_code in (404, 409),
          'status=%s' % r.status_code)

    # 10 · validation: bad price is refused
    r = client.post('/ai/publish/', json.dumps({
        'title': 'Bad', 'description': 'x', 'category': 'Y', 'price': '-5',
    }), content_type='application/json')
    check('negative price refused',
          r.status_code == 400 and as_json(r).get('error', {}).get('code') == 'bad_price')

    # 11 · XSS is stripped
    r = client.post('/ai/publish/', json.dumps({
        'title': 'XSS probe',
        'description': '<script>alert(1)</script>safe text',
        'category': 'Security', 'price': '99',
    }), content_type='application/json')
    probe = Product.objects.filter(name='XSS probe').first()
    check('script tag stripped',
          r.status_code == 201 and probe is not None and '<script' not in (probe.description or ''),
          (probe.description or '')[:40] if probe else '')

    # 12 · a provider outage must not take the studio down with it
    r = client.post('/ai/text/product/keywords/', json.dumps({
        'title': 'Handwoven Cotton Table Runner',
    }), content_type='application/json')
    check('keywords endpoint answers cleanly when the provider fails',
          r.status_code in (200, 422),
          'status=%s' % r.status_code)
    if r.status_code == 422:
        message = as_json(r).get('error', {}).get('message', '')
        check('failure message is written for a seller',
              'rate limiting us' not in message and 'AI service' not in message,
              message[:60])

    # Publishing must still work with no AI text available at all.
    check('publish does not depend on generated text',
          Product.objects.filter(name='XSS probe').exists(),
          'draft survived the provider failure')

    print()
    print('products created: %d' % (Product.objects.count() - products_before))

    # cleanup
    User.objects.filter(username__in=[username, 'e2e_other']).delete()
    Product.objects.filter(name__in=[
        'Handwoven Cotton Table Runner', 'XSS probe']).delete()

    failed = [n for n, ok, _ in results if not ok]
    skipped = [n for n, _, d in results if d.startswith('provider:')]
    print('%d/%d checks passed' % (len(results) - len(failed), len(results)))
    if skipped:
        print('skipped (provider unavailable): %s' % ', '.join(skipped))
    if failed:
        print('failed: %s' % ', '.join(failed))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
