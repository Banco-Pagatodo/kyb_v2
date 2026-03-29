from enum import Enum
class DocFormat(str, Enum):
    """Possible values for document formats"""
    jpeg = "image/jpeg"
    png = "image/png"
    pdf = "application/pdf"