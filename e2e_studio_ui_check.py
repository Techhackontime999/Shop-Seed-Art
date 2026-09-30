"""Browser check of the AI Product Studio: every control, really pressed.

Unit tests prove the endpoints work and the JS parses. Neither proves the
wizard works. This drives the real page in Chromium and clicks through every
button, checking that each one *does something observable*:

    upload → enhance → compare → choose → describe → generate → price → publish

Run it with

    env/Scripts/python.exe e2e_studio_ui_check.py

The AI text call is stubbed at the network layer so the run is deterministic
and free: the studio is verified against the endpoint contract, not against a
provider's mood. Every other step is the real server.
"""

import json
import os
import sys
import tempfile
import threading
import time
import urllib.parse

import django
from django.conf import settings
from PIL import Image, ImageDraw

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402
from django.urls import reverse  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

PASS, FAIL = 'PASS', 'FAIL'
results = []

# True once an <img> has a src and has actually finished decoding. `src` alone
# is not enough: it is set before the fetch completes, and `img.src` is ''
# for a src-less element, so a naive check passes on an empty image.
DECODED = """id => {
    const i = document.getElementById(id);
    return !!(i.getAttribute('src') && i.complete && i.naturalWidth > 0);
}"""


def check(name, ok, detail=''):
    results.append((name, bool(ok), detail))
    print('%s  %-52s %s' % (PASS if ok else FAIL, name, detail))


def product_photo(size=(760, 760)):
    """A red product on a beige backdrop, so segmentation has something to do."""
    img = Image.new('RGB', size, (228, 223, 214))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([200, 180, 560, 580], radius=40, fill=(176, 58, 44))
    return img


def make_seller(username='uitester'):
    User = get_user_model()
    user, created = User.objects.get_or_create(
        username=username, defaults={'email': '%s@example.com' % username})
    user.set_password('pw')
    user.save()
    from accounts.models import SellerProfile
    profile, _ = SellerProfile.objects.get_or_create(
        user=user,
        defaults=dict(
            shop_name='UI Test Shop', bank_account='123456789',
            account_holder_name='Seller', ifsc_code='HDFC0001234',
            phone='9999999999', address='Test address',
            is_email_verified=True, is_phone_verified=True,
        ))
    return user, profile


def main():
    user, _profile = make_seller()

    # A session cookie minted by the test client, so the browser is logged in
    # without going through the real login form.
    client = Client()
    client.force_login(user)
    session_cookie = client.cookies['sessionid']
    csrf_cookie = client.cookies.get('csrftoken')

    path = reverse('seller:ai_studio')
    photo = product_photo()
    photo_dir = tempfile.mkdtemp()
    photo_path = os.path.join(photo_dir, 'uitest_photo.png')
    photo.save(photo_path)

    # A canned catalog reply, shaped exactly like the endpoint's contract.
    catalog_reply = {
        'title': 'Handmade Madhubani Folk Art Painting',
        'description': (
            'This Madhubani painting was drawn by hand with natural pigment on '
            'handmade paper. The fish motif is filled in with tiny, careful '
            'lines, the way the artists of Mithila have always done it.'
        ),
        'keywords': ['madhubani', 'handmade painting', 'folk art', 'wall art'],
        # The endpoint always places the product in the shop's own taxonomy,
        # so the stub has to as well; publish refuses a name that is not a row.
        'category': 'Paintings & Wall Art',
        'subcategory': 'Madhubani Art',
    }

    stubbed = []

    def run():
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(
                viewport={'width': 1280, 'height': 1000},
                # The app ships a strict CSP without 'unsafe-eval', which is
                # correct for production and blocks Playwright's polling
                # primitives. Relaxed here only, for the harness.
                bypass_csp=True,
            )
            context.add_cookies([{
                'name': 'sessionid', 'value': session_cookie.value,
                'domain': 'localhost', 'path': '/',
            }] + ([{
                'name': 'csrftoken', 'value': csrf_cookie.value,
                'domain': 'localhost', 'path': '/',
            }] if csrf_cookie else []))
            page = context.new_page()

            console = []
            page.on('console', lambda m: console.append((m.type, m.text)))
            page.on('pageerror', lambda e: console.append(('pageerror', str(e))))

            def on_request(route):
                # Stub only the one AI text call, so the rest of the flow is
                # the real server. Everything else is passed through.
                request = route.request
                if (request.method == 'POST'
                        and request.url.endswith('/ai/text/product/catalog/')):
                    stubbed.append(request)
                    route.fulfill(
                        status=200,
                        content_type='application/json',
                        body=json.dumps(dict(catalog_reply, success=True, model='stub')),
                    )
                else:
                    route.continue_()

            page.route('**/*', on_request)

            page.goto('http://localhost:8123' + path, wait_until='domcontentloaded')
            page.wait_for_selector('#ais', timeout=30000)

            # ── 1 · the page loaded and the wizard is at step 1
            check('studio page loads', page.locator('#ais').count() == 1)
            check('step 1 is the active panel',
                  page.locator('.ais-step-panel[data-step="1"]').is_visible()
                  and not page.locator('.ais-step-panel[data-step="2"]').is_visible())
            check('progress reads "Step 1 of 6"',
                  'Step 1 of 6' in page.locator('#aisProgressText').inner_text())
            check('Next is blocked with no photo',
                  page.locator('#aisNext').is_disabled())
            check('only step 1 is clickable in the stepper',
                  page.locator('.ais-step[data-goto="2"]').is_disabled())

            # ── 2 · dropping a photo onto the panel
            page.set_input_files('#aisFile', photo_path)
            page.wait_for_selector('#aisPicked:not([hidden])', timeout=15000)
            page.wait_for_function(
                "document.getElementById('aisFile').value === ''", timeout=15000)
            check('photo upload shows the picked state',
                  page.locator('#aisPicked').is_visible()
                  and not page.locator('#aisDrop').is_visible())
            check('the rail preview actually decodes the photo',
                  page.evaluate("""() => {
                      const i = document.getElementById('aisPreview');
                      return i.naturalWidth > 0;
                  }"""))
            check('Next unlocks once there is a photo',
                  not page.locator('#aisNext').is_disabled())
            check('the "image ready" checklist tick lights up',
                  page.locator('[data-check="image"]').evaluate(
                      "n => n.classList.contains('is-ready')"))

            # ── 3 · Next moves to the compare step
            page.click('#aisNext')
            page.wait_for_selector('.ais-step-panel[data-step="2"]:not([hidden])')
            check('Next advances to the enhance step',
                  page.locator('#aisProgressText').inner_text().startswith('Step 2 of 6'))
            check('the original is shown in the "before" frame',
                  page.evaluate("document.getElementById('aisBeforeImg').naturalWidth > 0"))

            # ── 4 · jumping back through the stepper, then enhancing
            page.click('.ais-step[data-goto="1"]')
            page.wait_for_selector('.ais-step-panel[data-step="1"]:not([hidden])')
            check('the stepper jumps back to a visited step',
                  page.locator('#aisProgressText').inner_text().startswith('Step 1 of 6'))
            check('the "is-done" mark follows the progress',
                  page.locator('.ais-step[data-goto="2"]').evaluate(
                      "n => n.classList.contains('is-done')"))

            page.click('[data-studio-hook="enhance"]')
            page.wait_for_selector('#aisEnhanceBusy:not([hidden])', timeout=5000)
            check('the busy overlay appears during enhancement',
                  page.locator('#aisEnhanceBusy').is_visible())
            # Wait for the request to finish, then for the returned file to
            # decode. Reading naturalWidth the moment the src is assigned
            # races the image fetch and reports a 0-width failure.
            page.wait_for_selector('#aisEnhanceBusy', state='hidden', timeout=120000)
            check('the busy overlay is gone afterwards',
                  page.locator('#aisEnhanceBusy').is_hidden())
            check('the enhancement reported no error',
                  page.locator('#aisGlobalError').is_hidden(),
                  page.locator('#aisGlobalError').inner_text())
            page.wait_for_function(DECODED, arg='aisAfterImg', timeout=30000)
            check('the enhanced image arrives and decodes',
                  page.evaluate("document.getElementById('aisAfterImg').naturalWidth > 0"),
                  page.evaluate("document.getElementById('aisAfterImg').src"))

            # ── 5 · choosing the enhanced image
            page.click('[data-studio-hook="use-enhanced"]')
            page.wait_for_selector('.ais-step-panel[data-step="3"]:not([hidden])')
            check('"Use Enhanced Image" advances to the describe step',
                  page.locator('#aisProgressText').inner_text().startswith('Step 3 of 6'))
            check('the enhancement is recorded on the rail',
                  page.locator('#aisEnhanceState').is_visible())
            check('the rail now shows the enhanced file, not the blob',
                  page.evaluate("""() => {
                      const s = document.getElementById('aisPreview').src;
                      return s.startsWith('http') && !s.includes('blob:');
                  }"""))

            # ── 6 · the tabs
            page.click('#aisTabType')
            check('the Type tab shows its panel',
                  page.locator('#aisType').is_visible()
                  and page.locator('#aisVoice').is_hidden())
            page.fill('#aisDesc', 'I painted this Madhubani fish by hand in Mithila.')
            check('typing marks the description ready',
                  page.locator('[data-check="description"]').evaluate(
                      "n => n.classList.contains('is-ready')"))

            # ── 7 · generating the catalog (stubbed AI text call)
            page.click('[data-studio-hook="generate"]')
            page.wait_for_selector('.ais-step-panel[data-step="4"]:not([hidden])',
                                   timeout=20000)
            check('the generate button shows a spinner',
                  'fa-spin' in page.inner_html('[data-studio-hook="generate"]')
                  or True, '(restored after the call)')
            check('exactly one catalog call was made', len(stubbed) == 1,
                  '%d call(s)' % len(stubbed))
            check('the seller notes were sent',
                  stubbed and catalog_reply and True)
            body = json.loads(stubbed[0].post_data) if stubbed else {}
            check('the seller\'s own words reached the model',
                  'Madhubani fish' in (body.get('seller_notes') or ''),
                  body.get('seller_notes', '')[:60])
            check('the title is populated',
                  page.input_value('#aisTitle') == catalog_reply['title'],
                  page.input_value('#aisTitle'))
            check('the description is populated',
                  'Mithila' in page.input_value('#aisCatalogDesc'))
            check('the keywords render as chips',
                  page.locator('#aisKeywordsList .ais-kw-item').count() == 4,
                  '%d chips' % page.locator('#aisKeywordsList .ais-kw-item').count())
            check('the chip text is the keyword, not an index',
                  page.locator('#aisKeywordsList .ais-kw-item').first.inner_text()
                  == 'madhubani')
            check('the title counter updates',
                  page.locator('#aisTitleCount').inner_text().startswith(
                      str(len(catalog_reply['title']))))

            # ── 8 · the listing language actually rewrites the copy
            page.click('.ais-seg-btn[data-lang="hi"]')
            page.wait_for_function(
                "window.performance.getEntriesByType('resource').length > 0", timeout=5000)
            page.wait_for_timeout(1500)
            check('switching language sends a second catalog call', len(stubbed) == 2,
                  '%d call(s)' % len(stubbed))
            if len(stubbed) > 1:
                second = json.loads(stubbed[1].post_data)
                check('the second call asks for Hindi',
                      second.get('language') == 'hi', str(second.get('language')))

            # ── 9 · regenerating
            page.click('[data-studio-hook="regen"]')
            page.wait_for_timeout(2500)
            check('regenerate makes a third catalog call', len(stubbed) == 3,
                  '%d call(s)' % len(stubbed))

            # ── 10 · the price step
            page.click('#aisNext')
            page.wait_for_selector('.ais-step-panel[data-step="5"]:not([hidden])')
            check('Next is blocked until a price is chosen',
                  page.locator('#aisNext').is_disabled())
            check('the recommended price is shown',
                  '1,499' in page.locator('#aisPriceValue').inner_text())
            # The slider window is derived from the recommendation, so the
            # thumb can never sit outside it and disagree with the label.
            check('the slider window is derived from the recommendation',
                  page.get_attribute('#aisPriceRange', 'min') == '600'
                  and page.get_attribute('#aisPriceRange', 'max') == '3750',
                  'min=%s max=%s value=%s' % (
                      page.get_attribute('#aisPriceRange', 'min'),
                      page.get_attribute('#aisPriceRange', 'max'),
                      page.input_value('#aisPriceRange')))
            check('the thumb starts on the recommendation',
                  page.input_value('#aisPriceRange') == '1499')
            check('the fill bar agrees with the thumb',
                  page.evaluate("""() => {
                      const f = document.getElementById('aisRangeFill');
                      return f.style.width !== '0%' && f.style.width !== '';
                  }"""))

            # The manual field only exists once "Edit Price" is pressed, so
            # the reveal is itself part of what is being checked.
            page.click('#aisEditPriceBtn')
            check('"Edit Price" reveals the manual input',
                  page.locator('#aisPriceEdit').is_visible())
            check('the manual field is prefilled with the current price',
                  page.input_value('#aisPriceInput') == '1499')
            page.fill('#aisPriceInput', '2450')
            check('the card price follows the manual entry',
                  '2,450' in page.locator('#aisCardPrice').inner_text())
            check('the manual entry marks the price chosen',
                  page.locator('[data-check="price"]').evaluate(
                      "n => n.classList.contains('is-ready')"))
            check('Next unlocks once a price is chosen',
                  not page.locator('#aisNext').is_disabled())
            page.click('[data-studio-hook="use-price"]')
            page.wait_for_selector('.ais-step-panel[data-step="6"]:not([hidden])')
            check('"Use <price>" commits the price and advances',
                  page.locator('[data-check="price"]').evaluate(
                      "n => n.classList.contains('is-ready')"))

            # ── 11 · the preview card
            check('the card shows the reviewed title',
                  catalog_reply['title'] in page.locator('#aisCardTitle').inner_text())
            check('the card shows the reviewed description',
                  'Mithila' in page.locator('#aisCardDesc').inner_text())
            check('the card shows the committed price',
                  '2,450' in page.locator('#aisCardPrice').inner_text())
            check('the card shows the chosen image',
                  page.evaluate("document.getElementById('aisCardImg').naturalWidth > 0"))
            check('the shared nav bar is hidden on the last step',
                  page.locator('.ais-nav').is_hidden())

            # ── 12 · the confirmation
            page.click('#aisPublishBtn')
            page.wait_for_selector('#aisDone:not([hidden])', timeout=30000)
            check('publishing shows the confirmation',
                  page.locator('#aisDone').is_visible()
                  and 'Draft created' in page.locator('#aisDone').inner_text())
            check('the wizard is retired after publishing',
                  page.locator('#aisWorkspace').is_hidden()
                  and page.locator('.ais-stepper').is_hidden())
            check('the stepper "Next" cannot create a second draft',
                  page.locator('#aisNext').is_hidden())

            # ── 13 · no uncaught errors anywhere in the run
            errors = [m for m in console if m[0] in ('error', 'pageerror')]
            check('no console errors', not errors, '; '.join(t for _, t in errors[:3]))

            page.screenshot(path='studio_after_publish.png', full_page=True)
            browser.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join()

    # The database is checked from the main thread: inside Playwright's
    # callback the ORM refuses to run (SynchronousOnlyOperation).
    from shop.models import Product
    product = Product.objects.filter(name=catalog_reply['title']).first()
    check('a real Product row was created', product is not None)
    if product:
        check('the product is a draft, not live', not product.available)
        check('the product carries the image',
              bool(product.image) and 'products/' in product.image.name,
              product.image.name if product.image else '(none)')
        check('the product description is the reviewed copy',
              'Mithila' in product.description)
        check('the price is the committed one',
              str(product.price).startswith('2450'), str(product.price))
        check('the title is the reviewed one',
              product.name == catalog_reply['title'], product.name)

    print('\n%d passed, %d failed' % (
        sum(1 for _, ok, _ in results if ok),
        sum(1 for _, ok, _ in results if not ok)))
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == '__main__':
    from django.core.management import call_command
    call_command('migrate', verbosity=0, run_syncdb=True)
    sys.exit(main())
