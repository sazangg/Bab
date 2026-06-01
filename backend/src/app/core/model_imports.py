def import_all_models() -> None:
    from app.modules.activity.internal import models as activity_models  # noqa: F401
    from app.modules.auth.internal import models as auth_models  # noqa: F401
    from app.modules.guardrails.internal import models as guardrail_models  # noqa: F401
    from app.modules.keys.internal import models as key_models  # noqa: F401
    from app.modules.policies.internal import models as policy_models  # noqa: F401
    from app.modules.providers.internal import models as provider_models  # noqa: F401
    from app.modules.settings.internal import models as settings_models  # noqa: F401
    from app.modules.usage.internal import models as usage_models  # noqa: F401
