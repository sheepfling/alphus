"""Negative source fixture for the FastAPI Ruff profile."""

import math
import time
from pathlib import Path

import requests
from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel


class Item(BaseModel):
    item_id: int


def get_item() -> Item:
    return Item(item_id=1)


def make_values() -> list[int]:
    return []


def repeated_default(values: list[int] = make_values()) -> list[int]:
    return values


def untyped(value):
    return value


def unsafe_query(database: object, item_id: int) -> None:
    database.execute(f"SELECT * FROM items WHERE id = {item_id}")


app = FastAPI()


@app.get("/items/{item_id}", response_model=Item)
async def read_item(item: Item = Depends(get_item), query: str = Query("")) -> Item:
    """Deliberately demonstrate unsafe endpoint patterns."""
    requests.get("https://example.com", verify=False)
    time.sleep(0.1)
    with open("payload.json") as payload:
        payload.read()
    Path("payload.json").read_text()
    return item
