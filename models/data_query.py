from typing import List, Optional, Tuple
from pydantic import BaseModel

class DataQueryRequest(BaseModel):
    variables: Optional[List[str]] = None
    time_range: Optional[Tuple[float, float]] = None
    job_id: Optional[int] = None # Deprecated, kept for backward compat
    job_ids: Optional[List[int]] = None # New spec compliant field
    limit: Optional[int] = 2000
