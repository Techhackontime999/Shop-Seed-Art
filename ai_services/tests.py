"""Tests for the image enhancement service.

Organised by the promise each layer makes:

* ``TestUploadValidation``  - untrusted bytes are judged, not claimed types
* ``TestSegmentation``      - the product survives, the backdrop does not
* ``TestPipeline``          - output shape, fidelity, and degradation
* ``TestStorage``           - originals are never overwritten
* ``TestEnhanceEndpoint``   - auth, ownership, throttling, response shape
* ``TestSelectionEndpoint`` - draft choice, and that it never publishes
* ``TestConfiguration``     - the production guard

The expensive-image tests build their fixtures in memory; nothing is read
from disk and no network call is made (the advisor is off by default).
"""

import io
import json
import tempfile
import unittest
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from PIL import Image, ImageDraw, ImageFilter

from .models import EnhancementStatus, ImageEnhancementJob, Selection
from .services.background_remover import ClassicalSegmenter
from .services.image_processor import StudioProvider
from .services.providers.base import (
    BACKGROUND_NEUTRAL,
    BACKGROUND_TRANSPARENT,
    BACKGROUND_WHITE,
    EnhancementOptions,
)
from .services.storage import StorageError


def product_photo(size=(900, 900), backdrop=(228, 223, 214), body=(176, 58, 44)):
    """A red product on a beige studio backdrop.

    Includes a cast shadow and a pale inner rim, which are the two things a
    naive segmenter gets wrong: it deletes the shadow's backdrop as product,
    or it deletes the rim as backdrop.
    """
    img = Image.new('RGB', size, backdrop)
    d = ImageDraw.Draw(img)
    d.ellipse([210, 560, 690, 660], fill=(205, 199, 190))
    img = img.filter(ImageFilter.GaussianBlur(9))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([230, 210, 670, 620], radius=48, fill=body)
    d.rounded_rectangle([248, 228, 652, 602], radius=36,
                        outline=(238, 232, 224), width=14)
    d.ellipse([360, 330, 540, 470], fill=(232, 226, 218))
    return img


def as_upload(img, name='photo.jpg', fmt='JPEG'):
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')


class TestUploadValidation(TestCase):
    """A PHP script renamed to photo.jpg must not get in."""

    def setUp(self):
        from .utils.image_validation import validate_upload
        self.validate = validate_upload
        self.kwargs = dict(max_bytes=25 * 1024 * 1024, max_pixels=40_000_000)

    def _reject(self, upload):
        from .utils.image_validation import ImageValidationError
        with self.assertRaises(ImageValidationError) as ctx:
            self.validate(upload, **self.kwargs)
        return ctx.exception

    def test_rejects_disguised_script(self):
        exc = self._reject(SimpleUploadedFile('photo.jpg', b'<?php system($_GET[0]); ?>'))
        self.assertEqual(exc.code, 'not_an_image')
        self.assertNotIn('<?php', exc.message)  # nothing internal leaks to seller

    def test_rejects_zip(self):
        exc = self._reject(SimpleUploadedFile('photo.jpg', b'PK\x03\x04' + b'\0' * 64))
        self.assertEqual(exc.code, 'not_an_image')

    def test_rejects_svg_disguised_as_jpeg(self):
        svg = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>'
        exc = self._reject(SimpleUploadedFile('photo.jpg', svg))
        self.assertIn(exc.code, ('not_an_image', 'corrupt_image', 'type_mismatch'))

    def test_rejects_empty_file(self):
        self.assertEqual(self._reject(SimpleUploadedFile('p.jpg', b'')).code, 'empty_file')

    def test_rejects_oversized(self):
        big = b'\xff\xd8\xff' + b'\0' * (26 * 1024 * 1024)
        self.assertEqual(self._reject(SimpleUploadedFile('p.jpg', big)).code, 'file_too_large')

    def test_rejects_too_small(self):
        tiny = Image.new('RGB', (32, 32), (10, 20, 30))
        self.assertEqual(self._reject(as_upload(tiny)).code, 'image_too_small')

    def test_rejects_animation_bomb_vector(self):
        # A GIF can declare a 64000x64000 canvas; the decoder is refused
        # outright rather than trusted to allocate.
        gif = b'GIF89a' + (64000).to_bytes(2, 'little') + (64000).to_bytes(2, 'little')
        self.assertEqual(self._reject(SimpleUploadedFile('p.gif', gif)).code,
                         'unsupported_format')

    def test_rejects_truncated_jpeg(self):
        """Pillow is lenient; a mid-file truncation often still decodes.
        A header-only file is the reliable rejection path."""
        from PIL import Image
        import io
        buf = io.BytesIO()
        product_photo((400, 400)).save(buf, format='JPEG')
        full = buf.getvalue()
        # Only the first 100 bytes = SOI + partial header, no image data
        exc = self._reject(SimpleUploadedFile('p.jpg', full[:100]))
        self.assertIn(exc.code, ('corrupt_image', 'type_mismatch', 'not_an_image'))

    def test_accepts_real_photo(self):
        result = self.validate(as_upload(product_photo((400, 400))), **self.kwargs)
        self.assertEqual(result.format, 'JPEG')
        self.assertEqual(result.size, (400, 400))


class TestSegmentation(TestCase):
    def setUp(self):
        self.segmenter = ClassicalSegmenter()
        self.photo = product_photo()

    def test_isolates_product_on_flat_backdrop(self):
        mask = self.segmenter.segment(self.photo)
        self.assertIsNotNone(mask)
        self.assertEqual(mask.size, self.photo.size)

    def test_keeps_pale_detail_inside_the_product(self):
        """The rim is light like the backdrop, but it is inside the product."""
        import numpy as np
        mask = np.asarray(self.segmenter.segment(self.photo))
        rim = mask[230:244, 400:440]
        self.assertGreater((rim > 127).mean(), 0.9)

    def test_removes_backdrop(self):
        import numpy as np
        mask = np.asarray(self.segmenter.segment(self.photo))
        corner = mask[10:60, 10:60]
        self.assertLess((corner > 127).mean(), 0.05)

    def test_declines_on_a_flat_frame(self):
        """Nothing to isolate means None, so the seller's background is kept."""
        self.assertIsNone(
            self.segmenter.segment(Image.new('RGB', (600, 600), (176, 58, 44)))
        )

    def test_works_on_dark_product_light_backdrop(self):
        mask = self.segmenter.segment(
            product_photo(size=(700, 700), backdrop=(38, 40, 44), body=(214, 206, 190))
        )
        self.assertIsNotNone(mask)

    def test_never_raises_on_hostile_input(self):
        """A segmentation failure degrades to 'no mask', it never 500s."""
        with mock.patch('scipy.ndimage.label', side_effect=RuntimeError('boom')):
            self.assertIsNone(self.segmenter.segment(self.photo))


class TestPipeline(TestCase):
    def setUp(self):
        self.photo = product_photo()
        self.provider = StudioProvider(segmenter=ClassicalSegmenter())

    def _run(self, **kw):
        options = EnhancementOptions(advisor_guidance={}, **kw)
        return self.provider.enhance(self.photo, options)

    def test_records_every_stage_it_ran(self):
        result = self._run(background=BACKGROUND_WHITE)
        keys = [s.key for s in result.stages]
        for expected in ('validate', 'normalize', 'segment', 'clean', 'background',
                         'correct', 'sharpen', 'format', 'validate_output'):
            self.assertIn(expected, keys)

    def test_stage_details_are_present(self):
        """The UI renders these verbatim, so an empty detail is a UI gap."""
        for stage in self._run(background=BACKGROUND_WHITE).stages:
            self.assertTrue(stage.detail, 'stage %r has no detail' % stage.key)

    def test_white_background_output(self):
        result = self._run(background=BACKGROUND_WHITE)
        self.assertEqual(result.image.size, (1000, 1000))
        self.assertEqual(result.image.mode, 'RGB')
        self.assertGreater(result.image.getpixel((2, 2))[0], 245)

    def test_transparent_background_output(self):
        result = self._run(background=BACKGROUND_TRANSPARENT, canvas=(800, 800))
        self.assertEqual(result.image.mode, 'RGBA')
        self.assertLess(result.image.getchannel('A').getpixel((2, 2)), 20)
        self.assertGreater(result.image.getchannel('A').getpixel((400, 400)), 200)

    def test_product_colour_is_preserved(self):
        """The core promise: a red product does not come back orange."""
        import numpy as np
        result = self._run(background=BACKGROUND_WHITE)
        arr = np.asarray(result.image, dtype=np.float32)
        self.assertGreater(result.quality['fidelity'], 0.8)
        self.assertLess(result.quality['color_shift'], 13)
        # Sample the product region (centered, ~400x400) not the white backdrop
        h, w = arr.shape[:2]
        product = arr[h//2-200:h//2+200, w//2-200:w//2+200]
        red, _, blue = product[..., 0].mean(), product[..., 1].mean(), product[..., 2].mean()
        self.assertGreater(red, blue + 40)

    def test_never_leaves_a_backdrop_halo(self):
        """Deleted-background photos are betrayed by a fringe of old backdrop."""
        import numpy as np
        from scipy import ndimage
        result = self._run(background=BACKGROUND_WHITE)
        arr = np.asarray(result.image, dtype=np.float32)
        product = (255 - arr.min(axis=2)) > 18
        product = ndimage.binary_opening(product, np.ones((3, 3)), iterations=1)
        ring = (ndimage.binary_dilation(product, iterations=6)
                & ~ndimage.binary_dilation(product, iterations=2))
        if ring.any():
            self.assertLess(float(np.abs(arr[ring] - 255).max()), 40)

    def test_never_crops_the_product(self):
        """A wide product must not lose its edges to fill the square canvas."""
        wide = product_photo(size=(1200, 500), body=(58, 92, 176))
        result = self.provider.enhance(
            wide, EnhancementOptions(canvas=(1000, 1000), advisor_guidance={}))
        self.assertEqual(result.image.size, (1000, 1000))

    def test_does_not_upscale_a_small_photo(self):
        small = product_photo(size=(200, 200))
        result = self.provider.enhance(
            small, EnhancementOptions(canvas=(1000, 1000), advisor_guidance={}))
        self.assertEqual(result.image.size, (1000, 1000))

    def test_original_background_is_preserved_when_asked(self):
        result = self._run(background='original')
        self.assertFalse(result.quality['segmented'])

    def test_survives_a_flat_photo(self):
        result = self.provider.enhance(
            Image.new('RGB', (600, 600), (200, 200, 200)),
            EnhancementOptions(canvas=(1000, 1000), advisor_guidance={}))
        self.assertEqual(result.image.size, (1000, 1000))

    def test_survives_a_near_black_photo(self):
        result = self.provider.enhance(
            Image.new('RGB', (600, 600), (10, 10, 12)),
            EnhancementOptions(canvas=(1000, 1000), advisor_guidance={}))
        self.assertEqual(result.image.size, (1000, 1000))

    def test_survives_a_tiny_photo(self):
        result = self.provider.enhance(
            Image.new('RGB', (12, 12), (120, 90, 60)),
            EnhancementOptions(canvas=(1000, 1000), advisor_guidance={}))
        self.assertEqual(result.image.size, (1000, 1000))

    def test_advisor_can_only_reduce_work(self):
        """A model asking for a bigger canvas must not get one."""
        result = self.provider.enhance(
            self.photo,
            EnhancementOptions(canvas=(1000, 1000), output_quality=90,
                               advisor_guidance={'canvas': [4000, 4000]}))
        self.assertEqual(result.image.size, (1000, 1000))

    def test_metadata_is_stripped_from_output(self):
        """A phone photo's GPS must not survive into a published listing."""
        from .utils.image_io import encode_image
        buf = io.BytesIO()
        exif = Image.Exif()
        exif[0x0132] = '19.0760, 72.8777'  # DateTime, stands in for a GPS tag
        self.photo.save(buf, format='JPEG', exif=exif)
        raw = buf.getvalue()
        from .utils.image_io import open_image
        self.assertNotIn(b'Exif', encode_image(open_image(raw), 'JPEG', 90)[:200])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TestStorage(TestCase):
    def test_original_is_never_overwritten(self):
        from .services.storage import StorageError, store_original
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        name = store_original(b'first-bytes', 'JPEG', 'job-abc')
        with self.assertRaises(StorageError):
            store_original(b'second-bytes', 'JPEG', 'job-abc')
        self.assertEqual(default_storage.open(name).read(), b'first-bytes')

    def test_retries_do_not_collide(self):
        from .services.storage import store_enhanced
        from django.core.files.storage import default_storage
        a = store_enhanced(b'aaa', 'JPEG', 'job-xyz', attempt=1)
        b = store_enhanced(b'bbb', 'JPEG', 'job-xyz', attempt=2)
        self.assertNotEqual(a, b)
        self.assertEqual(default_storage.open(b).read(), b'bbb')

    def test_enhanced_lives_outside_products(self):
        from .services.storage import store_enhanced
        name = store_enhanced(b'x', 'JPEG', 'job-prefix')
        self.assertTrue(name.startswith('ai-enhancements/'))
        self.assertNotIn('products/', name)

    def test_refuses_empty_file(self):
        from .services.storage import StorageError, store_original
        with self.assertRaises(StorageError):
            store_original(b'', 'JPEG', 'job-empty')


class EnhanceTestBase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user('seller', 's@example.com', 'pw')
        self.other = User.objects.create_user('rival', 'r@example.com', 'pw')
        self.client = Client()
        self.client.force_login(self.user)
        self.url = '/ai/image/enhance/'

    @staticmethod
    def _unauthenticated_client():
        return Client()


@override_settings(IMAGE_ENHANCEMENT_RATE_LIMIT=100)
class TestEnhanceEndpoint(EnhanceTestBase):
    def test_requires_login(self):
        Client().post(self.url, {'image': as_upload(product_photo((400, 400)))})
        self.assertEqual(
            Client().post(self.url, {'image': as_upload(product_photo((400, 400)))}).status_code,
            302,
        )

    def test_rejects_get(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.login(username=self.user.username, password='pw')
        response = csrf_client.post(
            self.url, {'image': as_upload(product_photo((400, 400)))})
        self.assertEqual(response.status_code, 403)

    def test_rejects_missing_file(self):
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error']['code'], 'missing_file')

    def test_rejects_a_disguised_script(self):
        response = self.client.post(
            self.url, {'image': SimpleUploadedFile('p.jpg', b'<?php ?>')})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['error']['message'].count('<?php'))

    def test_rejects_unknown_background(self):
        response = self.client.post(self.url, {
            'image': as_upload(product_photo((400, 400))), 'background': 'sparkles'})
        self.assertEqual(response.json()['error']['code'], 'bad_background')

    def test_successful_enhancement(self):
        response = self.client.post(self.url, {
            'image': as_upload(product_photo((400, 400))),
            'background': BACKGROUND_WHITE,
        })
        self.assertEqual(response.status_code, 201, response.content[:300])
        body = response.json()
        self.assertTrue(body['success'])

        job = body['job']
        self.assertEqual(job['status'], EnhancementStatus.COMPLETED)
        self.assertTrue(job['original_url'])
        self.assertTrue(job['enhanced_url'])
        self.assertNotEqual(job['original_url'], job['enhanced_url'])
        self.assertEqual(job['selection'], Selection.NONE)
        self.assertTrue(job['stages'])

    def test_enhanced_and_original_are_different_files(self):
        response = self.client.post(self.url, {
            'image': as_upload(product_photo((400, 400)))})
        job = ImageEnhancementJob.objects.get(pk=response.json()['job']['id'])
        self.assertTrue(job.original.name)
        self.assertTrue(job.enhanced.name)
        self.assertNotEqual(job.original.name, job.enhanced.name)

    def test_does_not_create_a_product(self):
        """Enhancement is a draft. It must never publish anything."""
        from shop.models import Product
        before = Product.objects.count()
        self.client.post(self.url, {'image': as_upload(product_photo((400, 400)))})
        self.assertEqual(Product.objects.count(), before)

    def test_is_rate_limited(self):
        cache.clear()
        with override_settings(IMAGE_ENHANCEMENT_RATE_LIMIT=2):
            for _ in range(2):
                first = self.client.post(
                    self.url, {'image': as_upload(product_photo((400, 400)))})
                self.assertEqual(first.status_code, 201, first.content[:200])
            limited = self.client.post(
                self.url, {'image': as_upload(product_photo((400, 400)))})
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()['error']['code'], 'rate_limited')
        cache.clear()

    def test_provider_failure_is_reported_cleanly(self):
        with mock.patch('ai_services.views.run_enhancement') as run:
            from .services.image_enhancer import EnhancementError
            run.side_effect = EnhancementError(
                'enhancement_failed', 'We could not enhance that photo.',
                detail='KeyError: secret_internal_path')
            response = self.client.post(self.url, {
                'image': as_upload(product_photo((400, 400)))})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('secret_internal_path', response.content.decode())

    def test_unexpected_error_does_not_leak_a_traceback(self):
        with mock.patch('ai_services.views.run_enhancement',
                        side_effect=RuntimeError('secret_internal_path')):
            response = self.client.post(self.url, {
                'image': as_upload(product_photo((400, 400)))})
        self.assertEqual(response.status_code, 500)
        body = response.content.decode()
        self.assertNotIn('secret_internal_path', body)
        self.assertNotIn('Traceback', body)


class TestStatusAndDraft(EnhanceTestBase):
    def setUp(self):
        super().setUp()
        self.job = ImageEnhancementJob.objects.create(
            seller=self.user, status=EnhancementStatus.COMPLETED,
            original='ai-enhancements/originals/2026/01/01/a.jpg',
            enhanced='ai-enhancements/enhanced/2026/01/01/a.jpg')

    def test_status_returns_own_job(self):
        response = self.client.get('/ai/image/status/%s/' % self.job.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['job']['id'], str(self.job.id))

    def test_status_hides_another_sellers_job(self):
        User = get_user_model()
        other = User.objects.create_user('nosy', 'n@example.com', 'pw')
        other_job = ImageEnhancementJob.objects.create(
            seller=other, status=EnhancementStatus.COMPLETED,
            original='ai-enhancements/originals/2026/01/01/b.jpg',
            enhanced='ai-enhancements/enhanced/2026/01/01/b.jpg')
        response = self.client.get('/ai/image/status/%s/' % other_job.id)
        self.assertEqual(response.status_code, 404)

    def test_status_requires_login(self):
        self.assertEqual(Client().get('/ai/image/status/%s/' % self.job.id).status_code, 302)

    def test_draft_returns_latest(self):
        response = self.client.get('/ai/image/draft/')
        self.assertEqual(response.json()['job']['id'], str(self.job.id))

    def test_draft_is_empty_for_a_new_seller(self):
        User = get_user_model()
        User.objects.create_user('fresh', 'f@example.com', 'pw')
        c = Client()
        c.login(username='fresh', password='pw')
        self.assertIsNone(c.get('/ai/image/draft/').json()['job'])


class TestSelectionEndpoint(EnhanceTestBase):
    def setUp(self):
        super().setUp()
        self.job = ImageEnhancementJob.objects.create(
            seller=self.user, status=EnhancementStatus.COMPLETED,
            original='ai-enhancements/originals/2026/01/01/a.jpg',
            enhanced='ai-enhancements/enhanced/2026/01/01/a.jpg')
        self.url = '/ai/image/select/'

    def test_records_use_enhanced(self):
        response = self.client.post(self.url, {
            'job_id': str(self.job.id), 'selection': Selection.ENHANCED})
        self.assertEqual(response.status_code, 200)
        self.job.refresh_from_db()
        self.assertEqual(self.job.selection, Selection.ENHANCED)

    def test_records_keep_original(self):
        self.client.post(self.url, {
            'job_id': str(self.job.id), 'selection': Selection.ORIGINAL})
        self.job.refresh_from_db()
        self.assertEqual(self.job.selection, Selection.ORIGINAL)

    def test_rejects_an_invalid_choice(self):
        response = self.client.post(self.url, {
            'job_id': str(self.job.id), 'selection': 'published'})
        self.assertEqual(response.json()['error']['code'], 'bad_selection')

    def test_cannot_select_another_sellers_draft(self):
        User = get_user_model()
        other = User.objects.create_user('thief', 't@example.com', 'pw')
        other_job = ImageEnhancementJob.objects.create(
            seller=other, status=EnhancementStatus.COMPLETED,
            original='ai-enhancements/originals/2026/01/01/c.jpg',
            enhanced='ai-enhancements/enhanced/2026/01/01/c.jpg')
        response = self.client.post(self.url, {
            'job_id': str(other_job.id), 'selection': Selection.ENHANCED})
        self.assertEqual(response.status_code, 404)
        other_job.refresh_from_db()
        self.assertEqual(other_job.selection, Selection.NONE)

    def test_cannot_select_an_unfinished_job(self):
        self.job.status = EnhancementStatus.PROCESSING
        self.job.save()
        response = self.client.post(self.url, {
            'job_id': str(self.job.id), 'selection': Selection.ENHANCED})
        self.assertEqual(response.status_code, 409)

    def test_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.login(username=self.user.username, password='pw')
        response = csrf_client.post(self.url, {
            'job_id': str(self.job.id), 'selection': Selection.ENHANCED})
        self.assertEqual(response.status_code, 403)
        self.job.refresh_from_db()
        self.assertEqual(self.job.selection, Selection.NONE)

    def test_selection_does_not_publish_a_product(self):
        from shop.models import Product
        before = Product.objects.count()
        self.client.post(self.url, {
            'job_id': str(self.job.id), 'selection': Selection.ENHANCED})
        self.assertEqual(Product.objects.count(), before)


@override_settings(IMAGE_ENHANCEMENT_RATE_LIMIT=100, MEDIA_ROOT=tempfile.mkdtemp())
class TestUploadPhotoEndpoint(EnhanceTestBase):
    """A photo the seller chose not to enhance still has to reach the server.

    ``publish`` attaches an image by job id, so without this endpoint a seller
    who skips the enhancement step would silently get a product with no image.
    """

    def setUp(self):
        super().setUp()
        self.url = '/ai/image/upload/'
        # Publish needs a seller profile; the studio redirects to onboarding
        # without one, so a real flow always has it by the time it gets here.
        from accounts.models import SellerProfile
        SellerProfile.objects.create(
            user=self.user, shop_name='Studio Shop', bank_account='123456789',
            account_holder_name='Seller', ifsc_code='HDFC0001234',
            phone='9999999999', address='Test address',
            is_email_verified=True, is_phone_verified=True,
        )

    def test_requires_login(self):
        self.assertEqual(
            Client().post(self.url, {'image': as_upload(product_photo())}).status_code, 302)

    def test_requires_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.login(username=self.user.username, password='pw')
        response = csrf_client.post(self.url, {'image': as_upload(product_photo())})
        self.assertEqual(response.status_code, 403)

    def test_rejects_a_missing_file(self):
        response = self.client.post(self.url, {})
        self.assertEqual(response.json()['error']['code'], 'missing_file')

    def test_rejects_a_non_image(self):
        bogus = SimpleUploadedFile('photo.jpg', b'<?php echo 1; ?>',
                                   content_type='image/jpeg')
        response = self.client.post(self.url, {'image': bogus})
        self.assertEqual(response.json()['error']['code'], 'not_an_image')
        self.assertEqual(ImageEnhancementJob.objects.count(), 0)

    def test_stores_the_photo_and_reports_a_usable_job(self):
        from django.core.files.storage import default_storage

        response = self.client.post(
            self.url, {'image': as_upload(product_photo((600, 600)))})
        self.assertEqual(response.status_code, 201)
        job = response.json()['job']
        self.assertEqual(job['status'], EnhancementStatus.COMPLETED)

        row = ImageEnhancementJob.objects.get(pk=job['id'])
        self.assertEqual(row.seller, self.user)
        self.assertTrue(row.original)
        # No enhanced artefact, and the seller did not choose one.
        self.assertFalse(row.has_enhanced)
        self.assertFalse(row.enhanced)
        self.assertIsNone(row.as_dict()['enhanced_url'])
        self.assertEqual(row.selection, Selection.ORIGINAL)
        self.assertFalse(row.is_ai)

        # The bytes are the seller's own file, untouched.
        with default_storage.open(row.original.name) as fh:
            self.assertGreater(len(fh.read()), 100)

    def test_the_job_can_be_used_to_publish_with_an_image(self):
        from shop.models import Product

        upload = self.client.post(
            self.url, {'image': as_upload(product_photo((600, 600)))})
        self.assertEqual(upload.status_code, 201)

        response = self.client.post(
            '/ai/publish/',
            json.dumps({
                'title': 'Handwoven Runner',
                'description': 'A cotton runner woven by hand.',
                'category': 'Textiles',
                'price': '1200',
                'stock': 1,
                'enhancement_job': upload.json()['job']['id'],
                'use_enhanced': False,
            }),
            content_type='application/json')

        self.assertEqual(response.status_code, 201)
        product = Product.objects.get(name='Handwoven Runner')
        self.assertTrue(product.image, 'published product must carry the photo')
        self.assertTrue(product.image.name.startswith('products/'),
                        'the photo must be copied into the product, not linked')

    def test_stored_bytes_never_live_under_products(self):
        response = self.client.post(self.url, {'image': as_upload(product_photo())})
        row = ImageEnhancementJob.objects.get(pk=response.json()['job']['id'])
        self.assertTrue(row.original.name.startswith('ai-enhancements/'))
        self.assertNotIn('products/', row.original.name)

    def test_is_rate_limited(self):
        cache.clear()
        with override_settings(IMAGE_ENHANCEMENT_RATE_LIMIT=1):
            first = self.client.post(self.url, {'image': as_upload(product_photo())})
            second = self.client.post(self.url, {'image': as_upload(product_photo())})
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()['error']['code'], 'rate_limited')
        cache.clear()

    def test_a_storage_failure_is_reported_not_silently_dropped(self):
        with mock.patch('ai_services.views.store_original',
                        side_effect=StorageError('disk full')):
            response = self.client.post(self.url, {'image': as_upload(product_photo())})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()['error']['code'], 'storage_failed')

    def test_uploading_does_not_publish_a_product(self):
        from shop.models import Product
        before = Product.objects.count()
        self.client.post(self.url, {'image': as_upload(product_photo())})
        self.assertEqual(Product.objects.count(), before)


class TestConfiguration(TestCase):
    def test_demo_provider_is_an_error_in_production(self):
        from .checks import check_production_configuration
        with override_settings(DEBUG=False, IMAGE_ENHANCEMENT_PROVIDER='demo'):
            ids = {m.id for m in check_production_configuration(None)}
        self.assertIn('ai_services.E001', ids)

    def test_demo_provider_is_fine_in_debug(self):
        from .checks import check_production_configuration
        with override_settings(DEBUG=True, IMAGE_ENHANCEMENT_PROVIDER='demo'):
            self.assertEqual(check_production_configuration(None), [])

    def test_unknown_provider_is_an_error(self):
        from .checks import check_production_configuration
        with override_settings(IMAGE_ENHANCEMENT_PROVIDER='magic'):
            ids = {m.id for m in check_production_configuration(None)}
        self.assertIn('ai_services.E002', ids)

    @override_settings(IMAGE_ENHANCEMENT_PROVIDER='studio',
                       IMAGE_ENHANCEMENT_BACKGROUND=BACKGROUND_NEUTRAL)
    def test_neutral_background_is_supported(self):
        from .checks import check_production_configuration
        self.assertEqual(check_production_configuration(None), [])

    def test_image_path_makes_no_external_call(self):
        """OpenRouter is for voice and text; enhancement must stay local."""
        with mock.patch('requests.Session.post',
                        side_effect=AssertionError('external call during enhancement')):
            StudioProvider(segmenter=ClassicalSegmenter()).enhance(
                product_photo((400, 400)),
                EnhancementOptions(canvas=(1000, 1000), advisor_guidance={}))

# =========================================================================
# Voice + Text endpoint tests
# =========================================================================

