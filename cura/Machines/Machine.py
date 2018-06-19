
from collections import OrderedDict
from typing import Dict, List, TYPE_CHECKING

from UM.Logging.Logger import Logger
from UM import Util

from .Extruder import Extruder

if TYPE_CHECKING:
    from UM.Application import Application
    from cura.Settings.GlobalStack import GlobalStack


class Machine:

    def __init__(self, application: "Application", global_stack: "GlobalStack") -> None:
        self._application = application
        self._container_registry = self._application.getContainerRegistry()
        self._quality_manager = self._application.getQualityManager()

        self._global_stack = global_stack  # type: GlobalStack
        self._extruders = OrderedDict()  # type: Dict[str, "Extruder"]

        self._current_quality_group = None
        self._current_quality_changes_group = None

    @property
    def global_stack(self) -> "GlobalStack":
        return self._global_stack

    @property
    def extruders(self) -> Dict[str, "Extruder"]:
        return self._extruders

    def initState(self) -> None:
        """
        This function initializes this machine and fixes any problems that we can discover.
        """
        if not self._extruders:
            for position, extruder_stack in sorted(self.global_stack.extruders.items()):
                extruder = Extruder(self._application, self, extruder_stack)
                extruder.initialize()
                self._extruders[position] = extruder

        # Update materials to make sure that the diameters match with the machine's
        for extruder in self._extruders.values():
            extruder.updateMaterial()

        self.updateQuality()

    def updateQuality(self) -> None:
        Logger.log("i", "Updating quality/quality_changes due to material change")
        current_quality_type = None
        if self._current_quality_group:
            current_quality_type = self._current_quality_group.quality_type
        candidate_quality_groups = self._quality_manager.getQualityGroups(self.global_stack)
        available_quality_types = {qt for qt, g in candidate_quality_groups.items() if g.is_available}

        Logger.log("d", "Current quality type = [%s]", current_quality_type)
        if not self.areMaterialsCompatible:
            if current_quality_type is not None:
                Logger.log("i", "Active materials are not compatible, setting all qualities to empty (Not Supported).")
                self._setEmptyQuality()
            return

        if not available_quality_types:
            if self._current_quality_changes_group is None:
                Logger.log("i", "No available quality types found, setting all qualities to empty (Not Supported).")
                self._setEmptyQuality()
            return

        if current_quality_type in available_quality_types:
            Logger.log("i", "Current available quality type [%s] is available, applying changes.", current_quality_type)
            self.setQualityGroup(candidate_quality_groups[current_quality_type], empty_quality_changes = False)
            return

        # The current quality type is not available so we use the preferred quality type if it's available,
        # otherwise use one of the available quality types.
        quality_type = sorted(list(available_quality_types))[0]
        preferred_quality_type = self.global_stack.getMetaDataEntry("preferred_quality_type")
        if preferred_quality_type in available_quality_types:
            quality_type = preferred_quality_type

        Logger.log("i", "The current quality type [%s] is not available, switching to [%s] instead",
                   current_quality_type, quality_type)
        self.setQualityGroup(candidate_quality_groups[quality_type], empty_quality_changes = True)

    def setQualityGroupByQualityType(self, quality_type: str) -> None:
        if self._global_stack is None:
            return
        # Get all the quality groups for this global stack and filter out by quality_type
        quality_group_dict = self._quality_manager.getQualityGroups(self._global_stack)
        quality_group = quality_group_dict[quality_type]
        self.setQualityGroup(quality_group)

    def setQualityGroup(self, quality_group, empty_quality_changes: bool = True) -> None:
        if quality_group is None:
            self._setEmptyQuality()
            return

        if quality_group.node_for_global.getContainer() is None:
            return
        for node in quality_group.nodes_for_extruders.values():
            if node.getContainer() is None:
                return

        self._current_quality_group = quality_group
        if empty_quality_changes:
            self._current_quality_changes_group = None

        # Set quality and quality_changes for the GlobalStack
        self.global_stack.quality = quality_group.node_for_global.getContainer()
        if empty_quality_changes:
            self.global_stack.qualityChanges = self._container_registry.empty_quality_changes_container

        # Set quality and quality_changes for each ExtruderStack
        for position, node in quality_group.nodes_for_extruders.items():
            position = str(position)
            self.global_stack.extruders[position].quality = node.getContainer()
            if empty_quality_changes:
                self.global_stack.extruders[position].qualityChanges = self._container_registry.empty_quality_changes_container

    def setQualityChangesGroup(self, quality_changes_group) -> None:
        quality_type = quality_changes_group.quality_type
        # A custom quality can be created based on "not supported".
        # In that case, do not set quality containers to empty.
        quality_group = None
        if quality_type != "not_supported":
            quality_group_dict = self._quality_manager.getQualityGroups(self._global_stack)
            quality_group = quality_group_dict.get(quality_type)
            if quality_group is None:
                self._fixQualityChangesGroupToNotSupported(quality_changes_group)

        quality_changes_container = self._container_registry.empty_quality_changes_container
        quality_container = self._container_registry.empty_quality_container
        if quality_changes_group.node_for_global and quality_changes_group.node_for_global.getContainer():
            quality_changes_container = quality_changes_group.node_for_global.getContainer()
        if quality_group is not None and quality_group.node_for_global and quality_group.node_for_global.getContainer():
            quality_container = quality_group.node_for_global.getContainer()

        self._global_stack.quality = quality_container
        self._global_stack.qualityChanges = quality_changes_container

        for position, extruder in self._global_stack.extruders.items():
            quality_changes_node = quality_changes_group.nodes_for_extruders.get(position)
            quality_node = None
            if quality_group is not None:
                quality_node = quality_group.nodes_for_extruders.get(position)

            quality_changes_container = self._container_registry.empty_quality_changes_container
            quality_container = self._container_registry.empty_quality_container
            if quality_changes_node and quality_changes_node.getContainer():
                quality_changes_container = quality_changes_node.getContainer()
            if quality_node and quality_node.getContainer():
                quality_container = quality_node.getContainer()

            extruder.quality = quality_container
            extruder.qualityChanges = quality_changes_container

        self._current_quality_group = quality_group
        self._current_quality_changes_group = quality_changes_group

    def _fixQualityChangesGroupToNotSupported(self, quality_changes_group):
        nodes = [quality_changes_group.node_for_global] + list(quality_changes_group.nodes_for_extruders.values())
        containers = [n.getContainer() for n in nodes if n is not None]
        for container in containers:
            container.setMetaDataEntry("quality_type", "not_supported")
        quality_changes_group.quality_type = "not_supported"

    def _setEmptyQuality(self) -> None:
        self._current_quality_group = None
        self._current_quality_changes_group = None
        self.global_stack.quality = self._container_registry.empty_quality_container
        self.global_stack.qualityChanges = self._container_registry.empty_quality_changes_container
        for extruder in self.global_stack.extruders.values():
            extruder.quality = self._container_registry.empty_quality_container
            extruder.qualityChanges = self._container_registry.empty_quality_changes_container

    @property
    def areMaterialsCompatible(self) -> bool:
        result = True
        if Util.parseBool(self.global_stack.getMetaDataEntry("has_materials", False)):
            for position, extruder in self.global_stack.extruders.items():
                if not extruder.isEnabled:
                    continue
                if not extruder.material.getMetaDataEntry("compatible"):
                    result = False
                    break
        return result

    @property
    def isQualitySupported(self) -> bool:
        is_supported = False
        if self._current_quality_group:
            is_supported = self._current_quality_group.is_available
        return is_supported

    @property
    def isCurrentSetupSupported(self) -> bool:
        result = True
        for stack in [self.global_stack] + list(self.global_stack.extruders.values()):
            for container in stack.getContainers():
                if not container:
                    result = False
                    break
                if not Util.parseBool(container.getMetaDataEntry("supported", True)):
                    result = False
                    break
        return result

    @property
    def isBuildplateCompatible(self) -> bool:
        buildplate_compatible = True  # It is compatible by default
        buildplate_name = self.global_stack.variant.getName()
        extruder_stacks = self.global_stack.extruders.values()
        for stack in extruder_stacks:
            if not stack.isEnabled:
                continue

            material_container = stack.material
            if material_container.getId() == self._container_registry.empty_material_container.getId():
                continue
            if material_container.getMetaDataEntry("buildplate_compatible"):
                buildplate_compatible = buildplate_compatible and material_container.getMetaDataEntry("buildplate_compatible").get(buildplate_name, True)

        return buildplate_compatible

    @property
    def isBuildplateUsable(self) -> bool:
        # Here the next formula is being calculated:
        # result = (not (material_left_compatible and material_right_compatible)) and
        #           (material_left_compatible or material_left_usable) and
        #           (material_right_compatible or material_right_usable)
        result = not self.isBuildplateCompatible
        extruder_stacks = self._global_stack.extruders.values()
        for stack in extruder_stacks:
            material_container = stack.material
            if material_container == self._container_registry.empty_material_container:
                continue
            buildplate_compatible = material_container.getMetaDataEntry("buildplate_compatible")[self.activeVariantBuildplateName] if material_container.getMetaDataEntry("buildplate_compatible") else True
            buildplate_usable = material_container.getMetaDataEntry("buildplate_recommended")[self.activeVariantBuildplateName] if material_container.getMetaDataEntry("buildplate_recommended") else True

            result = result and (buildplate_compatible or buildplate_usable)

        return result

    def checkHaveErrors(self) -> bool:
        import time
        time_start = time.time()

        if self.global_stack.hasErrors():
            Logger.log("d", "Checking global stack for errors took %0.2f s and we found an error" % (
                        time.time() - time_start))
            return True

        machine_extruder_count = self.global_stack.getProperty("machine_extruder_count", "value")
        extruder_stacks = list(self.global_stack.extruders.values())
        count = 1  # we start with the global stack
        for stack in extruder_stacks:
            md = stack.getMetaData()
            if "position" in md and int(md["position"]) >= machine_extruder_count:
                continue
            count += 1
            if stack.hasErrors():
                Logger.log("d", "Checking %s stacks for errors took %.2f s and we found an error in stack [%s]",
                           count, time.time() - time_start, str(stack))
                return True

        Logger.log("d", "Checking %s stacks for errors took %.2f s", count, time.time() - time_start)
        return False

    def isHardwareCompatible(self) -> bool:
        return self.areMaterialsCompatible and self.isBuildplateCompatible

    def getEnabledExtruders(self) -> Dict:
        return {p: e for p, e in self.global_stack.extruders.items() if e.isEnabled()}
