"""Where a document's bytes live.

Every key is scoped to a school. S3 has no folders, but a key prefix behaves
like one for the operations that matter: listing what a school holds, deleting
everything belonging to a school that leaves, and reasoning about a stray key
without joining back to the database. A key carries who it belongs to.

    {env}/tenants/{tenant_id}/{owner_kind}/{owner_id}/{unique}_{filename}

The env prefix, sanitising and unique-naming are `shared.s3_utils`' job and are
not reimplemented here — this module only decides the shape of the folder.
"""

from __future__ import annotations

from shared.s3_utils import build_s3_key, sanitize_folder


def tenant_prefix(tenant_id: str) -> str:
    """Everything one school holds. The unit of bulk listing and bulk deletion."""
    return sanitize_folder(f"tenants/{tenant_id}")


def owner_folder(tenant_id: str, owner_kind: str, owner_id: str) -> str:
    """Everything hanging off one owner — a person, an exam paper, a submission."""
    return sanitize_folder(f"tenants/{tenant_id}/{owner_kind}/{owner_id}")


def build_key(
    tenant_id: str, owner_kind: str, owner_id: str, original_filename: str
) -> str:
    """The object key for a new upload.

    Uniqueness comes from `build_s3_key`, so two files of the same name under
    one owner do not collide and an overwrite is never silent.
    """
    return build_s3_key(
        owner_folder(tenant_id, owner_kind, owner_id), original_filename
    )
