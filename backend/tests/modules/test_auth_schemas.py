import pytest
from pydantic import ValidationError

from app.modules.auth.schemas import AcceptInviteRequest, CreateMemberRequest


@pytest.mark.parametrize("schema", [CreateMemberRequest, AcceptInviteRequest])
def test_password_rejects_more_than_72_utf8_bytes(schema) -> None:
    identity = (
        {"email": "member@example.com"} if schema is CreateMemberRequest else {"token": "token"}
    )
    payload = {
        "password": "é" * 37,
        **identity,
    }

    with pytest.raises(ValidationError, match="72 UTF-8 bytes"):
        schema.model_validate(payload)


@pytest.mark.parametrize("schema", [CreateMemberRequest, AcceptInviteRequest])
def test_password_accepts_exactly_72_utf8_bytes(schema) -> None:
    identity = (
        {"email": "member@example.com"} if schema is CreateMemberRequest else {"token": "token"}
    )
    payload = {
        "password": "é" * 36,
        **identity,
    }

    assert schema.model_validate(payload).password == "é" * 36
