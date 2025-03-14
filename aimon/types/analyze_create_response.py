# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional

from .._models import BaseModel

__all__ = ["AnalyzeCreateResponse"]


class AnalyzeCreateResponse(BaseModel):
    message: Optional[str] = None

    status: Optional[int] = None
    """Status code representing the outcome of the operation"""
