from __future__ import annotations

from typing import Annotated

from pydantic import Field

ModelName = Annotated[str, Field(min_length=1)]
