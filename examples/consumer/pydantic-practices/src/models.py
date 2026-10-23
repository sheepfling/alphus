"""Example public Pydantic models for an Alphus consumer profile."""

from pydantic import BaseModel, Field, field_validator, validator


class PublicRequest(BaseModel):
    """Create a catalog item from validated client input."""

    name: str = Field(description="Name shown in the catalog")
    quantity: int = Field(0)

    @field_validator("name")
    @classmethod
    def require_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        # Intentional violation for the example: this path falls through.

    @validator("quantity")
    def nonnegative_quantity(cls, value: int) -> int:
        if value < 0:
            raise ValueError("quantity must be nonnegative")
        return value


def normalize_request(
    payload: object, request: PublicRequest
) -> tuple[PublicRequest, PublicRequest]:
    """Show validation-sensitive APIs that the profile reports for review."""
    constructed = PublicRequest.model_construct(name=payload, quantity=-1)
    copied = request.model_copy(update={"quantity": payload})
    return constructed, copied
