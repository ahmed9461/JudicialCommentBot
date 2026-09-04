class PdfAcquisitionError(RuntimeError):
    """Base PDF acquisition error."""


class PdfSecurityError(PdfAcquisitionError):
    """The remote URL failed network/source safety rules."""


class PdfValidationError(PdfAcquisitionError):
    """Downloaded bytes are not a valid acceptable PDF."""
