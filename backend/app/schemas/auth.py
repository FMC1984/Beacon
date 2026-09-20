from datetime import datetime

from pydantic import BaseModel


class LoginIn(BaseModel):
    email: str
    password: str


class MembershipOut(BaseModel):
    organization_id: int
    organization_name: str
    organization_slug: str
    role: str
    sample_data: bool = False


class UserOut(BaseModel):
    id: int
    email: str
    name: str | None
    is_platform_admin: bool
    last_login_at: datetime | None = None


class OrgOut(BaseModel):
    id: int
    name: str
    slug: str
    role: str
    sample_data: bool = False


class MeOut(BaseModel):
    user: UserOut | None
    via: str
    is_platform_admin: bool
    org: OrgOut | None
    memberships: list[MembershipOut]
    organizations: list[OrgOut] = []


class LoginOut(MeOut):
    token: str


class InviteCreate(BaseModel):
    organization_id: int
    email: str
    role: str


class InviteOut(BaseModel):
    invite_id: int
    email: str
    role: str
    organization_id: int
    link: str
    expires_at: datetime
    delivered: bool
    delivery_note: str


class InvitePublic(BaseModel):
    organization_name: str
    email: str
    role: str
    state: str
    existing_user: bool


class InviteAccept(BaseModel):
    name: str | None = None
    password: str


class ResetRequest(BaseModel):
    email: str


class ResetConfirm(BaseModel):
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class MemberOut(BaseModel):
    user_id: int
    email: str
    name: str | None
    role: str
    last_login_at: datetime | None


class PendingInviteOut(BaseModel):
    invite_id: int
    email: str
    role: str
    expires_at: datetime


class MembersOut(BaseModel):
    organization_id: int
    members: list[MemberOut]
    pending_invites: list[PendingInviteOut]


class RoleChange(BaseModel):
    role: str
