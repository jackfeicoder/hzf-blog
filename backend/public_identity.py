"""Public profile identifiers are separate from privileged login names."""
ADMIN_LOGIN = "jackfei"
ADMIN_ALIAS = "administrator"
ADMIN_LABEL = "管理员"


def internal_username(value):
    return ADMIN_LOGIN if value == ADMIN_ALIAS else value


def public_name(user):
    return ADMIN_LABEL if user.username == ADMIN_LOGIN else user.nickname or user.username


def public_reference(value):
    return value.replace(ADMIN_LOGIN, ADMIN_LABEL) if value else value
