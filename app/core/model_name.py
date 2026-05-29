from __future__ import annotations

import re
from typing import Annotated

from pydantic import Field

ModelName = Annotated[str, Field(min_length=1)]


def normalize_model_name(model_name: object) -> str:
    """Return a provider model id, tolerating display-style whitespace."""

    return re.sub(r"\s+", "-", str(model_name).strip())
