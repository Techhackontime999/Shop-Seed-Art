"""Admin for enhancement jobs.

Useful for support ("what happened to this seller's photo?") and for keeping
an eye on the failure rate of a provider change. The images are deliberately
read-only links rather than inline previews: the originals can be large, and
nothing about them should be editable from the admin.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import ImageEnhancementJob


@admin.register(ImageEnhancementJob)
class ImageEnhancementJobAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'seller', 'status', 'provider', 'background', 'selection',
        'created_at', 'files',
    )
    list_filter = ('status', 'provider', 'background', 'selection', 'is_ai')
    search_fields = ('id', 'seller__username', 'seller__email')
    readonly_fields = (
        'id', 'seller', 'created_at', 'updated_at', 'stages',
        'quality', 'provider', 'is_ai', 'duration_summary', 'file_links',
    )
    ordering = ('-created_at',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('seller')

    @admin.display(description='Files')
    def files(self, obj):
        return 'original + enhanced' if obj.has_enhanced else 'original only'

    @admin.display(description='Images')
    def file_links(self, obj):
        links = []
        if obj.original:
            links.append(format_html('<a href="{}" target="_blank">original</a>',
                                     obj.original.url))
        if obj.enhanced:
            links.append(format_html('<a href="{}" target="_blank">enhanced</a>',
                                     obj.enhanced.url))
        return ' &middot; '.join(links) or '-'

    @admin.display(description='Stages')
    def duration_summary(self, obj):
        total = sum(s.get('duration_ms', 0) for s in (obj.stages or []))
        return '%d stages, %d ms' % (len(obj.stages or []), total)
