from app.modules.authorization.schemas import AuthorizationDecision


class AuthorizationDeniedError(Exception):
    def __init__(self, decision: AuthorizationDecision):
        super().__init__(decision.reason_code)
        self.decision = decision
