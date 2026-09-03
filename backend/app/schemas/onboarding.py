from typing import Literal

from pydantic import BaseModel


class RoleChoice(BaseModel):
    role: Literal["BUYER", "MERCHANT"]


class RoleChoiceResult(BaseModel):
    role: str
    # A fresh JWT carrying the new role claim — the old one still says
    # role=null (or the pre-switch role), so the frontend must swap its
    # stored token for this one immediately, the same way login/callback
    # stores the token it's handed.
    token: str
