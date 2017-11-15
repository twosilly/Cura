from collections import deque

from PyQt5.QtCore import QObject, pyqtProperty, pyqtSlot, pyqtSignal

from UM.Application import Application
from UM.Logger import Logger
from UM.Settings.ContainerRegistry import ContainerRegistry
from UM.Signal import postponeSignals, CompressTechnique

from cura.Settings.CureCoreAPI import CuraCoreAPI


class Machine(QObject):

    def __init__(self, machine_id, name, parent = None):
        super().__init__(parent)
        self._id = machine_id
        self._name = name

        self._global_stack = None  # the global stack which represents this machine
        self._extruder_stack_list = None  # a list of extruder stacks this machine has in the order of positions

        self._all_quality_changes_dict = {}
        self._all_quality_dict = {}
        self._usable_quality_type_list = []  # a list of quality types that are usable
        self._usable_quality_changes_name_list = []  # a list of quality_changes names that are usable

        # for postponing setting the variants, materials, qualities, and quality_changes
        self._pending_container_changes = deque()

        # for convenience
        self._container_registry = ContainerRegistry.getInstance()
        self._core = CuraCoreAPI()
        self._empty_variant = self._container_registry.findInstanceContainers(id = "empty_variant")[0]
        self._empty_material = self._container_registry.findInstanceContainers(id = "empty_material")[0]
        self._empty_quality = self._container_registry.findInstanceContainers(id = "empty_quality")[0]
        self._empty_quality_changes = self._container_registry.findInstanceContainers(id = "empty_quality_changes")[0]

        self._active_extruder_index = 0

    activeExtruderIndexChanged = pyqtSignal()

    @pyqtProperty(str)
    def id(self):
        return self._id

    @pyqtProperty(str)
    def name(self):
        return self._name

    @pyqtProperty(str)
    def qualityId(self):
        return self._global_stack.quality.getId()

    @pyqtProperty(str)
    def qualityChangesId(self):
        return self._global_stack.qualityChanges.getId()

    def setActiveExtruderIndex(self, extruder_position):
        extruder_position = int(extruder_position)
        if extruder_position >= len(self._extruder_stack_list):
            Logger.log("e", "machine [%s] doesn't have extruder [%s]", self._name, extruder_position)
            return

        # TODO: also check user specified extruder count

        if extruder_position == self._active_extruder_index:
            Logger.log("i", "same extruder [%s], won't do anything", extruder_position)
            return
        self._active_extruder_index = extruder_position
        self.activeExtruderIndexChanged.emit()

    @pyqtProperty(int, fset = setActiveExtruderIndex, notify = activeExtruderIndexChanged)
    def activeExtruderIndex(self):
        return self._active_extruder_index

    def initialize(self):
        # find the machine stack
        machine_stack = self._container_registry.findContainerStacks(id = self._id,
                                                                     type = "machine")
        if not machine_stack:
            raise RuntimeError("Could not find machine stack [%s]" % self._id)
        machine_stack = machine_stack[0]

        # find the extruder stacks
        extruder_stack_list = self._container_registry.findContainerStacks(type = "extruder_train",
                                                                           machine = self._id)
        if not extruder_stack_list:
            raise RuntimeError("Could not find extruder stacks for machine [%s]" % self._id)

        self._global_stack = machine_stack
        self._extruder_stack_list = extruder_stack_list

        self._active_extruder_index = 0

        # perform some sanity checks and cleanups to fix some potential legacy issues
        self._sanitize()

        # connect signals
        for extruder_stack in self._extruder_stack_list:
            extruder_stack.pyqtVariantChanged.connect(self._onExtruderVariantChanged)
            extruder_stack.pyqtMaterialChanged.connect(self._onExtruderMaterialChanged)

        # update the quality and quality_changes for this machine
        self.updateQualityAndQualityChanges()

    def _sanitize(self):
        # The global stack should have empty containers for material and variant
        if self._global_stack.material.getId() != self._empty_material.getId():
            self._global_stack.material = self._empty_material
        if self._global_stack.variant.getId() != self._empty_variant.getId():
            self._global_stack.variant = self._empty_variant

    def _onExtruderVariantChanged(self, stack_id):
        extruder_stack = None
        for extruder in self._extruder_stack_list:
            if extruder.getId() == stack_id:
                extruder_stack = extruder
                break
        self.setMaterial(extruder_stack.material.getId(), extruder_stack.getMetaDataEntry("position"))

    def _onExtruderMaterialChanged(self, stack_id):
        self.updateQualityAndQualityChanges()

    @pyqtSlot(str, int)
    def setVariant(self, variant_name, extruder_position = 0):
        with postponeSignals(*self._getAllContainerChangedSignals(), compress = CompressTechnique.CompressPerParameterValue):
            extruder_position = str(extruder_position)
            extruder_stack = self._extruder_stack_list.get(extruder_position)
            if extruder_stack is None:
                Logger.log("e", "Could not find extruder at position [%s] for machine [%s], will not change its variant.",
                           extruder_position, self._id)
                return

            # find the variant
            variant = self._container_registry.findInstanceContainers(name = variant_name,
                                                                      type = "variant",
                                                                      definition = self._global_stack.definition.getId())
            if not variant:
                Logger.log("e", "Could not find variant with name [%s] for machine [%s] at extruder position [%s]",
                           variant_name, self._global_stack.getId(), extruder_position)
                return
            variant = variant[0]

            if variant.getId() == extruder_stack.variant.getId():
                Logger.log("i", "Same variant [%s] for machine [%s] extruder position [%s], will not change it.",
                           variant.getId(), self._global_stack.getId(), extruder_position)
                return

            # change variant (postponed)
            self._pending_container_changes.append({"extruder": extruder_stack, "variant": variant})
            Application.getInstance().callLater(self._setNewContainers)

            # update material
            self.setMaterial(extruder_position, extruder_stack.material.getId(), new_variant = variant)

    @pyqtSlot(str, int)
    def setMaterial(self, material_id, extruder_position = 0, new_variant = None):
        """
        Sets the material on the given extruder position on this machine.
        :param extruder_position: The extruder position.
        :param material_id: ID of the material, whether the base name or not.
        """
        with postponeSignals(*self._getAllContainerChangedSignals(), compress = CompressTechnique.CompressPerParameterValue):
            extruder_position = int(extruder_position)
            if extruder_position >= len(self._extruder_stack_list):
                Logger.log("e", "Could not find extruder at position [%s] for machine [%s], will not change its material.",
                           extruder_position, self._id)
                return
            extruder_stack = self._extruder_stack_list[extruder_position]

            # find the specific material for this extruder
            variant_to_use = new_variant if new_variant is not None else extruder_stack.variant
            specific_material = self._core.getSpecificMaterialById(material_id, self._global_stack, variant_to_use)
            if extruder_stack.material.getId() == specific_material.getId():
                Logger.log("i", "Same material [%s]->[%s] for machine [%s] extruder position [%s], will not change it.",
                           material_id, specific_material, self._global_stack.getId(), extruder_position)
                return

            # change material (postponed)
            self._pending_container_changes.append({"stack": extruder_stack, "material": specific_material})
            Application.getInstance().callLater(self._setNewContainers)

            # update quality and quality changes
            self.updateQualityAndQualityChanges()

    @pyqtSlot(str)
    def setQuality(self, quality_type_or_quality_changes_name: str):
        quality_group = self._usable_quality_type_dict.get(quality_type_or_quality_changes_name)
        quality_changes_group = self._usable_quality_changes_name_list.get(quality_type_or_quality_changes_name)
        if quality_group is None and quality_changes_group is None:
            Logger.log("e", "Could not find any quality_type or quality_changes with name [%s]",
                       quality_type_or_quality_changes_name)
            return

        with postponeSignals(*self._getAllContainerChangedSignals(), compress = CompressTechnique.CompressPerParameterValue):
            stacks = [self._global_stack] + self._extruder_stack_list
            if quality_changes_group is not None:
                quality_type = quality_changes_group.machine_quality_changes.getMetaDataEntry("type")
                quality_group = quality_group[quality_type]
                quality_changes = [quality_changes_group.machine_quality_changes] + quality_changes_group.extruder_quality_changes
            else:
                quality_changes = [self._empty_quality_changes for _ in stacks]

            qualities = [quality_group.machine_quality] + quality_group.extruder_qualities
            for idx, stack in enumerate(stacks):
                stack.quality = qualities[idx]
                stack.quality_changes = quality_changes[idx]

    def updateQualityAndQualityChanges(self):
        """
        Updates quality and quality_changes for the current machine because of variant and/or material changes.
        """
        with postponeSignals(*self._getAllContainerChangedSignals(), compress = CompressTechnique.CompressPerParameterValue):
            current_global_quality = self._global_stack.quality
            current_quality_type = current_global_quality.getMetaDataEntry("quality_type", "")
            current_global_quality_changes = self._global_stack.qualityChanges

            results = self._core.getQualitiesForMachineByName(self._global_stack.getName(),
                                                              pending_container_changes = self._pending_container_changes)

            # update results
            self._all_quality_changes_dict = results.quality_changes
            self._all_quality_dict = results.qualities

            self._usable_quality_type_list = results.usable_quality_types
            self._usable_quality_changes_name_list = results.usable_quality_changes_names

            # Decide which quality_changes to use
            switch_to_quality_changes_name = None
            switch_to_quality_type = None
            if current_global_quality_changes.getId() != "empty_quality_changes" \
                    and current_global_quality_changes.getMetaDataEntry("quality_type") in results.usable_quality_types:
                # only keep the current quality_changes if it's still usable
                switch_to_quality_changes_name = current_global_quality_changes.getName()
                switch_to_quality_type = current_global_quality_changes.getMetaDataEntry("quality_type")

            if switch_to_quality_type is None:
                # Decide with quality type to switch to according to the following rules:
                #  1. if the current quality type was "not supported", switch to the preferred quality if available or the
                #     first available quality.
                #  2. if the current quality type will still be supported, still use that quality type.
                #  3. if the current quality type will no longer be supported, switch to the preferred quality if available
                #     or the first available quality.
                if current_global_quality.getId() != "empty_quality":
                    if current_quality_type in results.usable_quality_types:
                        # use the same quality type if it's still usable
                        switch_to_quality_type = current_quality_type
                if switch_to_quality_type is None:
                    if results.usable_quality_types:
                        # use the preferred/the first available quality type
                        # TODO: preferred

                        switch_to_quality_type = sorted(results.usable_quality_types)[0]

            # check if there is any container change
            if switch_to_quality_type is None:
                # TODO: switch all to not supported
                def _set_to_not_supported(stack):
                    if stack.quality.getId() != "empty_quality":
                        self._pending_container_changes.append({"stack": stack,
                                                                "quality": self._empty_quality})
                    if stack.quality_changes.getId() != "empty_quality_changes":
                        self._pending_container_changes.append({"stack": stack,
                                                                "quality_changes": self._empty_quality_changes})

                _set_to_not_supported(self._global_stack)
                for extruder_stack in self._extruder_stack_list:
                    _set_to_not_supported(extruder_stack)
            else:
                # get the quality and quality_changes (optional) groups to set to
                quality_group = results.qualities[switch_to_quality_type]
                quality_changes_group = None
                if switch_to_quality_changes_name is not None:
                    quality_changes_group = results.quality_changes[switch_to_quality_changes_name]

                def _set_quality_and_quality_changes(stack, quality, quality_changes):
                    if stack.quality.getId() != quality.getId():
                        self._pending_container_changes.append({"stack": stack,
                                                                "quality": quality})
                    if stack.qualityChanges.getId() != quality_changes.getId():
                        self._pending_container_changes.append({"stack": stack,
                                                                "quality_changes": quality_changes})

                _set_quality_and_quality_changes(self._global_stack,
                                                 quality_group.machine_quality,
                                                 quality_changes_group.machine_quality_changes if quality_changes_group else self._empty_quality_changes)
                for idx, extruder_stack in enumerate(self._extruder_stack_list):
                    _set_quality_and_quality_changes(extruder_stack,
                                                     quality_group.extruder_qualities[idx],
                                                     quality_changes_group.extruder_quality_changes[idx] if quality_changes_group else self._empty_quality_changes)

            Application.getInstance().callLater(self._setNewContainers)

    def _setNewContainers(self):
        while self._pending_container_changes:
            change = self._pending_container_changes.popleft()
            stack = change.get("stack")
            variant = change.get("variant")
            material = change.get("material")
            quality = change.get("quality")
            quality_changes = change.get("quality_changes")

            if variant is not None:
                stack.variant = variant
            if material is not None:
                stack.material = material
            if quality is not None:
                stack.quality = quality
            if quality_changes is not None:
                stack.quality_changes = quality_changes

    def _getAllContainerChangedSignals(self):
        return [s.containersChanged for s in [self._global_stack] + self._extruder_stack_list]
