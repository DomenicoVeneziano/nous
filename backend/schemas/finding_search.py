# backend/schemas/finding_search.py
from schemas.finding import FindingOut


class FindingSearchOut(FindingOut):
    asset_hostname: str
