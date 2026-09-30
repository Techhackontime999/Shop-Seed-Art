"""Where enhancement artefacts are written, and how they are named.

Two rules, both enforced here rather than left to callers:

* The seller's original is written to its own path and is **never** touched
  again. Every later stage reads from the decoded copy, and a re-run of the
  enhancer writes a new enhanced file rather than replacing the previous one.
* Nothing derived from an untrusted upload is allowed to influence the path.
  Names are generated server-side from the job id, and the caller's filename
  is only ever used as a sanitised, length-capped display hint.
"""

import logging

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone

from ..utils.image_io import safe_extension

logger = logging.getLogger(__name__)

# Deliberately *not* under products/: these are drafts awaiting the seller's
# approval and must not be swept up by anything that lists published media.
ORIGINAL_PREFIX = 'ai-enhancements/originals'
ENHANCED_PREFIX = 'ai-enhancements/enhanced'


class StorageError(Exception):
    """A file could not be written or read back."""


def _dotted(now=None) -> str:
    now = now or timezone.now()
    return now.strftime('%Y/%m/%d')


def _write(path: str, data: bytes) -> str:
    if not data:
        raise StorageError('refusing to write an empty file')
    # save() with an explicit name overwrites; a collision here would mean one
    # seller's draft replacing another's, so the name carries the job id and a
    # random suffix and is therefore not guessable in practice.
    if default_storage.exists(path):
        raise StorageError('refusing to overwrite %s' % path)
    try:
        return default_storage.save(path, ContentFile(data))
    except Exception as exc:
        raise StorageError('could not store image: %s' % exc) from exc


def store_original(data: bytes, extension: str, job_id: str, *, now=None) -> str:
    """Persist the seller's untouched upload. Returns the storage name."""
    path = '%s/%s/%s%s' % (ORIGINAL_PREFIX, _dotted(now), job_id, safe_extension(extension))
    return _write(path, data)


def store_enhanced(data: bytes, image_format: str, job_id: str, attempt: int = 1,
                   *, now=None) -> str:
    """Persist one enhanced result. ``attempt`` keeps retries from colliding."""
    path = '%s/%s/%s-%d%s' % (
        ENHANCED_PREFIX, _dotted(now), job_id, attempt, safe_extension(image_format))
    return _write(path, data)


def delete_quietly(name: str) -> None:
    """Best-effort delete used when a later stage fails and rolls back."""
    if not name:
        return
    try:
        default_storage.delete(name)
    except Exception:
        # A leftover draft is untidy, not dangerous; never let cleanup turn a
        # failed enhancement into a failed request.
        logger.warning('Could not remove %s during rollback', name, exc_info=True)
