import threading
from dataclasses import dataclass

from localflow.cloud import ToolCall, ToolDefinition
from localflow.tools.open_app import (
    OPEN_APP_DEFINITION,
    AppCatalogue,
    OpenApp,
    OpenAppError,
    validate_open_app,
)


@dataclass(frozen=True)
class Tool:
    definition: ToolDefinition
    validator: object
    handler: object


class ToolRegistry:
    def __init__(self, tools):
        self.tools = {tool.definition.name: tool for tool in tools}

    @property
    def definitions(self):
        return tuple(tool.definition for tool in self.tools.values())

    def dispatch(self, call: ToolCall):
        try:
            tool = self.tools[call.name]
        except KeyError:
            raise ValueError("Unknown command tool.") from None
        request = tool.validator(call.arguments)
        return tool.handler(request)


def build_builtin_registry(
    shutdown_event: threading.Event, app_aliases=(), report=print
):
    catalogue = AppCatalogue.discover(app_aliases=app_aliases)
    for error in catalogue.alias_errors:
        report(f"Application alias ignored: {error}.")
    return ToolRegistry(
        (
            Tool(
                OPEN_APP_DEFINITION,
                validate_open_app,
                OpenApp(catalogue, shutdown_event),
            ),
        )
    )
