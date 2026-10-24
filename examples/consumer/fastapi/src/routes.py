"""Small, import-safe FastAPI application for contract and behavior examples."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel


class Item(BaseModel):
    item_id: int


class ItemService:
    def read(self, item_id: int) -> Item:
        return Item(item_id=item_id)


app = FastAPI()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
service_events: list[str] = []


def require_example_user(token: Annotated[str, Depends(oauth2_scheme)]) -> str:
    if token != "example-token":
        raise HTTPException(status_code=401, detail="not authorized")
    return "example-user"


def get_item_service() -> Iterator[ItemService]:
    service = ItemService()
    service_events.append("open")
    try:
        yield service
    finally:
        service_events.append("close")


@app.get("/items/{item_id}", tags=["items"])
async def read_item(
    item_id: int,
    service: Annotated[ItemService, Depends(get_item_service)],
    user: Annotated[str, Depends(require_example_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Item:
    """Read an item for the authenticated example user."""
    if not user:
        raise HTTPException(status_code=401, detail="not authorized")
    return service.read(item_id)
