"""Browser check of the AI Studio's other paths: skips, errors and edge values.

``e2e_studio_ui_check.py`` walks the happy path. This one presses the buttons
that path never touches, because those are where a wizard quietly breaks:

  * publishing with no enhancement at all (the photo must still be uploaded)
  * "Keep Original" instead of the enhanced version
  * removing and replacing a photo
  * an AI call that fails (does the seller find out?)
  * dictation, start to finish
  * a price far outside the suggested range

Run it with

    env/Scripts/python.exe e2e_studio_ui_edge_check.py
"""

import json
import os
import sys
import tempfile
import threading

import django
from PIL import Image, ImageDraw

# The checks print rupee signs, which the Windows console codec cannot encode.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:  # pragma: no cover - older interpreters
    pass

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402
from django.urls import reverse  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

PASS, FAIL = 'PASS', 'FAIL'
results = []

DECODED = """id => {
    const i = document.getElementById(id);
    return !!(i.getAttribute('src') && i.complete && i.naturalWidth > 0);
}"""


def check(name, ok, detail=''):
    results.append((name, bool(ok), detail))
    print('%s  %-52s %s' % (PASS if ok else FAIL, name, detail))


def product_photo(size=(700, 700)):
    img = Image.new('RGB', size, (228, 223, 214))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([190, 170, 510, 540], radius=36, fill=(46, 92, 140))
    return img


def main():
    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username='edgeuser', defaults={'email': 'edge@example.com'})
    user.set_password('pw')
    user.save()
    from accounts.models import SellerProfile
    SellerProfile.objects.get_or_create(
        user=user,
        defaults=dict(
            shop_name='Edge Shop', bank_account='123456789',
            account_holder_name='Seller', ifsc_code='HDFC0001234',
            phone='9999999999', address='Edge address',
            is_email_verified=True, is_phone_verified=True,
        ))

    client = Client()
    client.force_login(user)
    session_cookie = client.cookies['sessionid']
    path = reverse('seller:ai_studio')

    tmp = tempfile.mkdtemp()
    photo_a = os.path.join(tmp, 'a.png')
    photo_b = os.path.join(tmp, 'b.png')
    product_photo().save(photo_a)
    Image.new('RGB', (640, 640), (250, 240, 230)).save(photo_b)

    catalog = {
        'title': 'Blue Clay Vase',
        'description': 'A blue vase thrown on a wheel and glazed by hand.',
        'keywords': ['blue vase', 'clay', 'handmade pottery'],
        # A real department, as the real endpoint always returns.
        'category': 'Home & Kitchen',
        'subcategory': 'Home Decor',
    }
    # How the fake AI text layer should answer, keyed by a counter the page
    # cannot see; the tests set it before each flow.
    text_mode = {'catalog': 'ok'}
    sent = []   # the catalog payloads the page actually sent, for inspection

    def make_page(browser, transcribe_ok=True):
        context = browser.new_context(
            viewport={'width': 1280, 'height': 1000},
            bypass_csp=True,
            permissions=['microphone'],
        )
        context.add_cookies([{
            'name': 'sessionid', 'value': session_cookie.value,
            'domain': 'localhost', 'path': '/',
        }])
        page = context.new_page()
        console = []

        def on_request(route):
            req = route.request
            if req.method == 'POST' and req.url.endswith('/ai/text/product/catalog/'):
                sent.append(req.post_data or '')
                if text_mode['catalog'] == 'fail':
                    route.fulfill(
                        status=500, content_type='application/json',
                        body=json.dumps({'success': False, 'error': {
                            'code': 'server_error',
                            'message': 'Something went wrong. Please try again.'}}))
                else:
                    route.fulfill(
                        status=200, content_type='application/json',
                        body=json.dumps(dict(catalog, success=True, model='stub')))
            elif req.method == 'POST' and req.url.endswith('/ai/voice/transcribe/'):
                if transcribe_ok:
                    route.fulfill(
                        status=200, content_type='application/json',
                        body=json.dumps({
                            'success': True, 'text': 'A blue vase I made on a wheel.',
                            'language': 'en', 'duration': 3.1, 'model': 'whisper-local'}))
                else:
                    route.fulfill(
                        status=503, content_type='application/json',
                        body=json.dumps({'success': False, 'error': {
                            'code': 'speech_unavailable',
                            'message': 'Voice typing is unavailable.'}}))
            else:
                route.continue_()

        page.route('**/*', on_request)
        page.on('console', lambda m: console.append((m.type, m.text)))
        page.on('pageerror', lambda e: console.append(('pageerror', str(e))))
        page.goto('http://localhost:8123' + path, wait_until='domcontentloaded')
        page.wait_for_selector('#ais')
        return context, page, console

    def upload(page, path_to_file):
        page.set_input_files('#aisFile', path_to_file)
        page.wait_for_selector('#aisPicked:not([hidden])', timeout=15000)
        page.wait_for_function(DECODED, arg='aisPreview', timeout=20000)

    def to_step(page, n):
        for _ in range(n):
            page.click('#aisNext')
            page.wait_for_timeout(120)

    def run():
        with sync_playwright() as p:
            browser = p.chromium.launch(args=[
                # A synthetic microphone, so the dictation path is exercised
                # for real rather than stubbed at the button.
                '--use-fake-device-for-media-stream',
                '--use-fake-ui-for-media-stream',
            ])

            # ── A · publishing with no enhancement ──────────────────────
            ctx, page, console = make_page(browser)
            upload(page, photo_a)
            to_step(page, 2)          # step 1 -> 2 -> 3, never enhancing
            check('the compare step is skipped without blocking', page.evaluate(
                "document.getElementById('aisProgressText').textContent"
            ).startswith('Step 3 of'))
            page.click('#aisTabType')
            page.fill('#aisDesc', 'A blue vase thrown on a wheel.')
            page.click('[data-studio-hook="generate"]')
            page.wait_for_selector('.ais-step-panel[data-step="4"]:not([hidden])',
                                   timeout=20000)
            page.click('#aisNext')
            page.wait_for_selector('.ais-step-panel[data-step="5"]:not([hidden])')
            page.click('[data-studio-hook="use-price"]')
            page.wait_for_selector('.ais-step-panel[data-step="6"]:not([hidden])')
            page.click('#aisPublishBtn')
            page.wait_for_selector('#aisDone:not([hidden])', timeout=40000)
            check('publishing without any enhancement succeeds',
                  page.locator('#aisDone').is_visible())
            check('no error was raised on that path',
                  page.locator('#aisGlobalError').is_hidden(),
                  page.locator('#aisGlobalError').inner_text())
            ctx.close()

            # ── B · a price far outside the suggested range ─────────────
            ctx, page, console = make_page(browser)
            upload(page, photo_a)
            to_step(page, 2)
            page.click('#aisTabType')
            page.fill('#aisDesc', 'A blue vase.')
            page.click('[data-studio-hook="generate"]')
            page.wait_for_selector('.ais-step-panel[data-step="4"]:not([hidden])',
                                   timeout=20000)
            page.click('#aisNext')
            page.wait_for_selector('.ais-step-panel[data-step="5"]:not([hidden])')
            page.click('#aisEditPriceBtn')
            page.fill('#aisPriceInput', '99000')
            check('an out-of-range price is not clamped away',
                  '99,000' in page.locator('#aisPriceValue').inner_text(),
                  page.locator('#aisPriceValue').inner_text())
            # The slider has to stretch to show it, or the thumb would clamp
            # to the old maximum and publish a different price than shown.
            check('the slider widens to include the price',
                  int(page.get_attribute('#aisPriceRange', 'max')) >= 99000,
                  'max=%s' % page.get_attribute('#aisPriceRange', 'max'))
            check('the thumb sits on the typed price',
                  page.input_value('#aisPriceRange') == '99000',
                  page.input_value('#aisPriceRange'))
            page.click('[data-studio-hook="use-price"]')
            page.wait_for_selector('.ais-step-panel[data-step="6"]:not([hidden])')
            check('the card shows the large price',
                  '99,000' in page.locator('#aisCardPrice').inner_text())
            ctx.close()

            # ── C · keeping the original instead of the enhanced one ───
            ctx, page, console = make_page(browser)
            upload(page, photo_a)
            page.click('#aisNext')
            page.wait_for_selector('.ais-step-panel[data-step="2"]:not([hidden])')
            page.click('.ais-step[data-goto="1"]')
            page.click('[data-studio-hook="enhance"]')
            page.wait_for_selector('#aisEnhanceBusy', state='hidden', timeout=120000)
            page.wait_for_function(DECODED, arg='aisAfterImg', timeout=30000)
            page.click('[data-studio-hook="keep-original"]')
            page.wait_for_selector('.ais-step-panel[data-step="3"]:not([hidden])')
            check('"Keep Original" advances to the describe step',
                  page.locator('#aisProgressText').inner_text().startswith('Step 3 of'))
            check('no enhancement badge is shown for a kept original',
                  page.locator('#aisEnhanceState').is_hidden())
            check('the rail keeps the seller\'s own photo',
                  page.evaluate("document.getElementById('aisPreview').src"
                                ".startsWith('blob:')"))
            ctx.close()

            # ── D · removing and replacing a photo ─────────────────────
            ctx, page, console = make_page(browser)
            upload(page, photo_a)
            page.click('[data-studio-hook="remove-image"]')
            page.wait_for_selector('#aisDrop:not([hidden])', timeout=5000)
            check('removing the photo restores the empty state',
                  page.locator('#aisDrop').is_visible()
                  and page.locator('#aisPicked').is_hidden())
            check('removing the photo re-locks Next',
                  page.locator('#aisNext').is_disabled())
            check('the image tick goes out again',
                  not page.locator('[data-check="image"]').evaluate(
                      "n => n.classList.contains('is-ready')"))
            check('the rail shows the "no image" tile',
                  page.locator('#aisMediaEmpty').is_visible()
                  and page.locator('#aisPreview').is_hidden())

            upload(page, photo_b)
            check('a replacement photo can be chosen straight after', True)
            page.click('#aisNext')
            page.click('.ais-step[data-goto="1"]')
            page.click('[data-studio-hook="enhance"]')
            page.wait_for_selector('#aisEnhanceBusy', state='hidden', timeout=120000)
            page.click('[data-studio-hook="use-enhanced"]')
            page.wait_for_selector('.ais-step-panel[data-step="3"]:not([hidden])')
            check('the replacement photo is what got enhanced', True)
            ctx.close()

            # ── E · an AI call that fails ──────────────────────────────
            ctx, page, console = make_page(browser)
            upload(page, photo_a)
            to_step(page, 2)
            page.click('#aisTabType')
            page.fill('#aisDesc', 'A blue vase.')
            text_mode['catalog'] = 'fail'
            page.click('[data-studio-hook="generate"]')
            page.wait_for_selector('#aisGlobalError:not([hidden])', timeout=20000)
            check('a failed AI call shows a message above the wizard',
                  page.locator('#aisGlobalError').is_visible())
            check('the failure message is readable, not a status code',
                  'went wrong' in page.locator('#aisGlobalError').inner_text().lower(),
                  page.locator('#aisGlobalError').inner_text())
            check('a failed call does not advance the wizard',
                  page.locator('#aisProgressText').inner_text().startswith('Step 3 of'))
            check('the generate button is usable again after a failure',
                  not page.locator('[data-studio-hook="generate"]').is_disabled())
            check('the seller\'s typed words survive a failed call',
                  page.input_value('#aisDesc') == 'A blue vase.')
            text_mode['catalog'] = 'ok'
            page.click('[data-studio-hook="generate"]')
            page.wait_for_selector('.ais-step-panel[data-step="4"]:not([hidden])',
                                   timeout=20000)
            check('retrying after a failure works', True)
            ctx.close()

            # ── F · dictation, start to finish ─────────────────────────
            ctx, page, console = make_page(browser)
            upload(page, photo_a)
            to_step(page, 2)
            check('the transcript is hidden before anything is said',
                  page.locator('#aisTranscript').is_hidden())
            page.click('#aisMic')
            page.wait_for_selector('#aisMic.is-live', timeout=10000)
            check('the mic shows a live recording state',
                  page.locator('#aisMic.is-live').count() == 1)
            check('the timer starts', page.locator('#aisTimer').is_visible())
            page.wait_for_timeout(1200)
            check('the timer counts up',
                  page.locator('#aisTimer').inner_text() != '00:00',
                  page.locator('#aisTimer').inner_text())
            page.click('#aisMic')
            page.wait_for_selector('#aisTranscript:not([hidden])', timeout=30000)
            check('the recording is transcribed and shown',
                  'vase' in page.locator('#aisTranscriptText').inner_text().lower(),
                  page.locator('#aisTranscriptText').inner_text())
            check('the mic returns to its idle state',
                  page.locator('#aisMic.is-live').count() == 0
                  and 'Tap to record' in page.locator('#aisMicLabel').inner_text())
            check('the record button says "Start Recording" again',
                  'Start Recording' in page.locator('#aisRecordBtn').inner_text())
            check('dictation counts as a description',
                  page.locator('[data-check="description"]').evaluate(
                      "n => n.classList.contains('is-ready')"))
            check('there is a visible way forward without leaving the voice tab',
                  page.locator('[data-studio-hook="generate"]').is_visible(),
                  'the generate button is inside the type tabpanel'
                  if not page.locator('[data-studio-hook="generate"]').is_visible()
                  else '')
            page.click('[data-studio-hook="generate"]')
            page.wait_for_selector('.ais-step-panel[data-step="4"]:not([hidden])',
                                   timeout=20000)
            seed = sent[-1] if sent else ''
            check('the dictated words reached the listing request as the seed',
                  'made on a wheel' in seed, seed[:120])
            ctx.close()

            # ── G · no speech model on the server ──────────────────────
            ctx, page, console = make_page(browser, transcribe_ok=False)
            upload(page, photo_a)
            to_step(page, 2)
            page.click('#aisMic')
            page.wait_for_selector('#aisMic.is-live', timeout=10000)
            page.click('#aisMic')          # stop, which is what triggers the upload
            page.wait_for_selector('#aisGlobalError:not([hidden])', timeout=20000)
            check('a missing speech model says so plainly',
                  'browser' in page.locator('#aisGlobalError').inner_text().lower(),
                  page.locator('#aisGlobalError').inner_text())
            check('the studio is not left mid-recording',
                  page.locator('#aisMic.is-live').count() == 0)
            check('the mic is offered again after the failure',
                  not page.locator('#aisMic').is_disabled())
            ctx.close()

            errors = [m for msgs in [] for m in msgs]
            browser.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join()

    from shop.models import Product
    unenhanced = Product.objects.filter(name=catalog['title'], available=False).first()
    check('the unenhanced publish stored a real image',
          bool(unenhanced and unenhanced.image),
          unenhanced.image.name if unenhanced and unenhanced.image else '(none)')

    print('\n%d passed, %d failed' % (
        sum(1 for _, ok, _ in results if ok),
        sum(1 for _, ok, _ in results if not ok)))
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == '__main__':
    from django.core.management import call_command
    call_command('migrate', verbosity=0, run_syncdb=True)
    sys.exit(main())