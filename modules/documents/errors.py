"""Failures the document store can report, in the vocabulary of the caller."""

from __future__ import annotations


class DocumentError(Exception):
    """Base for everything this module raises."""


class UnknownOwnerKind(DocumentError):
    """No domain registered this kind of owner. Almost always a missing import."""


class OwnerNotFound(DocumentError):
    """The owner does not exist, or belongs to another school."""


class UnknownDocumentType(DocumentError):
    """The type code is not in the catalogue for this owner kind."""


class FileRejected(DocumentError):
    """The file failed the owner kind's rules — size, or an unaccepted format."""


class DocumentNotFound(DocumentError):
    """No such document in this school."""
