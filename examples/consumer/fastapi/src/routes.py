"""Small source fixture for a valid FastAPI route profile."""

from typing import Annotated

from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel


class Item(BaseModel):
    item_id: int


class ItemService:
    def read(self, item_id: int) -> Item:
        return Item(item_id=item_id)


def get_item_service() -> ItemService:
    return ItemService()


app = FastAPI()


@app.get("/items/{item_id}")
async def read_item(
    item_id: int,
    service: Annotated[ItemService, Depends(get_item_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Item:
    """Read an item with typed dependencies."""
    return service.read(item_id)
