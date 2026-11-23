from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.routes_auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.user_workspace_membership import UserWorkspaceMembership
from app.models.workspace import Workspace

router = APIRouter(prefix="/workspaces")


@router.get("/me")
async def list_my_workspaces(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The workspaces the current user is a member of (id/name/slug/role).

    Deliberately lightweight: the dashboard fetches this once at startup and
    sends the chosen workspace's id in X-Workspace-Id on every workspace-
    scoped request (WhatsApp/Facebook this phase — Instagram routes ignore
    the header entirely). No workspace-switcher UI yet; the dashboard just
    picks the 'default' workspace until multi-workspace selection ships.
    """
    rows = (
        db.query(UserWorkspaceMembership, Workspace)
        .join(Workspace, Workspace.id == UserWorkspaceMembership.workspace_id)
        .filter(UserWorkspaceMembership.user_id == current_user.id)
        .all()
    )
    return [
        {
            "id": str(workspace.id),
            "name": workspace.name,
            "slug": workspace.slug,
            "role": membership.role,
        }
        for membership, workspace in rows
    ]
