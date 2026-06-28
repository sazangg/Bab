from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.providers.internal import repository
from app.modules.providers.internal.models import ModelOffering, Provider
from app.modules.workspace.internal.models import Organization


async def test_list_model_offerings_filters_and_paginates(db_session: AsyncSession):
    org_id = uuid4()
    provider_id = uuid4()
    other_provider_id = uuid4()
    db_session.add(Organization(id=org_id, name="Default org", slug="default"))
    await db_session.flush()
    db_session.add(
        Provider(
            id=provider_id,
            org_id=org_id,
            name="OpenAI",
            slug="openai",
            base_url="https://api.openai.com/v1",
        )
    )
    db_session.add(
        Provider(
            id=other_provider_id,
            org_id=org_id,
            name="Other",
            slug="other",
            base_url="https://example.com/v1",
        )
    )
    await db_session.flush()
    db_session.add_all(
        [
            ModelOffering(
                org_id=org_id,
                provider_id=provider_id,
                provider_model_name="gpt-5.4-mini",
                modality="text+vision",
                is_active=True,
            ),
            ModelOffering(
                org_id=org_id,
                provider_id=provider_id,
                provider_model_name="gpt-image-2",
                modality="image",
                is_active=True,
            ),
            ModelOffering(
                org_id=org_id,
                provider_id=provider_id,
                provider_model_name="legacy-text",
                modality="text",
                is_active=False,
            ),
            ModelOffering(
                org_id=org_id,
                provider_id=other_provider_id,
                provider_model_name="gpt-5.4-mini",
                modality="text",
                is_active=True,
            ),
        ]
    )
    await db_session.commit()

    offerings, total = await repository.list_model_offerings(
        org_id=org_id,
        provider_id=provider_id,
        search="gpt",
        modalities=["text"],
        is_active=True,
        limit=1,
        offset=0,
        db=db_session,
    )

    assert total == 1
    assert [offering.provider_model_name for offering in offerings] == ["gpt-5.4-mini"]


async def test_list_model_offerings_filters_multiple_modalities(db_session: AsyncSession):
    org_id = uuid4()
    provider_id = uuid4()
    db_session.add(Organization(id=org_id, name="Default org", slug="default"))
    await db_session.flush()
    db_session.add(
        Provider(
            id=provider_id,
            org_id=org_id,
            name="OpenAI",
            slug="openai",
            base_url="https://api.openai.com/v1",
        )
    )
    await db_session.flush()
    db_session.add_all(
        [
            ModelOffering(
                org_id=org_id,
                provider_id=provider_id,
                provider_model_name="text-vision-model",
                modality="text+vision",
                is_active=True,
            ),
            ModelOffering(
                org_id=org_id,
                provider_id=provider_id,
                provider_model_name="embedding-model",
                modality="embedding",
                is_active=True,
            ),
            ModelOffering(
                org_id=org_id,
                provider_id=provider_id,
                provider_model_name="audio-model",
                modality="audio",
                is_active=True,
            ),
        ]
    )
    await db_session.commit()

    offerings, total = await repository.list_model_offerings(
        org_id=org_id,
        provider_id=provider_id,
        search=None,
        modalities=["text", "vision"],
        is_active=True,
        limit=10,
        offset=0,
        db=db_session,
    )

    assert total == 1
    assert [offering.provider_model_name for offering in offerings] == ["text-vision-model"]
