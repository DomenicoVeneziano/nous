# backend/schemas/tag.py
from pydantic import BaseModel, model_validator


class TagOut(BaseModel):
    id: str
    project_id: str
    name: str
    color: str | None
    is_system: bool

    model_config = {"from_attributes": True}


class TagWithCount(TagOut):
    asset_count: int


class TagCreate(BaseModel):
    name: str
    color: str | None = None


class TagUpdate(BaseModel):
    # Both optional: an omitted field is left alone, an explicit null on `color`
    # clears it back to the default chip colour. The router tells the two apart
    # via model_fields_set.
    name: str | None = None
    color: str | None = None


class TagAssign(BaseModel):
    """Attach a tag by id, or by name to create-and-attach in one call."""
    tag_id: str | None = None
    name: str | None = None
    color: str | None = None

    @model_validator(mode="after")
    def _one_selector_only(self):
        # The router resolves tag_id first, so a payload carrying both would
        # attach the existing tag and drop the name and colour on the floor
        # without ever saying so. Refuse the ambiguous request instead.
        if self.tag_id and (self.name is not None or self.color is not None):
            raise ValueError("Provide either tag_id or name, not both")
        return self
