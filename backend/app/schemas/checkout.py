from pydantic import BaseModel


class CheckoutInitiateRequest(BaseModel):
    session_id: str
