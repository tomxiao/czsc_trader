from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from factor_signal_catalog import CatalogRegistry, CatalogValidationError
from strategy_template_catalog import TemplateRegistry, TemplateValidationError

from .context import RepositoryContext
from .errors import ValidationError
from .results import CommandResult


def _registry(context: RepositoryContext) -> TemplateRegistry:
    try:
        return TemplateRegistry(context.root / "strategy_templates")
    except TemplateValidationError as exc:
        raise ValidationError(
            "strategy_template_catalog_invalid",
            str(exc),
            context={"path": str(context.root / "strategy_templates")},
        ) from exc


def validate_templates(context: RepositoryContext) -> CommandResult:
    registry = _registry(context)
    return CommandResult(
        status="PASS",
        command="template.validate",
        result={
            "digest": registry.digest,
            "templates": len(registry.templates),
            "operators": dict(
                sorted(Counter(item.operator.value for item in registry.templates).items())
            ),
            "statuses": dict(
                sorted(Counter(item.status.value for item in registry.templates).items())
            ),
        },
    )


def list_templates(
    context: RepositoryContext,
    *,
    operator: str | None,
    status: str | None,
    query: str | None,
) -> CommandResult:
    registry = _registry(context)
    try:
        rows = registry.list_templates(operator=operator, status=status, query=query)
    except TemplateValidationError as exc:
        raise ValidationError("strategy_template_catalog_query_invalid", str(exc)) from exc
    return CommandResult(
        status="PASS",
        command="template.list",
        result={"digest": registry.digest, "count": len(rows), "templates": rows},
    )


def show_template(context: RepositoryContext, template_id: str) -> CommandResult:
    registry = _registry(context)
    try:
        template = registry.show(template_id)
    except TemplateValidationError as exc:
        raise ValidationError("strategy_template_not_found", str(exc)) from exc
    return CommandResult(
        status="PASS",
        command="template.show",
        result={"digest": registry.digest, "template": template},
    )


def instantiate_template(context: RepositoryContext, spec_path: Path) -> CommandResult:
    registry = _registry(context)
    path = Path(spec_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "strategy_template_instance_unreadable",
            f"cannot read template instance spec {path}: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise ValidationError(
            "strategy_template_instance_invalid",
            "template instance spec must be an object",
        )
    expected = {"schema_version", "template_id", "bindings", "parameters"}
    if payload.get("schema_version") != 1 or set(payload) != expected:
        raise ValidationError(
            "strategy_template_instance_invalid",
            "template instance spec requires exactly schema_version 1, template_id, bindings and parameters",
        )
    if not isinstance(payload["bindings"], list) or not isinstance(payload["parameters"], dict):
        raise ValidationError(
            "strategy_template_instance_invalid",
            "bindings must be an array and parameters must be an object",
        )
    try:
        instance = registry.instantiate(
            str(payload["template_id"]),
            payload["bindings"],
            payload["parameters"],
        )
    except TemplateValidationError as exc:
        raise ValidationError("strategy_template_instance_invalid", str(exc)) from exc
    try:
        source_catalog = CatalogRegistry(context.root / "catalog")
        template = registry.get(instance.template_id)
        slot_roles = {item.name: item.role for item in template.input_slots}
        for binding in instance.bindings:
            definition = source_catalog.show(binding.source_id)
            if definition["status"] == "DEPRECATED":
                raise TemplateValidationError(
                    f"deprecated FSC source cannot be bound: {binding.source_id}"
                )
            actual_kind = str(definition["kind"]).upper()
            if actual_kind != binding.source_kind.value:
                raise TemplateValidationError(
                    f"binding {binding.source_id} declares {binding.source_kind.value}, "
                    f"but FSC defines {actual_kind}"
                )
            if actual_kind == "FACTOR" and binding.state is not None:
                raise TemplateValidationError(
                    f"factor binding must not declare a state: {binding.source_id}"
                )
            if actual_kind == "SIGNAL" and slot_roles[binding.slot] != "REGIME":
                if binding.state is None:
                    raise TemplateValidationError(
                        f"signal binding requires a selected state: {binding.source_id}"
                    )
                states = tuple(definition.get("states", ()))
                if states and binding.state not in states:
                    raise TemplateValidationError(
                        f"signal state is not declared by FSC: {binding.source_id}={binding.state}"
                    )
    except (CatalogValidationError, TemplateValidationError) as exc:
        raise ValidationError("strategy_template_binding_invalid", str(exc)) from exc
    return CommandResult(
        status="PASS",
        command="template.instantiate",
        result={"catalog_digest": registry.digest, "instance": instance.to_dict()},
    )
