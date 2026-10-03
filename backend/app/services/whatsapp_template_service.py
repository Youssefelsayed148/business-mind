from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.integrations.meta.whatsapp_management_client import (
    WhatsappManagementClient,
    WhatsappManagementResult,
)
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_campaign import WhatsappCampaign
from app.models.whatsapp_template import WhatsappTemplate


_NAME = re.compile(r"^[a-z0-9_]{1,512}$")
_VARIABLE = re.compile(r"{{\s*(\d+)\s*}}")
_CATEGORIES = {"marketing", "utility", "authentication"}
_FINISHED_CAMPAIGNS = {"completed", "cancelled", "failed"}


class TemplateValidationError(ValueError):
    pass


class TemplateInUseError(ValueError):
    pass


@dataclass(frozen=True)
class TemplateSyncResult:
    success: bool
    created: int = 0
    updated: int = 0
    error_message: str | None = None


def _template_placeholders(template: WhatsappTemplate) -> set[int]:
    placeholders: set[int] = set()
    for component in template.components:
        if str(component.get("type", "")).lower() in {"header", "body"}:
            placeholders.update(
                int(value) for value in _VARIABLE.findall(str(component.get("text", "")))
            )
    return placeholders


def _variable_map(variables: list[object] | tuple[object, ...] | dict) -> dict[int, object]:
    if isinstance(variables, (list, tuple)):
        return {index: value for index, value in enumerate(variables, start=1)}
    if isinstance(variables, dict):
        try:
            return {int(key): value for key, value in variables.items()}
        except (TypeError, ValueError) as exc:
            raise TemplateValidationError("template_variable_keys_invalid") from exc
    raise TemplateValidationError("template_variables_invalid")


def validate_template_variables(
    template: WhatsappTemplate,
    variables: list[object] | tuple[object, ...] | dict,
) -> None:
    placeholders = _template_placeholders(template)
    if placeholders and placeholders != set(range(1, max(placeholders) + 1)):
        raise TemplateValidationError("template_variables_not_sequential")
    values = _variable_map(variables)
    if set(values) != placeholders:
        raise TemplateValidationError("template_variable_count_mismatch")
    if any(value is None or (isinstance(value, str) and not value.strip()) for value in values.values()):
        raise TemplateValidationError("template_variable_value_empty")


def render_template_components(
    template: WhatsappTemplate,
    variables: list[object] | tuple[object, ...] | dict,
) -> list[dict]:
    validate_template_variables(template, variables)
    values = _variable_map(variables)
    rendered: list[dict] = []
    for component in template.components:
        component_type = str(component.get("type", "")).lower()
        if component_type not in {"header", "body"}:
            continue
        placeholders = sorted(
            {int(value) for value in _VARIABLE.findall(str(component.get("text", "")))}
        )
        if placeholders:
            rendered.append(
                {
                    "type": component_type,
                    "parameters": [
                        {"type": "text", "text": str(values[index])}
                        for index in placeholders
                    ],
                }
            )
    return rendered


def validate_for_campaign(template: WhatsappTemplate) -> None:
    if template.category == "authentication":
        raise TemplateValidationError("template_category_unsupported")


def _validate(name: str, category: str, components: list[dict]) -> None:
    if not _NAME.fullmatch(name):
        raise TemplateValidationError("template_name_invalid")
    if category not in _CATEGORIES:
        raise TemplateValidationError("template_category_invalid")
    variables: set[int] = set()
    example_values = 0
    for component in components:
        variables.update(int(value) for value in _VARIABLE.findall(str(component.get("text", ""))))
        examples = component.get("example")
        if isinstance(examples, dict):
            example_values += sum(len(value) for value in examples.values() if isinstance(value, list))
    if variables and variables != set(range(1, max(variables) + 1)):
        raise TemplateValidationError("template_variables_not_sequential")
    if variables and example_values < len(variables):
        raise TemplateValidationError("template_variable_examples_required")


def create_draft(
    db: Session,
    *,
    account: WhatsappAccount,
    name: str,
    language: str,
    category: str,
    components: list[dict],
) -> WhatsappTemplate:
    category = category.lower()
    _validate(name, category, components)
    template = WhatsappTemplate(
        workspace_id=account.workspace_id,
        whatsapp_account_id=account.id,
        name=name,
        language=language,
        category=category,
        components=components,
        status="draft",
    )
    db.add(template)
    db.flush()
    return template


def submit(
    db: Session,
    *,
    template: WhatsappTemplate,
    account: WhatsappAccount,
    access_token: str,
    client: WhatsappManagementClient | None = None,
) -> WhatsappManagementResult:
    _validate(template.name, template.category, template.components)
    owns_client = client is None
    client = client or WhatsappManagementClient()
    try:
        result = client.create_template(
            access_token,
            account.whatsapp_business_account_id or "",
            template.name,
            template.language,
            template.category.upper(),
            template.components,
        )
    finally:
        if owns_client:
            client.close()
    if getattr(result, "success", False):
        template.status = "pending"
        if isinstance(result.data, dict):
            template.meta_template_id = result.data.get("id")
        db.flush()
    return result


def sync_status(template: WhatsappTemplate, meta_row: dict) -> WhatsappTemplate:
    status = str(meta_row.get("status", "")).lower()
    if status in {"pending", "approved", "rejected", "paused", "disabled"}:
        template.status = status
    template.rejection_reason = meta_row.get("rejected_reason") or meta_row.get("rejection_reason")
    template.quality_score = meta_row.get("quality_score")
    template.last_synced_at = datetime.now(timezone.utc)
    return template


def sync_templates(
    db: Session,
    *,
    account: WhatsappAccount,
    access_token: str,
    client: WhatsappManagementClient | None = None,
) -> TemplateSyncResult:
    owns_client = client is None
    client = client or WhatsappManagementClient()
    try:
        result = client.list_templates(
            access_token, account.whatsapp_business_account_id or ""
        )
    finally:
        if owns_client:
            client.close()
    if not result.success:
        return TemplateSyncResult(False, error_message=result.error_message)

    created = updated = 0
    rows = result.data if isinstance(result.data, list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        language = row.get("language")
        if not isinstance(name, str) or not isinstance(language, str):
            continue
        template = (
            db.query(WhatsappTemplate)
            .filter(
                WhatsappTemplate.whatsapp_account_id == account.id,
                WhatsappTemplate.name == name,
                WhatsappTemplate.language == language,
            )
            .first()
        )
        if template is None:
            category = str(row.get("category", "utility")).lower()
            if category not in _CATEGORIES:
                category = "utility"
            template = WhatsappTemplate(
                workspace_id=account.workspace_id,
                whatsapp_account_id=account.id,
                name=name,
                language=language,
                category=category,
                components=row.get("components") if isinstance(row.get("components"), list) else [],
                status="pending",
            )
            db.add(template)
            db.flush()
            created += 1
        else:
            if str(row.get("category", "")).lower() in _CATEGORIES:
                template.category = str(row["category"]).lower()
            if isinstance(row.get("components"), list):
                template.components = row["components"]
            updated += 1
        if row.get("id") is not None:
            template.meta_template_id = str(row["id"])
        sync_status(template, row)
    db.flush()
    return TemplateSyncResult(True, created=created, updated=updated)


def delete_template_by_name(
    db: Session,
    *,
    account: WhatsappAccount,
    name: str,
    access_token: str,
    client: WhatsappManagementClient | None = None,
) -> WhatsappManagementResult:
    db.flush()
    referenced = (
        db.query(WhatsappCampaign.id)
        .join(WhatsappTemplate, WhatsappTemplate.id == WhatsappCampaign.template_id)
        .filter(
            WhatsappCampaign.whatsapp_account_id == account.id,
            WhatsappTemplate.name == name,
            WhatsappCampaign.status.notin_(_FINISHED_CAMPAIGNS),
        )
        .first()
    )
    if referenced:
        raise TemplateInUseError("template_in_use_by_active_campaign")
    owns_client = client is None
    client = client or WhatsappManagementClient()
    try:
        result = client.delete_template_by_name(
            access_token, account.whatsapp_business_account_id or "", name
        )
    finally:
        if owns_client:
            client.close()
    if getattr(result, "success", False):
        rows = (
            db.query(WhatsappTemplate)
            .filter(
                WhatsappTemplate.whatsapp_account_id == account.id,
                WhatsappTemplate.name == name,
            )
            .all()
        )
        for template in rows:
            template.status = "deleted"
        db.flush()
    return result
