"""CKEditor plumbing: the ``Media`` renderer fix and a fluid-width widget.

Two independent problems live here.

**1. ``Media.render_js()`` truncates ``js_asset.JS`` paths (django-ckeditor 6).**
django-ckeditor declares its init script as a ``js_asset.JS`` so the
``data-ckeditor-basepath`` attribute (which the form-media tags cannot express)
travels with the path. Django's ``Media.render_js()`` short-circuits on any path
defining ``__html__()`` and emits the result verbatim, but ``js_asset.JS``'s
``__html__()`` returns only the *inner* fragment that its own ``{% js_asset %}``
template tag wraps in ``<script src="..."></script>``. Rendered through
``{{ form.media }}`` the tag therefore comes out truncated::

    /static/ckeditor/ckeditor-init.js" data-ckeditor-basepath="..." id="ckeditor-init-script

The browser never fetches ``ckeditor-init.js``, ``CKEDITOR_BASEPATH`` is never
set, and every rich-text field degrades to a plain ``<textarea>``. Patching the
renderer once at start-up fixes every consumer at the same time — the seller
product forms, any ModelForm over a ``RichTextField``, and the admin — instead
of re-declaring the widget's ``Media`` in each of them.

**2. CKEditor sizes itself in pixels.** It measures the textarea once and writes
the result onto the chrome as an inline pixel width, so the editor keeps the
width it had at load time and overflows a phone-sized column.
``ResponsiveCKEditorWidget`` opts into a percentage width and points CKEditor at
a stylesheet for the WYSIWYG document, which is a separate page that inherits
nothing from the surrounding template.
"""

from django.forms.utils import flatatt
from django.forms.widgets import Media
from django.templatetags.static import static
from django.utils.html import format_html

try:
    from js_asset import JS
except ImportError:  # pragma: no cover - js_asset ships with django-ckeditor
    JS = None


def _render_js(self):
    """Emit one complete ``<script>`` tag per path, attributes included."""
    tags = []
    for path in self._js:
        if JS is not None and isinstance(path, JS) and path.attrs:
            tags.append(format_html(
                '<script src="{}"{}></script>',
                self.absolute_path(path.js),
                flatatt(path.attrs),
            ))
        elif hasattr(path, '__html__'):
            tags.append(path.__html__())
        else:
            tags.append(format_html(
                '<script src="{}"></script>', self.absolute_path(path),
            ))
    return tags


def patch_media_renderer():
    """Install the fix. Idempotent, and a no-op without django-js-asset."""
    if JS is None:
        return
    if Media.render_js is not _render_js:
        Media.render_js = _render_js


def _build_responsive_richtext():
    """Build the responsive widget and form-field callback.

    Imported lazily because ``core`` is the first entry in ``INSTALLED_APPS``, so
    ``ckeditor`` is not importable yet while this module is being loaded.
    """
    from ckeditor.fields import RichTextFormField
    from ckeditor.widgets import CKEditorWidget

    class ResponsiveCKEditorWidget(CKEditorWidget):
        """CKEditor that fills its column and adapts on small screens.

        ``width: '100%'`` hands sizing over to CSS (see
        ``css/ckeditor-responsive.css``). ``height`` is a minimum, so the pane
        keeps CKEditor's default height on desktop and grows once it is dragged
        open. ``contentsCss`` is resolved here rather than in settings because
        it has to go through the configured static files storage, which in
        production appends a content hash.
        """

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.config.update({
                'width': '100%',
                'height': 320,
                'resize_enabled': True,
                'contentsCss': static('css/ckeditor-content.css'),
            })

    def responsive_richtext(model_field, **kwargs):
        """``ModelForm.Meta.formfield_callback`` giving fluid rich-text fields.

        The callback is handed a *model* field and must return the form field,
        so every field — rich-text or not — is built here.

        django-ckeditor's ``RichTextFormField.__init__`` overwrites
        ``kwargs['widget']`` with a freshly built ``CKEditorWidget``, so a
        ``Meta.widgets`` entry naming a widget is silently thrown away. That is
        why the seller description editors kept CKEditor's built-in 835px width
        however the form was declared: the widget has to be swapped once the
        form field exists.
        """
        form_field = model_field.formfield(**kwargs)
        if not isinstance(form_field, RichTextFormField):
            return form_field
        if not isinstance(form_field.widget, ResponsiveCKEditorWidget):
            form_field.widget = ResponsiveCKEditorWidget(
                config_name=model_field.config_name,
                extra_plugins=model_field.extra_plugins,
                external_plugin_resources=model_field.external_plugin_resources,
            )
        return form_field

    return ResponsiveCKEditorWidget, responsive_richtext


ResponsiveCKEditorWidget, responsive_richtext = _build_responsive_richtext()
