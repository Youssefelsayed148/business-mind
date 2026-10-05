import ast
from pathlib import Path


def test_send_template_message_has_no_unapproved_application_callers():
    app_root = Path(__file__).resolve().parents[1] / "app"
    violations = []

    for path in app_root.rglob("*.py"):
        if path.name in {"whatsapp_client.py", "outreach_service.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported = isinstance(node, (ast.Import, ast.ImportFrom)) and any(
                alias.name == "send_template_message" for alias in node.names
            )
            referenced = (
                isinstance(node, ast.Attribute) and node.attr == "send_template_message"
            ) or (isinstance(node, ast.Name) and node.id == "send_template_message")
            if imported or referenced:
                violations.append(f"{path.relative_to(app_root)}:{node.lineno}")

    assert violations == [], f"send_template_message has unapproved callers: {violations}"
