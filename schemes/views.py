"""Artisan scheme directory — presentation layer only.

This module intentionally holds NO model, no query and no integration. The
scheme records below are hand-written placeholders that exist so the directory
UI can be designed and reviewed before any data source is agreed.

The dict keys mirror the future ``Scheme`` model field-for-field (name,
provider, type, category, description, eligible_artisans, benefits, state,
application_method, official_url, last_verified, active) so that swapping this
list for a queryset is a mechanical change: keep the template contract and
replace the literal with the query.

Nothing here is verified. ``official_url`` is empty and ``last_verified`` is
None on every record, which is why the template renders "Last Verified: —"
and an inert CTA instead of an outbound link.
"""

from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

SORT_OPTIONS = [
    {'value': 'curated', 'label': _('Curated order')},
    {'value': 'name-asc', 'label': _('Name A–Z')},
    {'value': 'name-desc', 'label': _('Name Z–A')},
    {'value': 'government', 'label': _('Government first')},
]

TYPE_TAGS = ('government', 'non-government')

# Filter chips are also a hardcoded UI list for now. ``tags`` on each record
# is what the client-side filter matches against, so adding a chip means
# adding its tag to the records too.
SCHEME_FILTERS = [
    {'slug': 'all', 'label': _('All Schemes')},
    {'slug': 'government', 'label': _('Government')},
    {'slug': 'non-government', 'label': _('Non-Government')},
    {'slug': 'financial-support', 'label': _('Financial Support')},
    {'slug': 'training', 'label': _('Training & Skill Development')},
    {'slug': 'marketing', 'label': _('Marketing Support')},
    {'slug': 'equipment', 'label': _('Equipment & Tools')},
    {'slug': 'women', 'label': _('Women Artisans')},
    {'slug': 'youth', 'label': _('Youth')},
]

# ── PLACEHOLDER CONTENT — NOT VERIFIED ──────────────────────────────────
# Demo records. Names, providers and figures are illustrative samples of the
# kind of listing the directory will hold; none of them has been checked
# against a ministry, board or NGO, and no official URL is attached.
SCHEMES = [
    {
        'name': 'PM Vishwakarma (placeholder listing)',
        'provider': 'Ministry of Micro, Small & Medium Enterprises',
        'type': 'Government',
        'category': 'Financial Support',
        'description': (
            'Sample entry — support programme for eligible traditional '
            'artisans and craftspeople, covering recognition, skill '
            'upgrading and credit access.'
        ),
        'eligible_artisans': 'Artisans working with wood, metal, leather, stone, terracotta and other craft trades',
        'benefits': 'Tool-kit support, credit guarantee cover, skill certification, mentoring network',
        'state': 'Pan-India',
        'application_method': 'Common service centre / designated portal (illustrative)',
        'official_url': '',
        'last_verified': None,
        'active': True,
        'tags': ['government', 'financial-support', 'equipment', 'training'],
        'icon': 'fa-solid fa-hands-holding-circle',
        'accent': 'gov',
    },
    {
        'name': 'National Handicrafts Development Programme',
        'provider': 'Office of the Development Commissioner for Handicrafts',
        'type': 'Government',
        'category': 'Training & Skill Development',
        'description': (
            'Sample entry — cluster-level intervention combining design '
            'training, shared workspaces and market linkage for craft '
            'communities.'
        ),
        'eligible_artisans': 'Artisans in notified craft clusters, including master craftspeople',
        'benefits': 'Design workshops, shared tooling, exhibition participation, buyer introductions',
        'state': 'Select states and clusters',
        'application_method': 'Craft development agency / empanelled training partner',
        'official_url': '',
        'last_verified': None,
        'active': True,
        'tags': ['government', 'training', 'marketing'],
        'icon': 'fa-solid fa-palette',
        'accent': 'gov',
    },
    {
        'name': 'Women Artisans Collective — Livelihood Grant',
        'provider': 'Non-governmental craft collective',
        'type': 'Non-Government',
        'category': 'Financial Support',
        'description': (
            'Sample entry — pooled working-capital grant for self-help '
            'groups of women artisans, paired with bookkeeping support.'
        ),
        'eligible_artisans': 'Women artisans organised in registered self-help groups',
        'benefits': 'Working capital, bookkeeping assistance, raw-material advance',
        'state': 'Illustrative — regional',
        'application_method': 'Through the collective office (illustrative)',
        'official_url': '',
        'last_verified': None,
        'active': True,
        'tags': ['non-government', 'financial-support', 'women'],
        'icon': 'fa-solid fa-people-group',
        'accent': 'ngo',
    },
    {
        'name': 'Weaver Market Access Programme',
        'provider': 'Craft-sector foundation',
        'type': 'Non-Government',
        'category': 'Marketing Support',
        'description': (
            'Sample entry — helps weaving co-operatives photograph, price '
            'and list their output, and introduces them to wholesale buyers.'
        ),
        'eligible_artisans': 'Handloom weavers and co-operative members',
        'benefits': 'Product photography, listing support, buyer fairs, pricing guidance',
        'state': 'Illustrative — regional',
        'application_method': 'Co-operative or guild referral',
        'official_url': '',
        'last_verified': None,
        'active': True,
        'tags': ['non-government', 'marketing', 'equipment'],
        'icon': 'fa-solid fa-store',
        'accent': 'ngo',
    },
    {
        'name': 'Young Artisan Skill Fellowship',
        'provider': 'Industry–government joint initiative',
        'type': 'Government',
        'category': 'Training & Skill Development',
        'description': (
            'Sample entry — short fellowships pairing apprentices with '
            'senior craftspeople, with a stipend during the training period.'
        ),
        'eligible_artisans': 'Apprentices under 30 learning a craft trade',
        'benefits': 'Stipend, tool kit, apprenticeship certificate, placement support',
        'state': 'Illustrative — selected districts',
        'application_method': 'Online application window (illustrative)',
        'official_url': '',
        'last_verified': None,
        'active': True,
        'tags': ['government', 'training', 'youth', 'equipment'],
        'icon': 'fa-solid fa-graduation-cap',
        'accent': 'gov',
    },
    {
        'name': 'Shared Tools & Workspace Fund',
        'provider': 'Craft-sector foundation',
        'type': 'Non-Government',
        'category': 'Equipment & Tools',
        'description': (
            'Sample entry — funds pooled access to kilns, looms, polishing '
            'benches and similar shared equipment for small workshops that '
            'cannot buy them individually.'
        ),
        'eligible_artisans': 'Owner-operators of small craft workshops',
        'benefits': 'Shared equipment access, maintenance cover, booking priority',
        'state': 'Illustrative — regional',
        'application_method': 'Membership enquiry with the foundation',
        'official_url': '',
        'last_verified': None,
        'active': True,
        'tags': ['non-government', 'equipment'],
        'icon': 'fa-solid fa-screwdriver-wrench',
        'accent': 'ngo',
    },
]


def _count_for(slug):
    if slug == 'all':
        return len(SCHEMES)
    return sum(1 for scheme in SCHEMES if slug in scheme['tags'])


FILTER_LABELS = {f['slug']: f['label'] for f in SCHEME_FILTERS}


def _present(scheme):
    tags = [t for t in scheme['tags'] if t not in TYPE_TAGS]
    return {
        **scheme,
        'tag_chips': [{'slug': t, 'label': FILTER_LABELS.get(t, t)} for t in tags],
    }


def schemes_list(request):
    """Render the artisan scheme directory.

    Frontend only: the placeholder records above are rendered as-is, and the
    search field / filter chips / sort / saved list are handled on the client.
    No database access happens here yet.
    """
    return render(request, 'schemes/schemes_list.html', {
        'schemes': [_present(scheme) for scheme in SCHEMES],
        'scheme_filters': [
            {**f, 'count': _count_for(f['slug'])} for f in SCHEME_FILTERS
        ],
        'sort_options': SORT_OPTIONS,
        'total_schemes': len(SCHEMES),
        'total_categories': len(SCHEME_FILTERS) - 1,
    })