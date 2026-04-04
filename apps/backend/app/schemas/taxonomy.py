from pydantic import BaseModel


class TaxonomyItemOut(BaseModel):
    id: int
    name: str
    description: str | None = None


class DescriptionUpdate(BaseModel):
    description: str | None
