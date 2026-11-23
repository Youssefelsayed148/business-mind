"""Architecture checks over production code, including future routes/callers."""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def test_template_send_has_exactly_one_production_caller():
    callers = []
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and (
                    isinstance(node.func, ast.Attribute) and node.func.attr == "send_template_message"
                    or isinstance(node.func, ast.Name) and node.func.id == "send_template_message"
                ):
                    callers.append((path.relative_to(APP).as_posix(), function.name))
    assert callers == [("services/outreach_service.py", "send_outreach_message")]


def test_every_outreach_route_declares_permission_dependency():
    tree = ast.parse((APP / "api/routes_whatsapp_outreach.py").read_text(encoding="utf-8"))
    routes = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = [d for d in node.decorator_list if isinstance(d, ast.Call)
                      and isinstance(d.func, ast.Attribute) and d.func.attr in {"get", "post", "patch", "delete"}]
        if not decorators:
            continue
        routes.append(node.name)
        calls = [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "Depends"]
        if node.name == "public_opt_in":
            # Public capability authorization: signed JWT, no user login dependency.
            assert any(c.args and isinstance(c.args[0], ast.Name)
                       and c.args[0].id == "_public_opt_in_permission" for c in calls)
            continue
        dependencies = [c.args[0] for c in calls if c.args and isinstance(c.args[0], ast.Call)]
        assert any(isinstance(d.func, ast.Name) and d.func.id in {
            "require_workspace_permission", "require_workspace_any_permission", "require_workspace_role"
        } for d in dependencies), node.name
        for dep in dependencies:
            if isinstance(dep.func, ast.Name) and dep.func.id == "require_workspace_role":
                assert {ast.literal_eval(a) for a in dep.args} == {"owner", "admin"}, node.name
    assert len(routes) == 29  # Review matrix must expand if routes are added.


def test_consent_mutations_and_events_belong_to_consent_service():
    fields = {"marketing_consent", "consent_source", "consent_at", "opted_out_at"}
    violations = []
    for path in APP.rglob("*.py"):
        if path.name == "whatsapp_consent_service.py" or "models" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets = node.targets if isinstance(node, ast.Assign) else ([node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else [])
            if any(isinstance(t, ast.Attribute) and t.attr in fields for t in targets):
                violations.append((str(path), node.lineno))
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            if name == "WhatsappConsentEvent":
                violations.append((str(path), node.lineno))
            if name == "setattr" and len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and node.args[1].value in fields:
                violations.append((str(path), node.lineno))
            # Neutral contact creation is allowed; granting or revoking is a service write.
            for kw in node.keywords:
                if kw.arg in fields and not (name == "WhatsappContact" and kw.arg == "marketing_consent"
                    and isinstance(kw.value, ast.Constant) and kw.value.value == "unknown"):
                    violations.append((str(path), node.lineno))
    assert violations == []
