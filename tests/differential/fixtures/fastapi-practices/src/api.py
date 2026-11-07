from fastapi import APIRouter as Router
router = Router()
@router.post('/items', status_code=201)
def create_item():
    return {"created": True}
