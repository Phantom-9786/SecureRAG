from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field, SecretStr

from app.api.dependencies import Database, require_origin
from app.core.config import get_settings
from app.core.security import issue_token, set_auth_cookies, signing_key
from app.schemas.identity import InputModel, Profile
from app.services import google_auth
from app.services.authorization import profile

router = APIRouter(prefix="/auth/google", tags=["Google authentication"])


class GoogleCredential(InputModel):
    credential: Annotated[SecretStr, Field(min_length=1, max_length=16384)]


@router.get("/config")
def config():
    client_id = get_settings().google_client_id
    return {"enabled": bool(client_id), "client_id": client_id}


@router.post("/challenge", dependencies=[Depends(require_origin)])
def challenge(db: Database, response: Response):
    settings = get_settings()
    google_auth.require_google(settings)
    signing_key(settings)
    cookie, nonce = google_auth.create_challenge(db)
    response.set_cookie(
        google_auth.challenge_cookie(settings),
        cookie,
        max_age=300,
        path="/",
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
    )
    return {"nonce": nonce}


@router.post("", response_model=Profile, dependencies=[Depends(require_origin)])
def google_login(body: GoogleCredential, request: Request, db: Database, response: Response):
    settings = get_settings()
    client_id = google_auth.require_google(settings)
    signing_key(settings)
    cookie = request.cookies.get(google_auth.challenge_cookie(settings))
    if not cookie or not 32 <= len(cookie) <= 256:
        raise HTTPException(401, "Google sign-in expired. Please try again.")
    # No database transaction is held during Google's certificate verification.
    identity = google_auth.verify_google_credential(body.credential.get_secret_value(), client_id)
    user = google_auth.sign_in_google(db, identity, cookie)
    token, csrf = issue_token(user.id, user.token_version, settings)
    result = profile(db, user, csrf)
    db.commit()
    response.delete_cookie(
        google_auth.challenge_cookie(settings),
        path="/",
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
    )
    set_auth_cookies(response, token, csrf, settings)
    return result
