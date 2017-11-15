# Copyright (c) 2017 Ultimaker B.V.
# Cura is released under the terms of the LGPLv3 or higher.

from PyQt5.QtCore import Qt, pyqtProperty, pyqtSignal, pyqtSlot

from UM.Application import Application
from UM.Settings.ContainerRegistry import ContainerRegistry
from UM.Settings.Models.InstanceContainersModel import InstanceContainersModel
from UM.Signal import postponeSignals, CompressTechnique

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
    QualityTypeRole = Qt.UserRole + 1005

    def __init__(self, parent = None):
        self._quality_results = []
        self._has_usable_quality = False
        self._has_quality_changes = False

        self._empty_quality_container = ContainerRegistry.getInstance().findContainers(id = "empty_quality")[0]

        super().__init__(parent)
        self.addRoleName(self.LayerHeightRole, "layer_height")
        self.addRoleName(self.LayerHeightWithoutUnitRole, "layer_height_without_unit")
        self.addRoleName(self.AvailableRole, "available")
        self.addRoleName(self.IsCustomQualityRole, "is_custom_quality")
        self.addRoleName(self.QualityTypeRole, "quality_type")

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

    @pyqtSlot(str)
    def setQualityType(self, quality_type: str):
        machine_manager = Application.getInstance().getMachineManager()
        from UM.Logger import Logger
        quality_group = self._quality_results.qualities[quality_type]

        global_container_stack = Application.getInstance().getGlobalContainerStack()
        machine_manager._replaceQualityOrQualityChangesInStack(global_container_stack, quality_group.machine_quality)
        Logger.log("d", "----- [%s] -> [%s]", global_container_stack.getId(), quality_group.machine_quality.getId())

        for position, quality in enumerate(quality_group.extruder_qualities):
            Logger.log("d", "----- [%s] -> [%s]", global_container_stack.extruders[str(position)].getId(), quality.getId())
            machine_manager._replaceQualityOrQualityChangesInStack(global_container_stack.extruders[str(position)], quality)

    ##  Fetch the list of containers to display.
    #
    #   See UM.Settings.Models.InstanceContainersModel._fetchInstanceContainers().
    def _fetchInstanceContainers(self):
        global_container_stack = Application.getInstance().getGlobalContainerStack()
        if global_container_stack is None:
            return []

        from cura.Settings.CureCoreAPI import CuraCoreAPI
        core = CuraCoreAPI()
        all_results = core.getQualitiesForMachineByName(global_container_stack.getName())

        self._quality_results = all_results

        result_containers = {}
        for quality_group in all_results.qualities.values():
            for quality_container in [quality_group.machine_quality] + quality_group.extruder_qualities:
                if quality_container.getId() not in result_containers:
                    result_containers[quality_container.getId()] = quality_container
        for qc_group in all_results.quality_changes.values():
            for qc_container in [qc_group.machine_quality_changes] + qc_group.extruder_quality_changes:
                if qc_container.getId() not in result_containers:
                    result_containers[qc_container.getId()] = qc_container

        # if still profiles are found, add a single empty_quality ("Not supported") instance to the drop down list
        if len(result_containers) == 0 and "empty_quality" not in result_containers:
            # If not qualities are found we dynamically create a not supported container for this machine + material combination
            #result_containers[self._empty_quality_container.getId()] = self._empty_quality_container
            pass

        self.setHasUsableQuality(len(all_results.usable_quality_types) > 0)
        self.setHasQualityChanges(len(all_results.quality_changes) > 0)

        return [c for c in result_containers.values()]

    ##  Re-computes the items in this model, and adds the layer height role.
    def _recomputeItems(self):
        # Some globals that we can re-use.
        global_container_stack = Application.getInstance().getGlobalContainerStack()
        if global_container_stack is None:
            return

        extruder_manager = Application.getInstance().getExtruderManager()
        active_extruder = extruder_manager.getActiveExtruderStack()
        active_extruder_position = int(active_extruder.getMetaDataEntry("position"))

        unit = global_container_stack.getBottom().getProperty("layer_height", "unit")
        if not unit:
            unit = ""

        # Process qualities
        if not self._has_usable_quality:
            # if there is no usable quality, return the empty_quality as "Not Supported"
            item = self._createItem(self._empty_quality_container)
            self._setItemLayerHeight(item, "", "")
            item["available"] = True
            yield item
        else:
            quality_dict = {}
            for quality_type, quality_group in self._quality_results.qualities.items():
                from UM.Logger import Logger
                Logger.log("d", "~~~~~~~~ quality type = [%s]", quality_type)
                profile = quality_group.machine_quality
                item = self._createItem(profile)
                item["available"] = quality_group.usable

                # Easy case: This profile defines its own layer height.
                if profile.hasProperty("layer_height", "value"):
                    Logger.log("d", "~~~~~ profile layer height = [%s]", profile.getProperty("layer_height", "value"))
                    self._setItemLayerHeight(item, profile.getProperty("layer_height", "value"), unit)
                    quality_dict[item["layer_height_without_unit"]] = item
                    continue
                if quality_group.machine_quality.hasProperty("layer_height", "value"):
                    Logger.log("d", "~~~~~ profile layer height = [%s]", quality_group.machine_quality.getProperty("layer_height", "value"))
                    self._setItemLayerHeight(item, quality_group.machine_quality.getProperty("layer_height", "value"), unit)
                    quality_dict[item["layer_height_without_unit"]] = item
                    continue

                # Quality has no value for layer height either. Get the layer height from somewhere lower in the stack.
                skip_until_container = active_extruder.material
                if not skip_until_container or skip_until_container == ContainerRegistry.getInstance().getEmptyInstanceContainer(): #No material in stack.
                    skip_until_container = active_extruder.variant
                    if not skip_until_container or skip_until_container == ContainerRegistry.getInstance().getEmptyInstanceContainer(): #No variant in stack.
                        skip_until_container = active_extruder.getBottom()
                self._setItemLayerHeight(item, active_extruder.getRawProperty("layer_height", "value", skip_until_container = skip_until_container.getId()), unit)  # Fall through to the currently loaded material.
                quality_dict[item["layer_height_without_unit"]] = item

            layer_height_dict = {float(k): k for k in quality_dict}
            for layer_height in sorted(layer_height_dict.keys()):
                item = quality_dict[layer_height_dict[layer_height]]
                from UM.Logger import Logger
                Logger.log("d", "-------- [%s] [%s]", item["name"], item["layer_height_without_unit"])
                yield item

        # Process quality_changes
        for quality_changes_name in sorted(self._quality_results.quality_changes.keys()):
            quality_changes_group = self._quality_results.quality_changes[quality_changes_name]

            profile = quality_changes_group.extruder_quality_changes[active_extruder_position]

            item = self._createItem(profile)
            item["available"] = quality_changes_group.usable

            # Easy case: This profile defines its own layer height.
            if profile.hasProperty("layer_height", "value"):
                self._setItemLayerHeight(item, profile.getProperty("layer_height", "value"), unit)
                yield item
                continue

            machine_manager = Application.getInstance().getMachineManager()

            # Quality-changes profile that has no value for layer height. Get the corresponding quality profile and ask that profile.
            quality_type = profile.getMetaDataEntry("quality_type", None)
            if quality_type:
                global_qualities = ContainerRegistry.getInstance().findInstanceContainers(type = "quality",
                                                                                          quality_type = quality_type,
                                                                                          global_quality = True,
                                                                                          definition = global_container_stack.definition.getId())
                if global_qualities:
                    quality = global_qualities[0]
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
            "quality_type": container.getMetaDataEntry("quality_type"),
            "metadata": metadata,
            "readOnly": container.isReadOnly(),
            "section": container.getMetaDataEntry(self._section_property, ""),
            "is_custom_quality": container.getMetaDataEntry("type") == "quality_changes",
        }
