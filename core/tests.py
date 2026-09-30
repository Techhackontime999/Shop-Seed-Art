from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client, SimpleTestCase, TestCase
from django.core.files.uploadedfile import SimpleUploadedFile

from core.sanitizers import sanitize_html
from core.templatetags.core_security import richtext
from core.validators import (
    MAX_UPLOAD_BYTES,
    validate_document_file,
    validate_image_file,
)
from core.views import healthz


class SanitizerTests(SimpleTestCase):
    """Stored-XSS payloads must be stripped by sanitize_html/|richtext."""

    def test_strips_script_tags(self):
        html = '<p>Hello <script>alert(1)</script></p>'
        out = sanitize_html(html)
        self.assertNotIn('<script', out)
        self.assertNotIn('</script>', out)
        # Text content survives as inert text; the tag itself is removed.
        self.assertIn('alert(1)', out)

    def test_strips_event_handlers(self):
        html = '<img src="x" onerror="alert(1)"><p onmouseover="evil()">hi</p>'
        out = sanitize_html(html)
        self.assertNotIn('onerror', out)
        self.assertNotIn('onmouseover', out)

    def test_strips_javascript_urls(self):
        html = '<a href="javascript:alert(1)">click</a>'
        out = sanitize_html(html)
        self.assertNotIn('javascript:', out)

    def test_strips_iframes_objects_embeds(self):
        html = (
            '<iframe src="https://evil.example"></iframe>'
            '<object data="x"></object>'
            '<embed src="y">'
        )
        out = sanitize_html(html)
        self.assertNotIn('iframe', out)
        self.assertNotIn('object', out)
        self.assertNotIn('embed', out)

    def test_strips_style_blocks(self):
        html = '<style>body{display:none}</style><p>ok</p>'
        out = sanitize_html(html)
        self.assertNotIn('style', out)
        self.assertIn('ok', out)

    def test_keeps_safe_richtext(self):
        html = '<h2>Title</h2><p>Some <strong>bold</strong> text with <a href="https://example.com" rel="noopener">a link</a>.</p>'
        out = sanitize_html(html)
        self.assertIn('<h2>', out)
        self.assertIn('<strong>bold</strong>', out)
        self.assertIn('<a href="https://example.com"', out)

    def test_strips_comments(self):
        html = '<p>ok</p><!-- stealtoken -->'
        self.assertNotIn('stealtoken', sanitize_html(html))

    def test_none_and_empty(self):
        self.assertIsNone(sanitize_html(None))
        self.assertEqual(sanitize_html(''), '')


class HealthzTests(TestCase):
    def test_healthz_reports_ok(self):
        response = Client().get('/healthz')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        self.assertEqual(response.json()['checks']['database'], 'ok')

    def test_healthz_resolves_to_core_view(self):
        from django.urls import resolve
        match = resolve('/healthz')
        self.assertEqual(match.func, healthz)


class SecurityHeadersTests(TestCase):
    def test_security_headers_present(self):
        response = Client().get('/robots.txt')
        csp = response['Content-Security-Policy']
        self.assertIn("object-src 'none'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("default-src 'self'", csp)
        self.assertIn('base-uri', csp)
        self.assertIn("form-action 'self'", csp)
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertIn('camera=()', response['Permissions-Policy'])

    def test_csp_allows_site_scripts_and_payment(self):
        csp = Client().get('/robots.txt')['Content-Security-Policy']
        self.assertIn('checkout.razorpay.com', csp)
        self.assertIn('googletagmanager.com', csp)

    def test_permissions_policy_allows_our_own_microphone(self):
        """The AI Studio's voice typing is dead if this ever goes back to `()`.

        The browser rejects getUserMedia() before the page can even ask the
        seller for permission, so no amount of front-end care can recover it.
        """
        policy = Client().get('/robots.txt')['Permissions-Policy']
        self.assertIn('microphone=(self)', policy)
        self.assertNotIn('microphone=()', policy)
        # Same-origin only: a cross-origin document still gets no microphone.
        self.assertNotIn('microphone=*', policy)


class ThrottleTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_newsletter_subscribe_limits_requests(self):
        client = Client()
        for _ in range(10):
            resp = client.post('/newsletter/subscribe/', {'email': 'nope@'})
        resp = client.post('/newsletter/subscribe/', {'email': 'nope@'})
        self.assertEqual(resp.status_code, 429)

    def test_signup_limits_requests(self):
        client = Client()
        for _ in range(5):
            client.post('/accounts/signup/', {'username': 'x'})
        resp = client.post('/accounts/signup/', {'username': 'x'})
        self.assertEqual(resp.status_code, 429)


class NewsletterRedirectTests(TestCase):
    def test_no_open_redirect_via_referer(self):
        client = Client()
        resp = client.post(
            '/newsletter/subscribe/',
            {'email': 'not-an-email'},
            HTTP_REFERER='https://evil.example/phish',
        )
        self.assertNotIn('evil.example', resp.get('Location', ''))


class UploadValidatorTests(SimpleTestCase):
    def _upload(self, name, content):
        return SimpleUploadedFile(name, content, content_type='application/octet-stream')

    def test_rejects_executable_documents(self):
        with self.assertRaises(ValidationError):
            validate_document_file(self._upload('virus.exe', b'MZ'))

    def test_rejects_svg_images(self):
        with self.assertRaises(ValidationError):
            validate_image_file(self._upload('logo.svg', b'<svg/>'))

    def test_rejects_oversized_files(self):
        big = self._upload('big.png', b'\x00' * (MAX_UPLOAD_BYTES + 1))
        with self.assertRaises(ValidationError):
            validate_document_file(big)

    def test_accepts_pdf_documents(self):
        validate_document_file(self._upload('proof.pdf', b'%PDF-1.4'))

    def test_accepts_png_images(self):
        validate_image_file(self._upload('photo.png', b'\x89PNG'))


class CKEditorMediaTests(SimpleTestCase):
    """django-ckeditor's init script must render as a whole <script> tag."""

    def test_init_script_is_not_truncated(self):
        from seller.forms import ProductForm

        html = str(ProductForm().media)
        self.assertIn(
            '<script src="/static/ckeditor/ckeditor-init.js" '
            'data-ckeditor-basepath="/static/ckeditor/ckeditor/" '
            'id="ckeditor-init-script"></script>',
            html,
        )

    def test_every_js_path_has_an_opening_and_closing_tag(self):
        from seller.forms import ProductForm

        html = str(ProductForm().media)
        for tag in html.splitlines():
            self.assertTrue(
                tag.startswith('<script src="'),
                f'js_asset fragment leaked without its tag: {tag!r}',
            )
            self.assertTrue(tag.endswith('"></script>'), f'unclosed script tag: {tag!r}')

    def test_plain_paths_still_render(self):
        from django.forms.widgets import Media

        html = '\n'.join(Media(js=['js/app.js']).render_js())
        self.assertEqual(html, '<script src="/static/js/app.js"></script>')


class CKEditorResponsiveTests(SimpleTestCase):
    """The seller editors must fill their column instead of a fixed pixel width.

    django-ckeditor defaults to an 835px editor and its RichTextFormField
    discards any ``Meta.widgets`` entry, so these assert the form-field
    callback actually reaches the rendered widget.
    """

    def _config(self, widget):
        return widget.config

    def test_product_description_is_fluid(self):
        from core.ckeditor import ResponsiveCKEditorWidget
        from seller.forms import ProductForm

        widget = ProductForm().fields['description'].widget
        self.assertIsInstance(widget, ResponsiveCKEditorWidget)
        self.assertEqual(self._config(widget)['width'], '100%')
        self.assertTrue(self._config(widget)['resize_enabled'])

    def test_variant_description_is_fluid(self):
        from core.ckeditor import ResponsiveCKEditorWidget
        from seller.forms import ProductVariantForm

        widget = ProductVariantForm().fields['description'].widget
        self.assertIsInstance(widget, ResponsiveCKEditorWidget)
        self.assertEqual(self._config(widget)['width'], '100%')

    def test_contents_css_points_at_the_iframe_stylesheet(self):
        from django.contrib.staticfiles import finders
        from seller.forms import ProductForm

        # The WYSIWYG document is a separate page: page CSS cannot reach it, so
        # CKEditor has to load it as contentsCss.
        url = self._config(ProductForm().fields['description'].widget)['contentsCss']
        self.assertEqual(url, '/static/css/ckeditor-content.css')
        self.assertIsNotNone(finders.find('css/ckeditor-content.css'))

    def test_non_richtext_fields_survive_the_callback(self):
        from django import forms
        from seller.forms import ProductForm

        fields = ProductForm().fields
        # formfield_callback has to build every field, not just the rich ones.
        self.assertIsInstance(fields['name'].widget, forms.TextInput)
        self.assertIsInstance(fields['price'].widget, forms.NumberInput)

    def test_rendered_config_reaches_the_browser(self):
        import json
        from html import unescape

        from seller.forms import ProductForm

        html = str(ProductForm()['description'])
        start = html.index('data-config="') + len('data-config="')
        # The template engine escapes the JSON; getAttribute() hands the browser
        # the unescaped string, so unescape before parsing.
        config = json.loads(unescape(html[start:html.index('" data-external', start)]))
        self.assertEqual(config['width'], '100%')
        self.assertEqual(config['contentsCss'], '/static/css/ckeditor-content.css')

    def test_stylesheet_and_reflow_script_are_collectable(self):
        from django.contrib.staticfiles import finders

        for path in (
            'css/ckeditor-responsive.css',
            'css/ckeditor-content.css',
            'js/ckeditor-responsive.js',
        ):
            with self.subTest(path=path):
                self.assertIsNotNone(finders.find(path))
