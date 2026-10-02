from django.test import SimpleTestCase
from django.urls import resolve, reverse

from . import views


class TestSchemesUrls(SimpleTestCase):
    def test_list_url(self):
        url = reverse('schemes:schemes_list')
        self.assertEqual(resolve(url).func, views.schemes_list)

    def test_list_url_path(self):
        self.assertEqual(reverse('schemes:schemes_list'), '/artisan-schemes/')


class TestSchemeData(SimpleTestCase):
    def test_every_filter_count_matches_the_records(self):
        for scheme in views.SCHEMES:
            for tag in scheme['tags']:
                self.assertIn(tag, views.FILTER_LABELS, tag)

    def test_all_count_is_the_full_list(self):
        all_filter = next(f for f in views.SCHEME_FILTERS if f['slug'] == 'all')
        self.assertEqual(views._count_for('all'), len(views.SCHEMES))

    def test_no_scheme_advertises_an_unverified_link(self):
        for scheme in views.SCHEMES:
            self.assertEqual(scheme['official_url'], '')
            self.assertIsNone(scheme['last_verified'])

    def test_presentation_adds_labelled_tag_chips(self):
        presented = views._present(views.SCHEMES[0])
        self.assertTrue(presented['tag_chips'])
        for chip in presented['tag_chips']:
            self.assertNotEqual(chip['label'], chip['slug'])
            self.assertNotIn(chip['slug'], views.TYPE_TAGS)

    def test_presentation_does_not_mutate_the_source_record(self):
        views._present(views.SCHEMES[0])
        self.assertNotIn('tag_chips', views.SCHEMES[0])