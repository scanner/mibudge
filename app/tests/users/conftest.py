from pytest_factoryboy import register

from .factories import UserInvitationFactory

register(
    UserInvitationFactory
)  # UserInvitationFactory -> user_invitation_factory
