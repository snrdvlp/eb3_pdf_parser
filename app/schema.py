from pydantic import BaseModel
from typing import Optional

class ExtractResp(BaseModel):
    result_json: dict
    matched_sample_id: Optional[str] = None
    matched_sample_carrier: Optional[str] = None
    matched_sample_plan: Optional[str] = None