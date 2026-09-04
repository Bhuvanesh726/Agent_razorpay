from typing import Literal

from pydantic import BaseModel


class DemoLoginRequest(BaseModel):
    role: Literal["BUYER", "MERCHANT"]


class DemoPrincipalOut(BaseModel):
    role: str
    email: str
    name: str
    description: str


class DemoLoginOptions(BaseModel):
    # False in every non-development environment. The frontend hides the
    # demo buttons on this, but it is not the security boundary — the POST
    # endpoint enforces the gate itself.
    available: bool
    principals: list[DemoPrincipalOut]


class DemoLoginResult(BaseModel):
    token: str
    user_id: str
    email: str
    role: str
