# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Home Assistant compatibility layer for live HA environments and standalone pytest.

Provides imports from homeassistant.* when installed, and functional lightweight
fallback classes and helpers when homeassistant is not installed in the environment.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Generic, TypeVar

_LOGGER = logging.getLogger(__name__)

# --- Voluptuous Schema Fallback ---
try:
    import voluptuous as vol
except ImportError:

    class _VolUndefined:
        pass

    UNDEFINED = _VolUndefined()

    class Invalid(Exception):
        """Voluptuous Invalid exception fallback."""

    class MultipleInvalid(Invalid):
        """Voluptuous MultipleInvalid exception fallback."""

    class Marker:
        """Marker base class."""

        def __init__(
            self,
            schema: Any,
            msg: str | None = None,
            default: Any = UNDEFINED,
            description: Any = None,
        ) -> None:
            self.schema = schema
            self.msg = msg
            self.default = default
            self.description = description

        def __str__(self) -> str:
            return str(self.schema)

        def __repr__(self) -> str:
            return f"{self.__class__.__name__}({self.schema!r})"

        def __hash__(self) -> int:
            return hash(self.schema)

        def __eq__(self, other: Any) -> bool:
            if isinstance(other, Marker):
                return bool(self.schema == other.schema)
            return bool(self.schema == other)

    class Required(Marker):
        """Required field marker."""

    class Optional(Marker):
        """Optional field marker."""

    class In:
        """Value membership validator."""

        def __init__(self, container: Any, msg: str | None = None) -> None:
            self.container = container
            self.msg = msg

        def __call__(self, value: Any) -> Any:
            if value not in self.container:
                raise Invalid(self.msg or f"Value {value} is not in {self.container}")
            return value

    class Coerce:
        """Type coercion validator."""

        def __init__(self, type_func: Callable[[Any], Any], msg: str | None = None) -> None:
            self.type_func = type_func
            self.msg = msg

        def __call__(self, value: Any) -> Any:
            try:
                return self.type_func(value)
            except (ValueError, TypeError) as err:
                raise Invalid(self.msg or str(err)) from err

    class Schema:
        """Lightweight Schema validator."""

        def __init__(self, schema: Any, extra: int = 0) -> None:
            self.schema = schema
            self.extra = extra

        def __call__(self, data: Any) -> Any:
            if not isinstance(self.schema, dict):
                return data
            if not isinstance(data, dict):
                raise Invalid("Expected dictionary data")

            result: dict[str, Any] = dict(data)

            for marker, validator in self.schema.items():
                key = marker.schema if isinstance(marker, Marker) else marker
                is_required = isinstance(marker, Required)
                has_default = isinstance(marker, Marker) and marker.default is not UNDEFINED

                if key not in result:
                    if has_default:
                        result[key] = (
                            marker.default() if callable(marker.default) else marker.default
                        )
                    elif is_required:
                        raise Invalid(f"Missing required field: {key}")
                elif callable(validator) and not isinstance(validator, type):
                    result[key] = validator(result[key])

            return result

    class _VolModule:
        Schema = Schema
        Required = Required
        Optional = Optional
        In = In
        Coerce = Coerce
        Invalid = Invalid
        MultipleInvalid = MultipleInvalid
        UNDEFINED = UNDEFINED

    vol = _VolModule()


# --- Home Assistant Core & Helpers Fallback ---
try:
    from homeassistant.config_entries import (
        ConfigEntry,
        ConfigFlow,
        OptionsFlow,
    )
    from homeassistant.core import HomeAssistant, ServiceCall, callback
    from homeassistant.data_entry_flow import FlowResult
    from homeassistant.helpers.entity import DeviceInfo, Entity
    from homeassistant.helpers.update_coordinator import (
        CoordinatorEntity,
        DataUpdateCoordinator,
        UpdateFailed,
    )

    try:
        from homeassistant.const import Platform
    except ImportError:

        class Platform(StrEnum):
            SENSOR = "sensor"
            SWITCH = "switch"
            SELECT = "select"
            BUTTON = "button"

    try:
        from homeassistant.helpers.storage import Store
    except ImportError:

        class Store:  # type: ignore[no-redef]
            """In-memory Store stand-in; persisted per hass.data for the process."""

            def __init__(self, hass: Any, version: int, key: str, **_kw: Any) -> None:
                self.hass = hass
                self.version = version
                self.key = key

            def _bucket(self) -> dict[str, Any]:
                return self.hass.data.setdefault("_compat_store", {})

            async def async_load(self) -> Any:
                import copy

                return copy.deepcopy(self._bucket().get(self.key))

            async def async_save(self, data: Any) -> None:
                import copy

                self._bucket()[self.key] = copy.deepcopy(data)

    try:
        from homeassistant.components.http import StaticPathConfig
    except ImportError:

        @dataclass
        class StaticPathConfig:
            url_path: str
            path: str
            cache_headers: bool = True

    try:
        from homeassistant.components.sensor import SensorEntity
    except ImportError:
        SensorEntity = Entity  # type: ignore[misc, assignment]

    try:
        from homeassistant.components.switch import SwitchEntity
    except ImportError:
        SwitchEntity = Entity  # type: ignore[misc, assignment]

    try:
        from homeassistant.components.select import SelectEntity
    except ImportError:
        SelectEntity = Entity  # type: ignore[misc, assignment]

    try:
        from homeassistant.components.button import ButtonEntity
    except ImportError:
        ButtonEntity = Entity  # type: ignore[misc, assignment]

    # Import cv module for CONFIG_SCHEMA
    try:
        from homeassistant.helpers import config_validation as cv
    except ImportError:
        # Fallback: create a minimal cv module
        class _CVModule:
            @staticmethod
            def config_entry_only_config_schema(domain: str):
                """Return a schema that validates config-entry-only setup."""
                return vol.Schema({vol.Optional(domain): vol.Schema({})})

        cv = _CVModule()

    # Event constants
    try:
        from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
    except ImportError:
        EVENT_HOMEASSISTANT_STARTED = "homeassistant_start"

    try:
        from homeassistant.exceptions import HomeAssistantError, Unauthorized
    except ImportError:

        class HomeAssistantError(Exception):
            """General Home Assistant exception fallback."""

        class Unauthorized(HomeAssistantError):
            """Unauthorized Home Assistant exception fallback."""

            def __init__(
                self,
                context: Any = None,
                user_id: str | None = None,
                *args: Any,
                **kwargs: Any,
            ) -> None:
                super().__init__(f"Unauthorized (user_id={user_id})", *args)
                self.context = context
                self.user_id = user_id

    HAS_HOMEASSISTANT = True

except ImportError:
    HAS_HOMEASSISTANT = False

    EVENT_HOMEASSISTANT_STARTED = "homeassistant_start"

    class HomeAssistantError(Exception):
        """General Home Assistant exception fallback."""

    class Unauthorized(HomeAssistantError):
        """Unauthorized Home Assistant exception fallback."""

        def __init__(
            self,
            context: Any = None,
            user_id: str | None = None,
            *args: Any,
            **kwargs: Any,
        ) -> None:
            super().__init__(f"Unauthorized (user_id={user_id})", *args)
            self.context = context
            self.user_id = user_id

    def callback(func: Any) -> Any:
        """Callback decorator placeholder."""
        return func

    FlowResult = dict[str, Any]

    # Minimal cv module for standalone pytest
    class _CVModule:
        @staticmethod
        def config_entry_only_config_schema(domain: str):
            """Return a schema that validates config-entry-only setup."""
            return vol.Schema({vol.Optional(domain): vol.Schema({})})

    cv = _CVModule()

    class Store:
        """In-memory Store stand-in; persisted per hass.data for the process."""

        def __init__(self, hass: Any, version: int, key: str, **_kw: Any) -> None:
            self.hass = hass
            self.version = version
            self.key = key

        def _bucket(self) -> dict[str, Any]:
            return self.hass.data.setdefault("_compat_store", {})

        async def async_load(self) -> Any:
            import copy

            return copy.deepcopy(self._bucket().get(self.key))

        async def async_save(self, data: Any) -> None:
            import copy

            self._bucket()[self.key] = copy.deepcopy(data)

    class Platform(StrEnum):
        """Platform enum placeholder."""

        SENSOR = "sensor"
        SWITCH = "switch"
        SELECT = "select"
        BUTTON = "button"

    @dataclass
    class StaticPathConfig:
        """Static path config placeholder."""

        url_path: str
        path: str
        cache_headers: bool = True

    @dataclass
    class DeviceInfo:
        """Device registry info placeholder."""

        identifiers: set[tuple[str, str]] = field(default_factory=set)
        name: str | None = None
        manufacturer: str | None = "JetBrains"
        model: str | None = "Junie CLI"
        sw_version: str | None = None
        configuration_url: str | None = None

    @dataclass
    class ServiceCall:
        """Mock Home Assistant ServiceCall."""

        domain: str
        service: str
        data: dict[str, Any] = field(default_factory=dict)
        context: Any = None

    class Entity:
        """Entity base class placeholder."""

        _attr_has_entity_name: bool = False
        _attr_name: str | None = None
        _attr_unique_id: str | None = None
        _attr_device_info: DeviceInfo | None = None
        _attr_icon: str | None = None
        _attr_extra_state_attributes: dict[str, Any] = {}
        _attr_should_poll: bool = False

        def __init__(self) -> None:
            self.hass: Any = None
            self.entity_id: str | None = None
            self._remove_callbacks: list[Callable[[], None]] = []

        @property
        def name(self) -> str | None:
            return getattr(self, "_attr_name", None)

        @property
        def unique_id(self) -> str | None:
            return getattr(self, "_attr_unique_id", None)

        @property
        def device_info(self) -> DeviceInfo | None:
            return getattr(self, "_attr_device_info", None)

        @property
        def extra_state_attributes(self) -> dict[str, Any]:
            return getattr(self, "_attr_extra_state_attributes", {})

        @property
        def icon(self) -> str | None:
            return getattr(self, "_attr_icon", None)

        @property
        def available(self) -> bool:
            return True

        def async_write_ha_state(self) -> None:
            """Write entity state into hass.states registry if available."""
            if self.hass and hasattr(self.hass, "states") and self.entity_id:
                state_val = getattr(self, "state", None)
                if state_val is None and hasattr(self, "native_value"):
                    state_val = self.native_value
                if state_val is None and hasattr(self, "is_on"):
                    is_on = self.is_on
                    state_val = "on" if is_on else "off" if is_on is not None else None
                if state_val is None and hasattr(self, "current_option"):
                    state_val = self.current_option
                self.hass.states.set(
                    self.entity_id,
                    str(state_val) if state_val is not None else "unknown",
                    self.extra_state_attributes,
                )

        def async_on_remove(self, target: Callable[[], None]) -> None:
            self._remove_callbacks.append(target)

        async def async_added_to_hass(self) -> None:
            pass

        async def async_will_remove_from_hass(self) -> None:
            for cb in self._remove_callbacks:
                cb()
            self._remove_callbacks.clear()

    class SensorEntity(Entity):
        """Sensor entity base class placeholder."""

        _attr_native_value: Any = None

        @property
        def native_value(self) -> Any:
            return getattr(self, "_attr_native_value", None)

        @property
        def state(self) -> Any:
            return self.native_value

    class SwitchEntity(Entity):
        """Switch entity base class placeholder."""

        _attr_is_on: bool | None = None

        @property
        def is_on(self) -> bool | None:
            return getattr(self, "_attr_is_on", None)

        async def async_turn_on(self, **kwargs: Any) -> None:
            pass

        async def async_turn_off(self, **kwargs: Any) -> None:
            pass

    class SelectEntity(Entity):
        """Select entity base class placeholder."""

        _attr_current_option: str | None = None
        _attr_options: list[str] = []

        @property
        def current_option(self) -> str | None:
            return getattr(self, "_attr_current_option", None)

        @property
        def options(self) -> list[str]:
            return getattr(self, "_attr_options", [])

        async def async_select_option(self, option: str) -> None:
            pass

    class ButtonEntity(Entity):
        """Button entity base class placeholder."""

        async def async_press(self) -> None:
            pass

    @dataclass
    class ConfigEntry:
        """Mock Home Assistant ConfigEntry."""

        entry_id: str = "test_entry_id"
        domain: str = "junie_remote"
        title: str = "JetBrains Junie Remote"
        data: dict[str, Any] = field(default_factory=dict)
        options: dict[str, Any] = field(default_factory=dict)
        pref_disable_new_entities: bool = False
        pref_disable_polling: bool = False
        version: int = 1
        minor_version: int = 1
        _update_listeners: list[
            Callable[[Any, ConfigEntry], Coroutine[Any, Any, None]]
        ] = field(default_factory=list)
        _unload_listeners: list[Callable[[], None]] = field(default_factory=list)

        def add_update_listener(
            self, listener: Callable[[Any, ConfigEntry], Coroutine[Any, Any, None]]
        ) -> Callable[[], None]:
            """Register a listener for options updates."""
            self._update_listeners.append(listener)
            return lambda: (
                self._update_listeners.remove(listener)
                if listener in self._update_listeners
                else None
            )

        def async_on_unload(self, listener: Callable[[], None]) -> None:
            """Register an unload listener."""
            self._unload_listeners.append(listener)

    class ConfigFlow:
        """Mock Home Assistant ConfigFlow."""

        def __init_subclass__(cls, domain: str | None = None, **kwargs: Any) -> None:
            super().__init_subclass__(**kwargs)
            cls.domain = domain

        def __init__(self) -> None:
            self.hass: Any = None
            self.context: dict[str, Any] = {}
            self.handler: str = getattr(self, "domain", "junie_remote") or "junie_remote"

        def async_show_form(
            self,
            *,
            step_id: str,
            data_schema: Any = None,
            errors: dict[str, str] | None = None,
            description_placeholders: dict[str, str] | None = None,
            last_step: bool | None = None,
        ) -> FlowResult:
            """Show form response dictionary."""
            return {
                "type": "form",
                "flow_id": "test_flow_id",
                "handler": self.handler,
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
                "description_placeholders": description_placeholders or {},
                "last_step": last_step,
            }

        def async_create_entry(
            self,
            *,
            title: str,
            data: dict[str, Any],
            description: str | None = None,
            description_placeholders: dict[str, str] | None = None,
            options: dict[str, Any] | None = None,
        ) -> FlowResult:
            """Create entry response dictionary."""
            return {
                "type": "create_entry",
                "version": 1,
                "title": title,
                "data": data,
                "options": options or {},
                "description": description,
                "description_placeholders": description_placeholders or {},
                "result": ConfigEntry(
                    title=title,
                    data=data,
                    options=options or {},
                ),
            }

        def async_abort(
            self,
            *,
            reason: str,
            description_placeholders: dict[str, str] | None = None,
        ) -> FlowResult:
            """Abort flow response dictionary."""
            return {
                "type": "abort",
                "flow_id": "test_flow_id",
                "handler": self.handler,
                "reason": reason,
                "description_placeholders": description_placeholders or {},
            }

        def async_show_menu(
            self,
            *,
            step_id: str,
            menu_options: list[str],
            description: str | None = None,
        ) -> FlowResult:
            """Show menu response dictionary."""
            return {
                "type": "menu",
                "flow_id": "test_flow_id",
                "handler": self.handler,
                "step_id": step_id,
                "menu_options": menu_options,
                "description": description,
            }

        def _get_reauth_entry(self) -> ConfigEntry | None:
            """Return reauth entry if available in context."""
            if (
                self.hass
                and hasattr(self.hass, "config_entries")
                and self.context.get("entry_id")
            ):
                return self.hass.config_entries.async_get_entry(self.context["entry_id"])
            return None

    class OptionsFlow:
        """Mock Home Assistant OptionsFlow."""

        def __init__(self, config_entry: ConfigEntry | None = None) -> None:
            self.config_entry: ConfigEntry = config_entry or ConfigEntry()
            self.hass: Any = None
            self.handler: str = "junie_remote"

        def async_show_form(
            self,
            *,
            step_id: str,
            data_schema: Any = None,
            errors: dict[str, str] | None = None,
            description_placeholders: dict[str, str] | None = None,
            last_step: bool | None = None,
        ) -> FlowResult:
            """Show form response dictionary."""
            return {
                "type": "form",
                "flow_id": "test_options_flow_id",
                "handler": self.handler,
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
                "description_placeholders": description_placeholders or {},
                "last_step": last_step,
            }

        def async_show_menu(
            self,
            *,
            step_id: str,
            menu_options: list[str],
            description: str | None = None,
        ) -> FlowResult:
            """Show menu response dictionary."""
            return {
                "type": "menu",
                "flow_id": "test_options_flow_id",
                "handler": self.handler,
                "step_id": step_id,
                "menu_options": menu_options,
                "description": description,
            }

        def async_create_entry(
            self,
            *,
            title: str = "",
            data: dict[str, Any] | None = None,
        ) -> FlowResult:
            """Create options entry response dictionary."""
            return {
                "type": "create_entry",
                "title": title,
                "data": data or {},
            }

    class UpdateFailed(Exception):
        """UpdateFailed exception placeholder."""

    T = TypeVar("T")

    class DataUpdateCoordinator(Generic[T]):
        """Mock Home Assistant DataUpdateCoordinator."""

        def __init__(
            self,
            hass: Any,
            logger: logging.Logger,
            *,
            name: str,
            update_interval: timedelta | None = None,
            update_method: Callable[[], Coroutine[Any, Any, T]] | None = None,
            request_refresh_debouncer: Any = None,
        ) -> None:
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.update_method = update_method
            self.data: T | None = None
            self.last_update_success: bool = True
            self.last_exception: Exception | None = None
            self._listeners: list[Callable[[], None]] = []
            self._unsub_timer: asyncio.Task[None] | None = None
            self._is_shutdown = False

        def async_add_listener(
            self, update_callback: Callable[[], None]
        ) -> Callable[[], None]:
            """Register a listener for coordinator updates."""
            self._listeners.append(update_callback)
            return lambda: (
                self._listeners.remove(update_callback)
                if update_callback in self._listeners
                else None
            )

        def async_set_updated_data(self, data: T) -> None:
            """Manually set data and notify listeners."""
            self.data = data
            self.last_update_success = True
            self.last_exception = None
            for listener in list(self._listeners):
                try:
                    listener()
                except Exception:
                    self.logger.exception("Error calling coordinator listener")

        def async_set_update_error(self, err: Exception) -> None:
            """Manually set error and notify listeners."""
            self.last_update_success = False
            self.last_exception = err
            for listener in list(self._listeners):
                try:
                    listener()
                except Exception:
                    self.logger.exception("Error calling coordinator listener")

        async def _async_update_data(self) -> T:
            """Fetch data from update method."""
            if self.update_method:
                return await self.update_method()
            raise NotImplementedError

        async def async_refresh(self) -> None:
            """Refresh data asynchronously."""
            try:
                data = await self._async_update_data()
                self.async_set_updated_data(data)
            except Exception as err:
                self.async_set_update_error(err)
                raise

        async def async_config_entry_first_refresh(self) -> None:
            """Perform first refresh and start periodic polling loop."""
            await self.async_refresh()
            if self.update_interval and not self._is_shutdown:
                self._start_interval_timer()

        def _start_interval_timer(self) -> None:
            """Start background periodic polling loop."""
            if self._unsub_timer and not self._unsub_timer.done():
                self._unsub_timer.cancel()
            if self.update_interval:
                self._unsub_timer = asyncio.create_task(self._poll_loop())

        async def _poll_loop(self) -> None:
            """Periodic poll task loop."""
            interval = (
                self.update_interval.total_seconds()
                if self.update_interval
                else 10.0
            )
            try:
                while not self._is_shutdown:
                    await asyncio.sleep(interval)
                    if self._is_shutdown:
                        break
                    try:
                        data = await self._async_update_data()
                        self.async_set_updated_data(data)
                    except Exception as err:
                        self.async_set_update_error(err)
            except asyncio.CancelledError:
                pass

        async def async_shutdown(self) -> None:
            """Shut down coordinator and cancel background polling."""
            self._is_shutdown = True
            if self._unsub_timer and not self._unsub_timer.done():
                self._unsub_timer.cancel()
                self._unsub_timer = None

    class CoordinatorEntity(Entity, Generic[T]):
        """CoordinatorEntity placeholder."""

        def __init__(self, coordinator: DataUpdateCoordinator[T]) -> None:
            super().__init__()
            self.coordinator = coordinator

        @property
        def available(self) -> bool:
            """Return True if coordinator last update was successful."""
            return self.coordinator.last_update_success

        async def async_added_to_hass(self) -> None:
            """Register coordinator update listener when added to hass."""
            await super().async_added_to_hass()
            self.async_on_remove(
                self.coordinator.async_add_listener(self._handle_coordinator_update)
            )

        def _handle_coordinator_update(self) -> None:
            """Handle updated data from the coordinator."""
            self.async_write_ha_state()

@dataclass
class State:
    """Mock Home Assistant State."""

    entity_id: str
    state: str
    attributes: dict[str, Any] = field(default_factory=dict)

class MockStateManager:
    """Mock Home Assistant states manager."""

    def __init__(self) -> None:
        self._states: dict[str, State] = {}

    def get(self, entity_id: str) -> State | None:
        """Get state by entity ID."""
        return self._states.get(entity_id)

    def set(
        self,
        entity_id: str,
        new_state: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Set state for an entity ID."""
        self._states[entity_id] = State(
            entity_id=entity_id,
            state=str(new_state),
            attributes=dict(attributes or {}),
        )

    def async_all(self, domain: str | None = None) -> list[State]:
        """Return all entity states, optionally filtered by domain."""
        if domain:
            return [
                s
                for s in self._states.values()
                if s.entity_id.startswith(f"{domain}.")
            ]
        return list(self._states.values())

class MockServiceRegistry:
    """Mock Home Assistant services registry."""

    def __init__(self, hass: Any) -> None:
        self.hass = hass
        self._services: dict[
            str,
            dict[
                str,
                Callable[[ServiceCall], Coroutine[Any, Any, Any] | Any],
            ],
        ] = {}

    def has_service(self, domain: str, service: str) -> bool:
        """Check if service is registered."""
        return service in self._services.get(domain, {})

    def async_register(
        self,
        domain: str,
        service: str,
        service_func: Callable[[ServiceCall], Coroutine[Any, Any, Any] | Any],
        schema: Any = None,
    ) -> None:
        """Register a service handler."""
        self._services.setdefault(domain, {})[service] = service_func

    def async_remove(self, domain: str, service: str) -> None:
        """Unregister a service handler."""
        if domain in self._services:
            self._services[domain].pop(service, None)

    async def async_call(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
        blocking: bool = True,
        return_response: bool = False,
        context: Any = None,
    ) -> Any:
        """Call a registered service."""
        func = self._services.get(domain, {}).get(service)
        if not func:
            raise ValueError(f"Service {domain}.{service} not found")
        call = ServiceCall(
            domain=domain,
            service=service,
            data=service_data or {},
            context=context,
        )
        res = func(call)
        if asyncio.iscoroutine(res):
            res = await res
        return res

class MockHttp:
    """Mock Home Assistant HTTP component."""

    def __init__(self) -> None:
        self.registered_paths: list[dict[str, Any]] = []

    def register_static_path(
        self, url_path: str, path: str, cache_headers: bool = True
    ) -> None:
        """Register static path synchronously."""
        self.registered_paths.append({
            "url_path": url_path,
            "path": path,
            "cache_headers": cache_headers,
        })

    async def async_register_static_paths(self, configs: list[Any]) -> None:
        """Register static paths asynchronously."""
        for c in configs:
            if hasattr(c, "url_path"):
                self.registered_paths.append({
                    "url_path": getattr(c, "url_path"),
                    "path": getattr(c, "path"),
                    "cache_headers": getattr(c, "cache_headers", True),
                })
            elif isinstance(c, (list, tuple)) and len(c) >= 2:
                self.registered_paths.append({
                    "url_path": c[0],
                    "path": c[1],
                    "cache_headers": True,
                })

class MockFlowManager:
    """Mock config flow manager."""

    def __init__(self) -> None:
        self._progress: list[Any] = []

    def async_progress_by_handler(
        self, handler: str, include_uninitialized: bool = False
    ) -> list[Any]:
        """Return flows in progress for a handler."""
        return [f for f in self._progress if f.get("handler") == handler]


class MockConfigEntries:
    """Mock config entries manager."""

    def __init__(self, hass: Any) -> None:
        self.hass = hass
        self.entries: dict[str, Any] = {}
        self.forwarded_setups: list[tuple[Any, list[str]]] = []
        self.unloaded_platforms: list[tuple[Any, list[str]]] = []
        self.flow = MockFlowManager()

    def async_get_entry(self, entry_id: str) -> ConfigEntry | None:
        """Get config entry by ID."""
        return self.entries.get(entry_id)

    def async_entries(self, domain: str | None = None) -> list[ConfigEntry]:
        """Return configured entries, including disabled ones."""
        return [
            entry for entry in self.entries.values()
            if domain is None or entry.domain == domain
        ]

    def async_update_entry(
        self,
        entry: ConfigEntry,
        *,
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        """Update config entry data or options."""
        if data is not None:
            entry.data = dict(data)
        if options is not None:
            entry.options = dict(options)

    async def async_reload(self, entry_id: str) -> bool:
        """Reload config entry by notifying listeners."""
        entry = self.entries.get(entry_id)
        if entry:
            for listener in list(entry._update_listeners):
                await listener(self.hass, entry)
        return True

    async def async_forward_entry_setups(
        self, entry: ConfigEntry, platforms: list[str]
    ) -> bool:
        """Forward entry setups to platforms."""
        self.forwarded_setups.append((entry, list(platforms)))
        return True

    async def async_unload_platforms(
        self, entry: ConfigEntry, platforms: list[str]
    ) -> bool:
        """Unload entry platforms."""
        self.unloaded_platforms.append((entry, list(platforms)))
        return True

class MockConfig:
    """Mock Home Assistant config."""

    def __init__(self, config_dir: str | None = None) -> None:
        import tempfile

        self.config_dir = config_dir or tempfile.mkdtemp()

    def path(self, *parts: str) -> str:
        """Return path joined with config directory."""
        return str(Path(self.config_dir).joinpath(*parts))

class MockLovelaceResources:
    """Mock Lovelace resource collection."""

    def __init__(self) -> None:
        self.loaded = True
        self._items: list[dict[str, Any]] = []

    def async_items(self) -> list[dict[str, Any]]:
        """Return copy of resource items."""
        return list(self._items)

    async def async_load(self) -> None:
        """Mark collection as loaded."""
        self.loaded = True

    async def async_create_item(
        self, item_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a new Lovelace resource item."""
        import uuid

        item = {
            "id": uuid.uuid4().hex,
            "type": item_data.get("res_type", item_data.get("type")),
            "url": item_data["url"],
        }
        self._items.append(item)
        return dict(item)

    async def async_update_item(self, item_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a resource by its assigned ID."""
        for index, item in enumerate(self._items):
            if item["id"] == item_id:
                updated = dict(item)
                if "url" in updates:
                    updated["url"] = updates["url"]
                if "res_type" in updates:
                    updated["type"] = updates["res_type"]
                self._items[index] = updated
                return dict(updated)
        raise KeyError(item_id)

    async def async_delete_item(self, item_id: str) -> None:
        """Delete an item by its assigned ID."""
        for index, item in enumerate(self._items):
            if item["id"] == item_id:
                self._items.pop(index)
                return
        raise KeyError(item_id)

class MockLovelace:
    """Mock Lovelace data store."""

    def __init__(self) -> None:
        self.mode = "storage"
        self.config: dict[str, Any] = {}
        self.resources = MockLovelaceResources()

    async def async_create_item(
        self, item_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a new Lovelace resource item directly on lovelace."""
        return await self.resources.async_create_item(item_data)

class MockEventBus:
    """Mock Home Assistant event bus."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable[..., Any]]] = {}

    def async_listen(
        self,
        event_type: str,
        listener: Callable[..., Any],
    ) -> Callable[[], None]:
        """Register an event listener."""
        self._listeners.setdefault(event_type, []).append(listener)
        return lambda: (
            self._listeners.get(event_type, []).remove(listener)
            if listener in self._listeners.get(event_type, [])
            else None
        )

    def async_listen_once(
        self,
        event_type: str,
        listener: Callable[..., Any],
    ) -> Callable[[], None]:
        """Register a one-time event listener."""

        def _once_listener(data: Any) -> Any:
            unsub()
            return listener(data)

        unsub = self.async_listen(event_type, _once_listener)
        return unsub

    async def async_fire(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Fire an event and call all listeners."""
        for listener in list(self._listeners.get(event_type, [])):
            try:
                result = listener(data or {})
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass


# --- Mock Classes (always available, regardless of homeassistant install) ---

@dataclass
class MockConfigEntry:
    """Mock Home Assistant ConfigEntry for tests.

    Always available regardless of whether the real homeassistant package
    is installed. Tests should prefer this over the real ConfigEntry.
    """

    entry_id: str = "test_entry_id"
    domain: str = "junie_remote"
    title: str = "JetBrains Junie Remote"
    data: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    pref_disable_new_entities: bool = False
    pref_disable_polling: bool = False
    version: int = 1
    minor_version: int = 1
    _update_listeners: list[
        Callable[[Any, "MockConfigEntry"], Coroutine[Any, Any, None]]
    ] = field(default_factory=list)
    _unload_listeners: list[Callable[[], None]] = field(default_factory=list)

    def add_update_listener(
        self, listener: Callable[[Any, "MockConfigEntry"], Coroutine[Any, Any, None]]
    ) -> Callable[[], None]:
        """Register a listener for options updates."""
        self._update_listeners.append(listener)
        return lambda: (
            self._update_listeners.remove(listener)
            if listener in self._update_listeners
            else None
        )

    def async_on_unload(self, listener: Callable[[], None]) -> None:
        """Register an unload listener."""
        self._unload_listeners.append(listener)


class MockHomeAssistant:
    """Mock Home Assistant core object for tests.

    Always available regardless of whether the real homeassistant package
    is installed. Tests should prefer this over the real HomeAssistant
    to avoid depending on HA internals.
    """

    def __init__(self) -> None:
        self.state = "RUNNING"
        self.data: dict[str, Any] = {}
        self.http = MockHttp()
        self.config = MockConfig()
        self.config_entries = MockConfigEntries(self)
        self.services = MockServiceRegistry(self)
        self.states = MockStateManager()
        self._tasks: list[asyncio.Task[Any]] = []
        self.bus = MockEventBus()
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()

    def async_create_task(
        self,
        coro: Coroutine[Any, Any, Any],
        name: str | None = None,
    ) -> asyncio.Task[Any]:
        """Create an asyncio task tracked by hass."""
        task = asyncio.create_task(coro, name=name)
        self._tasks.append(task)
        return task

    def async_add_executor_job(
        self, target: Callable[..., Any], *args: Any
    ) -> asyncio.Future[Any]:
        """Run a function in an executor and return a future."""
        return self.loop.run_in_executor(None, target, *args)  # type: ignore[return-value]


# When homeassistant is not installed, MockHomeAssistant serves as HomeAssistant.
HomeAssistant = MockHomeAssistant  # type: ignore[name-defined]


__all__ = [
    "HAS_HOMEASSISTANT",
    "ButtonEntity",
    "ConfigEntry",
    "ConfigFlow",
    "CoordinatorEntity",
    "DataUpdateCoordinator",
    "DeviceInfo",
    "Entity",
    "FlowResult",
    "HomeAssistant",
    "HomeAssistantError",
    "MockConfigEntry",
    "MockHomeAssistant",
    "OptionsFlow",
    "Platform",
    "SelectEntity",
    "SensorEntity",
    "ServiceCall",
    "State",
    "StaticPathConfig",
    "Store",
    "SwitchEntity",
    "Unauthorized",
    "UpdateFailed",
    "callback",
    "cv",
    "vol",
]
