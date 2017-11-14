# Copyright (c) 2017 Ultimaker B.V.
# Cura is released under the terms of the LGPLv3 or higher.

from PyQt5.QtCore import Qt, pyqtProperty, pyqtSignal

from UM.Application import Application
from UM.Settings.ContainerRegistry import ContainerRegistry
from UM.Settings.Models.InstanceContainersModel import InstanceContainersModel

from cura.Settings.ExtruderManager import ExtruderManager

from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from cura.Settings.ExtruderStack import ExtruderStack


##  QML Model for listing the current list of valid quality profiles.
#
class ProfilesModel(InstanceContainersModel):
    LayerHeightRole = Qt.UserRole + 1001
    LayerHeightWithoutUnitRole = Qt.UserRole + 1002
    AvailableRole = Qt.UserRole + 1003
    IsCustomQualityRole = Qt.UserRole + 1004

    def __init__(self, parent = None):
        self._quality_results = []
        self._has_usable_quality = False
        self._has_quality_changes = False

        super().__init__(parent)
        self.addRoleName(self.LayerHeightRole, "layer_height")
        self.addRoleName(self.LayerHeightWithoutUnitRole, "layer_height_without_unit")
        self.addRoleName(self.AvailableRole, "available")
        self.addRoleName(self.IsCustomQualityRole, "is_custom_quality")

        Application.getInstance().globalContainerStackChanged.connect(self._update)
        Application.getInstance().getMachineManager().activeVariantChanged.connect(self._update)
        Application.getInstance().getMachineManager().activeStackChanged.connect(self._update)
        Application.getInstance().getMachineManager().activeMaterialChanged.connect(self._update)

    hasUsableQualityChanged = pyqtSignal()
    hasQualityChangesChanged = pyqtSignal()

    @pyqtProperty(bool, notify = hasUsableQualityChanged)
    def hasUsableQuality(self):
        return self._has_usable_quality

    def setHasUsableQuality(self, value):
        need_emit_signal = self._has_usable_quality != value
        self._has_usable_quality = value
        if need_emit_signal:
            self.hasUsableQualityChanged.emit()

    @pyqtProperty(bool, notify = hasQualityChangesChanged)
    def hasQualityChanges(self):
        return self._has_quality_changes

    def setHasQualityChanges(self, value):
        need_emit_signal = self._has_quality_changes != value
        self._has_quality_changes = value
        if need_emit_signal:
            self.hasQualityChangesChanged.emit()

    # Factory function, used by QML
    @staticmethod
    def createProfilesModel(engine, js_engine):
        return ProfilesModel.getInstance()

    ##  Get the singleton instance for this class.
    @classmethod
    def getInstance(cls) -> "ProfilesModel":
        # Note: Explicit use of class name to prevent issues with inheritance.
        if not ProfilesModel.__instance:
            ProfilesModel.__instance = cls()
        return ProfilesModel.__instance

    __instance = None   # type: "ProfilesModel"

    ##  Fetch the list of containers to display.
    #
    #   See UM.Settings.Models.InstanceContainersModel._fetchInstanceContainers().
    def _fetchInstanceContainers(self):
        global_container_stack = Application.getInstance().getGlobalContainerStack()
        if global_container_stack is None:
            return []

        global_stack_definition = global_container_stack.definition

        # Get the list of extruders and place the selected extruder at the front of the list.
        extruder_stacks = self._getOrderedExtruderStacksList()
        materials = [extruder.material for extruder in extruder_stacks]

        from .CureCoreAPI import CuraCoreAPI
        core = CuraCoreAPI()

        # cache the results for _recomputeItems()
        self._quality_results = core.getQualitiesForMachineByName(global_container_stack.getName())

        extruder_manager = ExtruderManager.getInstance()
        active_extruder = extruder_manager.getActiveExtruderStack()

        usable_quality_containers = []
        for quality_type, quality_data in self._quality_results.qualities.items():
            # get the quality container for the currently active stack
            if global_container_stack.extruders:
                quality_container = quality_data["qualities"][int(active_extruder.getMetaDataEntry("position"))]
            else:
                quality_container = quality_data["qualities"]

            quality_data["container_for_active_stack"] = quality_container
            if quality_data["is_usable"]:
                usable_quality_containers.append(quality_container)

        for quality_changes_name, quality_changes_data in self._quality_results.quality_changes.items():
            # get the quality container for the currently active stack
            if global_container_stack.extruders:
                quality_changes_container = quality_changes_data["quality_changes"][int(active_extruder.getMetaDataEntry("position"))]
            else:
                quality_changes_container = quality_changes_data["quality_changes"]
            quality_changes_data["container_for_active_stack"] = quality_changes_container

        # if still profiles are found, add a single empty_quality ("Not supported") instance to the drop down list
        self.setHasUsableQuality(len(usable_quality_containers) > 0)
        if not self._has_usable_quality:
            # If not qualities are found we dynamically create a not supported container for this machine + material combination
            not_supported_container = ContainerRegistry.getInstance().findContainers(id = "empty_quality")[0]
            usable_quality_containers.append(not_supported_container)

        self.setHasQualityChanges(len(self._quality_results.quality_changes) > 0)

        return usable_quality_containers

    ##  Re-computes the items in this model, and adds the layer height role.
    def _recomputeItems(self):
        # Some globals that we can re-use.
        global_container_stack = Application.getInstance().getGlobalContainerStack()
        if global_container_stack is None:
            return

        extruder_stacks = self._getOrderedExtruderStacksList()
        container_registry = ContainerRegistry.getInstance()
        machine_manager = Application.getInstance().getMachineManager()

        unit = global_container_stack.getBottom().getProperty("layer_height", "unit")
        if not unit:
            unit = ""

        # if there is no usable quality, return the empty_quality as "Not Supported"
        if not self._has_usable_quality:
            item = self._createItem(self.__instance[0])
            self._setItemLayerHeight(item, "", "")
            item["available"] = True
            yield item
            return

        quality_dict = {}
        for quality_type in sorted(self._quality_results.qualities.keys()):
            quality_data = self._quality_results.qualities[quality_type]

            profile = quality_data["container_for_active_stack"]

            item = self._createItem(profile)
            item["available"] = quality_data["is_usable"]

            # Easy case: This profile defines its own layer height.
            if profile.hasProperty("layer_height", "value"):
                self._setItemLayerHeight(item, profile.getProperty("layer_height", "value"), unit)
                quality_dict[float(item["layer_height_without_unit"])] = item
                continue

            # Quality has no value for layer height either. Get the layer height from somewhere lower in the stack.
            skip_until_container = global_container_stack.material
            if not skip_until_container or skip_until_container == ContainerRegistry.getInstance().getEmptyInstanceContainer(): #No material in stack.
                skip_until_container = global_container_stack.variant
                if not skip_until_container or skip_until_container == ContainerRegistry.getInstance().getEmptyInstanceContainer(): #No variant in stack.
                    skip_until_container = global_container_stack.getBottom()
            self._setItemLayerHeight(item, global_container_stack.getRawProperty("layer_height", "value", skip_until_container = skip_until_container.getId()), unit)  # Fall through to the currently loaded material.
            quality_dict[float(item["layer_height_without_unit"])] = item

        for layer_height in sorted(quality_dict.keys()):
            yield quality_dict[layer_height]

        for quality_changes_name in sorted(self._quality_results.quality_changes.keys()):
            quality_data = self._quality_results.quality_changes[quality_changes_name]

            profile = quality_data["container_for_active_stack"]

            item = self._createItem(profile)
            item["available"] = quality_data["is_usable"]

            # Easy case: This profile defines its own layer height.
            if profile.hasProperty("layer_height", "value"):
                self._setItemLayerHeight(item, profile.getProperty("layer_height", "value"), unit)
                yield item
                continue

            machine_manager = Application.getInstance().getMachineManager()

            # Quality-changes profile that has no value for layer height. Get the corresponding quality profile and ask that profile.
            quality_type = profile.getMetaDataEntry("quality_type", None)
            if quality_type:
                quality_results = machine_manager.determineQualityAndQualityChangesForQualityType(quality_type)
                for quality_result in quality_results:
                    if quality_result["stack"] is global_container_stack:
                        quality = quality_result["quality"]
                        break
                else:
                    # No global container stack in the results:
                    if quality_results:
                        # Take any of the extruders.
                        quality = quality_results[0]["quality"]
                    else:
                        quality = None
                if quality and quality.hasProperty("layer_height", "value"):
                    self._setItemLayerHeight(item, quality.getProperty("layer_height", "value"), unit)
                    yield item
                    continue

            # Quality has no value for layer height either. Get the layer height from somewhere lower in the stack.
            skip_until_container = global_container_stack.material
            if not skip_until_container or skip_until_container == ContainerRegistry.getInstance().getEmptyInstanceContainer():  # No material in stack.
                skip_until_container = global_container_stack.variant
                if not skip_until_container or skip_until_container == ContainerRegistry.getInstance().getEmptyInstanceContainer():  # No variant in stack.
                    skip_until_container = global_container_stack.getBottom()
            self._setItemLayerHeight(item, global_container_stack.getRawProperty("layer_height", "value", skip_until_container = skip_until_container.getId()), unit)  # Fall through to the currently loaded material.
            yield item

    ## Get a list of extruder stacks with the active extruder at the front of the list.
    @staticmethod
    def _getOrderedExtruderStacksList() -> List["ExtruderStack"]:
        extruder_manager = ExtruderManager.getInstance()
        extruder_stacks = extruder_manager.getActiveExtruderStacks()
        active_extruder = extruder_manager.getActiveExtruderStack()

        if active_extruder in extruder_stacks:
            extruder_stacks.remove(active_extruder)
            extruder_stacks = [active_extruder] + extruder_stacks

        return extruder_stacks

    @staticmethod
    def _setItemLayerHeight(item, value, unit):
        item["layer_height"] = str(value) + unit
        item["layer_height_without_unit"] = str(value)

    def _createItem(self, container):
        metadata = container.getMetaData().copy()
        metadata["has_settings"] = len(container.getAllKeys()) > 0

        return {
            "name": container.getName(),
            "id": container.getId(),
            "metadata": metadata,
            "readOnly": container.isReadOnly(),
            "section": container.getMetaDataEntry(self._section_property, ""),
            "is_custom_quality": container.getMetaDataEntry("type") == "quality_changes",
        }
