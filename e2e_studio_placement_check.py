"""Browser check for the placement pickers and the dictation guidance.

Two things that used to be quietly wrong and that no screenshot would catch:

  * the category and subcategory lists were hardcoded in the template, so they
    listed departments the shop does not have (and publishing one invented a
    new Category row);
  * the voice panel gave no guidance about when to start or what to do next,
    so a failed recording read as an unresponsive page.

    env/Scripts/python.exe e2e_studio_placement_check.py
"""

import json
import os
import sys
import tempfile
import threading

import django
from PIL import Image

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from playwright.sync_api import sync_playwright

from shop.models import Category, Product, SubCategory

PASS, FAIL = 'PASS', 'FAIL'
results = []


def check(name, ok, detail=''):
    results.append((name, bool(ok), detail))
    print('%s  %-54s %s' % (PASS if ok else FAIL, name, detail))


def main():
    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username='placeuser', defaults={'email': 'place@example.com'})
    user.set_password('pw')
    user.save()
    from accounts.models import SellerProfile
    SellerProfile.objects.get_or_create(
        user=user,
        defaults=dict(shop_name='Place Shop', bank_account='123456789',
                      account_holder_name='Seller', ifsc_code='HDFC0001234',
                      phone='9999999999', address='Place address',
                      is_email_verified=True, is_phone_verified=True))

    client = Client()
    client.force_login(user)
    session_cookie = client.cookies['sessionid']
    path = reverse('seller:ai_studio')

    tmp = tempfile.mkdtemp()
    photo = os.path.join(tmp, 'p.png')
    Image.new('RGB', (400, 400), (60, 90, 150)).save(photo)

    real_categories = [c.name for c in Category.objects.all()]
    real_subs = list(
        SubCategory.objects.values_list('name', 'category__name'))

    # Computed here, not inside the Playwright callback: the ORM refuses to
    # run there, and a figure this check compares against has to come from the
    # database anyway.
    beauty = [name for name, cat in real_subs if cat == 'Beauty']
    kitchen = [name for name, cat in real_subs if cat == 'Home & Kitchen']
    live_beauty = list(
        Product.objects.filter(category__name='Beauty', available=True)
        .values_list('price', flat=True))
    beauty_average = int(round(
        sum(float(p) for p in live_beauty) / len(live_beauty)))

    catalog = {'title': 'Brass Diya Set', 'description': 'A set of five brass diyas.',
               'keywords': ['brass diya', 'oil lamp'],
               'category': 'Home & Kitchen', 'subcategory': 'Home Decor'}

    def run():
        with sync_playwright() as p:
            browser = p.chromium.launch(args=[
                '--use-fake-device-for-media-stream',
                '--use-fake-ui-for-media-stream',
            ])
            ctx = browser.new_context(bypass_csp=True, permissions=['microphone'],
                                      viewport={'width': 1280, 'height': 1100})
            ctx.add_cookies([{'name': 'sessionid', 'value': session_cookie.value,
                              'domain': 'localhost', 'path': '/'}])
            page = ctx.new_page()
            errors = []
            page.on('console', lambda m: errors.append((m.type, m.text)))
            page.on('pageerror', lambda e: errors.append(('pageerror', str(e))))

            sent = []

            def on_request(route):
                req = route.request
                if req.method == 'POST' and req.url.endswith('/ai/text/product/catalog/'):
                    sent.append(req.post_data or '')
                    route.fulfill(status=200, content_type='application/json',
                                  body=json.dumps(dict(catalog, success=True,
                                                       model='stub')))
                elif req.method == 'POST' and req.url.endswith('/ai/voice/transcribe/'):
                    route.fulfill(status=422, content_type='application/json',
                                  body=json.dumps({'success': False, 'error': {
                                      'code': 'no_speech',
                                      'message': 'No speech was detected in that recording.'}}))
                else:
                    route.continue_()

            page.route('**/*', on_request)
            page.goto('http://localhost:8123' + path, wait_until='domcontentloaded')
            page.wait_for_selector('#ais')

            # ── 1 · the pickers show the shop's real departments ──────
            page.set_input_files('#aisFile', photo)
            page.wait_for_selector('#aisPicked:not([hidden])')
            page.click('#aisNext')
            page.click('#aisNext')   # step 2 needs no enhancement to be left
            page.wait_for_selector('.ais-step-panel[data-step="3"]:not([hidden])')

            # ── 2 · the dictation guidance, before anything is typed ──
            page.click('#aisTabVoice')
            page.wait_for_timeout(150)
            steps = page.eval_on_selector_all(
                '.ais-guide-step', 'os => os.map(o => o.dataset.guide)')
            check('the voice panel lists what to do, in order',
                  steps == ['start', 'speak', 'stop', 'generate'], ', '.join(steps))
            idle = page.inner_text('#aisMicStatus')
            check('the panel says what is about to happen',
                  'tap the mic' in idle.lower(), idle)
            check('exactly one step is highlighted at rest',
                  page.eval_on_selector_all(
                      '.ais-guide-step.is-next', 'os => os.length') == 1,
                  '%d highlighted' % page.eval_on_selector_all(
                      '.ais-guide-step.is-next', 'os => os.length'))
            check('and it is the one to press first',
                  page.eval_on_selector_all(
                      '.ais-guide-step.is-next', 'os => os[0].dataset.guide')
                  == 'start')

            page.click('#aisMic')
            page.wait_for_selector('#aisMic.is-live', timeout=15000)
            recording_note = page.inner_text('#aisMicStatus')
            check('the status explains what is happening while recording',
                  'speak' in recording_note.lower(), recording_note)
            check('the start steps tick off once recording',
                  page.eval_on_selector_all(
                      '.ais-guide-step.is-done', 'os => os.length') >= 1)
            check('while recording the guide points at the tap that stops it',
                  page.eval_on_selector_all(
                      '.ais-guide-step.is-next', 'os => os[0].dataset.guide')
                  == 'stop')

            page.click('#aisMic')
            # The stubbed 422 comes back at once; give the upload handler time
            # to put the advice in place rather than sleeping a fixed guess.
            page.wait_for_function(
                "() => document.getElementById('aisMicStatus')"
                ".textContent.toLowerCase().includes('words')", timeout=15000)
            silence = page.inner_text('#aisMicStatus')
            check('a silent recording is explained, not just reported',
                  'hear any words' in silence, silence)
            check('a silent recording says what to do next',
                  'again' in silence.lower() and 'speak' in silence.lower(), silence)
            check('the guide offers to start over',
                  page.eval_on_selector_all(
                      '.ais-guide-step.is-next', 'os => os[0].dataset.guide')
                  == 'start',
                  page.eval_on_selector_all(
                      '.ais-guide-step.is-next', 'os => os[0].dataset.guide'))

            # Having heard nothing back, the seller types instead.
            page.click('#aisTabType')
            page.fill('#aisDesc', 'A set of five brass diyas that I polish by hand.')
            page.click('[data-studio-hook="generate"]')
            page.wait_for_selector('.ais-step-panel[data-step="4"]:not([hidden])',
                                   timeout=20000)

            shown = page.eval_on_selector_all(
                '#aisCategory option', 'os => os.map(o => o.value)')
            check('the category list is the shop\'s own departments',
                  set(shown) == set(real_categories),
                  '%d shown vs %d in the database' % (len(shown), len(real_categories)))
            check('no department appears that the shop does not have',
                  not (set(shown) - set(real_categories)),
                  ', '.join(sorted(set(shown) - set(real_categories))[:3]))

            # ── 3 · the AI placed it and the picks followed ───────────
            check('the AI\'s category was selected',
                  page.input_value('#aisCategory') == 'Home & Kitchen',
                  page.input_value('#aisCategory'))
            subs = page.eval_on_selector_all(
                '#aisSubcategory option', 'os => os.map(o => o.value)')
            check('the subcategory list is that department\'s own',
                  set(s for s in subs if s) == set(kitchen),
                  '%d subs' % len([s for s in subs if s]))
            check('the AI\'s subcategory was selected',
                  page.input_value('#aisSubcategory') == 'Home Decor',
                  page.input_value('#aisSubcategory'))

            # ── 4 · changing category re-scopes the subcategory ──────
            page.select_option('#aisCategory', 'Beauty')
            page.wait_for_timeout(150)
            after = page.eval_on_selector_all(
                '#aisSubcategory option', 'os => os.map(o => o.value)')
            check('choosing another department re-fills the subcategory list',
                  set(s for s in after if s) == set(beauty),
                  ', '.join(s for s in after if s)[:60])
            check('the subcategory from the previous department is gone',
                  'Home Decor' not in after)

            # ── 5 · the price follows the real catalogue ──────────────
            page.click('#aisNext')
            page.wait_for_selector('.ais-step-panel[data-step="5"]:not([hidden])')
            shown_price = page.inner_text('#aisPriceValue').replace(
                '₹', '').replace(',', '').strip()
            check('the suggested price is this shop\'s average for Beauty',
                  shown_price == str(beauty_average),
                  'shown %s vs catalogue average %s' % (shown_price, beauty_average))
            basis = page.inner_text('#aisPriceBasis')
            check('the seller is told where the price came from',
                  'average' in basis and 'Beauty' in basis, basis)

            # ── 6 · a department with nothing listed yet ──────────────
            page.click('.ais-step[data-goto="4"]')
            page.wait_for_selector('.ais-step-panel[data-step="4"]:not([hidden])')
            page.select_option('#aisCategory', 'Security')
            page.wait_for_timeout(150)
            security_subs = [name for name, cat in real_subs if cat == 'Security']
            now_subs = page.eval_on_selector_all(
                '#aisSubcategory option', 'os => os.map(o => o.value)')
            check('an unstocked department still offers its subcategories',
                  set(s for s in now_subs if s) == set(security_subs),
                  '%d subs' % len([s for s in now_subs if s]))
            page.click('#aisNext')
            page.wait_for_selector('.ais-step-panel[data-step="5"]:not([hidden])')
            empty_basis = page.inner_text('#aisPriceBasis')
            check('a department with nothing listed says so',
                  'nothing is listed' in empty_basis, empty_basis)

            # ── 7 · publishing an invented department is refused ──────
            page.click('#aisUsePriceBtn')
            page.wait_for_selector('.ais-step-panel[data-step="6"]:not([hidden])')
            refused = page.evaluate("""async () => {
                const body = {
                    title: 'Snake Oil Listing', description: 'Something.',
                    category: 'Home Decor', subcategory: '',
                    price: '999', stock: '1'
                };
                const csrf = document.querySelector(
                    '[name=csrfmiddlewaretoken]').value;
                const res = await fetch('/ai/publish/', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json',
                              'X-CSRFToken': csrf},
                    body: JSON.stringify(body),
                });
                return {status: res.status, body: await res.json()};
            }""")
            check('publishing a category the shop does not have is refused',
                  refused['status'] == 400
                  and refused['body'].get('error', {}).get('code') == 'unknown_category',
                  '%s %s' % (refused['status'], refused['body'].get('error')))

            mismatched = page.evaluate("""async () => {
                const body = {
                    title: 'Mismatched Sub', description: 'Something.',
                    category: 'Security', subcategory: 'Madhubani Art',
                    price: '999', stock: '1'
                };
                const csrf = document.querySelector(
                    '[name=csrfmiddlewaretoken]').value;
                const res = await fetch('/ai/publish/', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json',
                              'X-CSRFToken': csrf},
                    body: JSON.stringify(body),
                });
                return {status: res.status, body: await res.json()};
            }""")
            check('a subcategory from another department is refused',
                  mismatched['status'] == 400
                  and mismatched['body'].get('error', {}).get('code') == 'unknown_subcategory',
                  '%s %s' % (mismatched['status'], mismatched['body'].get('error')))

            ok_publish = page.evaluate("""async () => {
                const body = {
                    title: 'Properly Placed Listing', description: 'A listing.',
                    category: 'Home & Kitchen', subcategory: 'Home Decor',
                    price: '1200', stock: '2'
                };
                const csrf = document.querySelector(
                    '[name=csrfmiddlewaretoken]').value;
                const res = await fetch('/ai/publish/', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json',
                              'X-CSRFToken': csrf},
                    body: JSON.stringify(body),
                });
                return {status: res.status, body: await res.json()};
            }""")
            check('a real category and subcategory publish normally',
                  ok_publish['status'] == 201, str(ok_publish['status']))

            # browser logs every non-2xx fetch. Those are expected; anything
            # else is not.
            unexpected = [
                text for kind, text in errors
                if kind in ('error', 'pageerror')
                and 'Failed to load resource' not in text
            ]
            check('no unexpected console errors', not unexpected,
                  '; '.join(unexpected[:3]))
            # Three deliberate non-2xx answers: the two refused publishes and
            # the silent recording. Anything else that fails would be a bug.
            resource = [t for _, t in errors if 'Failed to load resource' in t]
            expected_failures = sum(1 for t in resource
                                    if '400' in t or '422' in t)
            check('the only failed requests were the ones this test asked for',
                  len(resource) == expected_failures == 3,
                  '%d failed: %s' % (len(resource), '; '.join(resource)))

            page.screenshot(path='studio_placement.png', full_page=True)
            browser.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join()

    product = Product.objects.filter(name='Properly Placed Listing').first()
    check('the published product carries the real category',
          bool(product and product.category.name == 'Home & Kitchen'),
          product.category.name if product else '(no product)')
    check('and the real subcategory',
          bool(product and product.subcategory
               and product.subcategory.name == 'Home Decor'),
          product.subcategory.name if product and product.subcategory else '(none)')
    check('the refused listings created nothing',
          not Product.objects.filter(name__in=['Snake Oil Listing',
                                               'Mismatched Sub']).exists())
    check('a refused category did not invent a department',
          not Category.objects.filter(name='Home Decor').exists(),
          'Home Decor is a subcategory of Fashion, not a category')

    print('\n%d passed, %d failed' % (
        sum(1 for _, ok, _ in results if ok),
        sum(1 for _, ok, _ in results if not ok)))
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == '__main__':
    sys.exit(main())
