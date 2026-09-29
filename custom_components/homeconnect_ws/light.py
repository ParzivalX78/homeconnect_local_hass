"""Light entities."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.components.light.const import DEFAULT_MAX_KELVIN, DEFAULT_MIN_KELVIN
from homeassistant.util.color import (
    brightness_to_value,
    color_rgb_to_hex,
    match_max_scale,
    rgb_hex_to_rgb_list,
    value_to_brightness,
)
from homeassistant.util.scaling import scale_ranged_value_to_int_range
from homeconnect_websocket.message import Action
from homeconnect_websocket.message import Message as HC_Message

from .entity import HCEntity
from .helpers import create_entities, error_decorator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeconnect_websocket.entities import Entity as HcEntity

    from . import HCConfigEntry, HCData
    from .entity_descriptions.descriptions_definitions import HCLightEntityDescription

PARALLEL_UPDATES = 0
WRITE_DELAY = 0.5  # seconds between sequential writes to the appliance


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    config_entry: HCConfigEntry,
    async_add_entites: AddEntitiesCallback,
) -> None:
    """Set up light platform."""
    entities = create_entities({"light": HCLight}, config_entry.runtime_data)
    async_add_entites(entities)


class HCLight(HCEntity, LightEntity):
    """Light Entity."""

    entity_description: HCLightEntityDescription
    _brightness_entity: HcEntity | None = None
    _color_temperature_entity: HcEntity | None = None
    _color_entity: HcEntity | None = None
    _color_mode_entity: HcEntity | None = None
    _color_temp_presets_entity: HcEntity | None = None

    def __init__(
        self,
        entity_description: HCLightEntityDescription,
        runtime_data: HCData,
    ) -> None:
        super().__init__(entity_description, runtime_data)
        if entity_description.brightness_entity is not None:
            self._brightness_entity = self._runtime_data.appliance.entities[
                entity_description.brightness_entity
            ]
            self._entities.append(self._brightness_entity)

        if entity_description.color_temperature_entity is not None:
            self._color_temperature_entity = self._runtime_data.appliance.entities[
                entity_description.color_temperature_entity
            ]
            self._entities.append(self._color_temperature_entity)
            self._color_temp_presets_entity = self._runtime_data.appliance.entities.get(
                "Cooking.Hood.Setting.ColorTemperature"
            )

        if entity_description.color_entity is not None:
            self._color_entity = self._runtime_data.appliance.entities[
                entity_description.color_entity
            ]
            self._entities.append(self._color_entity)

        if entity_description.color_mode_entity is not None:
            self._color_mode_entity = self._runtime_data.appliance.entities[
                entity_description.color_mode_entity
            ]
            self._entities.append(self._color_mode_entity)

        if self._color_entity:
            self._attr_supported_color_modes = {ColorMode.RGB}
            self._attr_color_mode = ColorMode.RGB
        elif self._color_temperature_entity and self._brightness_entity:
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_max_color_temp_kelvin = DEFAULT_MAX_KELVIN
            self._attr_min_color_temp_kelvin = DEFAULT_MIN_KELVIN
        elif self._brightness_entity:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF

    # Availability deliberately follows the power entity alone. Appliances
    # mark attribute entities such as brightness unavailable while the light
    # is off, and losing an attribute must not remove the on/off control.

    @property
    def is_on(self) -> bool | None:
        return bool(self._entity.value)

    @property
    def brightness(self) -> int | None:
        if self._color_entity is not None and self._color_entity.value is not None:
            rgb = rgb_hex_to_rgb_list(self._color_entity.value.strip("#"))
            return max(rgb)
        if self._brightness_entity is not None and self._brightness_entity.value is not None:
            return value_to_brightness((1, 100), self._brightness_entity.value)
        return None

    @property
    def color_temp_kelvin(self) -> int | None:
        if (
            self._color_temperature_entity is not None
            and self._color_temperature_entity.value is not None
        ):
            if self._color_temp_presets_entity:
                return scale_ranged_value_to_int_range(
                    (101, 0),
                    (DEFAULT_MIN_KELVIN + 1, DEFAULT_MAX_KELVIN),
                    self._color_temperature_entity.value,
                )

            return scale_ranged_value_to_int_range(
                (1, 100),
                (DEFAULT_MIN_KELVIN + 1, DEFAULT_MAX_KELVIN),
                self._color_temperature_entity.value,
            )
        return None

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        if self._color_entity is not None and self._color_entity.value is not None:
            rgb = rgb_hex_to_rgb_list(self._color_entity.value.strip("#"))
            return match_max_scale((255,), rgb)
        return None

    async def _write(self, uid: int, value: Any) -> None:
        """Send a single value, the same way turn_off does."""
        await self._runtime_data.appliance.session.send_sync(
            HC_Message(
                resource="/ro/values",
                action=Action.POST,
                data=[{"uid": uid, "value": value}],
            )
        )

    @error_decorator
    async def async_turn_on(self, **kwargs: Any) -> None:
        # 1) Power on as a separate single-value write (turn_off works this way)
        if self._entity.value is not True:
            await self._write(self._entity.uid, True)
            await asyncio.sleep(WRITE_DELAY)

        if self._attr_color_mode == ColorMode.RGB:
            brightness = kwargs.get(ATTR_BRIGHTNESS, self.brightness) or 255
            rgb = kwargs.get(ATTR_RGB_COLOR, self.rgb_color) or (255, 255, 255)
            # 2) Switch colour mode to CustomColor before writing the colour
            if (
                self._color_mode_entity is not None
                and self._color_mode_entity.value != "CustomColor"
            ):
                color_mode_value = self._color_mode_entity._rev_enumeration["CustomColor"]  # noqa: SLF001
                await self._write(self._color_mode_entity.uid, color_mode_value)
                await asyncio.sleep(WRITE_DELAY)
            # 3) Only then write the custom colour
            rgb_with_brightness = tuple(color * brightness // 255 for color in rgb)
            await self._write(
                self._color_entity.uid, "#" + color_rgb_to_hex(*rgb_with_brightness)
            )
            return

        if ATTR_BRIGHTNESS in kwargs and self._brightness_entity is not None:
            value_in_range = int(
                max(
                    brightness_to_value((1, 100), kwargs[ATTR_BRIGHTNESS]),
                    self._brightness_entity.min,
                )
            )
            await self._write(self._brightness_entity.uid, value_in_range)

        if ATTR_COLOR_TEMP_KELVIN in kwargs and self._color_temperature_entity is not None:
            if self._color_temp_presets_entity:
                await self._write(self._color_temp_presets_entity.uid, 0)
                value_in_range = int(
                    scale_ranged_value_to_int_range(
                        (DEFAULT_MIN_KELVIN + 1, DEFAULT_MAX_KELVIN),
                        (101, 0),
                        kwargs[ATTR_COLOR_TEMP_KELVIN],
                    )
                )
            else:
                value_in_range = int(
                    scale_ranged_value_to_int_range(
                        (DEFAULT_MIN_KELVIN + 1, DEFAULT_MAX_KELVIN),
                        (1, 100),
                        kwargs[ATTR_COLOR_TEMP_KELVIN],
                    )
                )
            await self._write(self._color_temperature_entity.uid, value_in_range)

    @error_decorator
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._entity.set_value(False)