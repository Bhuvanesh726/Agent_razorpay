from fastapi import Request

from app.auth.principal import Principal


def get_principal(request: Request) -> Principal:
    """SecureAPIRoute has already authenticated and authorized this request
    by the time any endpoint body runs — this just hands back what it
    resolved. Only valid on a route marked @requires(...); a @public route
    never sets request.state.principal, so this would raise AttributeError
    there, on purpose (a public endpoint has no principal to hand back)."""
    return request.state.principal
