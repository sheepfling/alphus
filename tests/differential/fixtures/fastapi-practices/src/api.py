from fastapi import APIRouter as Router

router = Router()


@router.post("/items", status_code=201)
def create_item() -> dict[str, bool]:
    return {"created": True}
