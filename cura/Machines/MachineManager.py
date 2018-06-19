# Copyright (c) 2018 Ultimaker B.V.
# Cura is released under the terms of the LGPLv3 or higher.

from typing import List, Optional

from UM.Logging.Logger import Logger
from UM.i18n import i18nCatalog

from cura.Settings.ExtruderStack import ExtruderStack

from .Machine import Machine

catalog = i18nCatalog("cura")


class MachineManager:

    def __init__(self, application = None):
        self._application = application
        self._container_registry = self._application.getContainerRegistry()
        self._material_manager = self._application.getMaterialManager()
        self._variant_manager = self._application.getVariantManager()
        self._quality_manager = self._application.getQualityManager()
        self._stack_builder = self._application.getCuraStackBuilder()

        self._active_machine = None  # type: Optional[Machine]

        self._default_extruder_position = "0"  # to be updated when extruders are switched on and off

        self._stacks_have_errors = None  # type:Optional[bool]

    def getActiveMachine(self) -> "Machine":
        return self._active_machine

    def setActiveMachine(self, stack_id: str) -> None:
        containers = self._container_registry.findContainerStacks(id = stack_id, type = "machine")
        if not containers:
            raise RuntimeError("Cannot find machine global stack with ID {stack_id}".format(stack_id = stack_id))

        global_stack = containers[0]
        if not global_stack.isValid():
            msg = "Invalid global stack %s" % global_stack
            raise RuntimeError(msg)

        # Load all extruder stacks
        containers = self._container_registry.findContainerStacks(machine = stack_id, type = "extruder_train")
        if not containers:
            raise RuntimeError("Cannot find machine extruder stacks for global stack {stack_id}".format(stack_id = stack_id))

        for extruder_stack in containers:
            extruder_stack.setNext(global_stack)

    def getMachine(self, name: str) -> Optional["Machine"]:
        global_stacks = self._container_registry.findContainerStacks(name = name, type = "machine")
        global_stack = global_stacks[0] if global_stacks else None
        machine = Machine(self._application, global_stack)
        machine.initState()
        return machine

    def createMachine(self, name: str, definition_id: str) -> None:
        new_stack = self._stack_builder.createMachine(name, definition_id)
        self._container_registry.addContainer(new_stack)

    def renameMachine(self, machine_id: str, new_name: str) -> None:
        container_registry = self._container_registry
        machine_stack = container_registry.findContainerStacks(id = machine_id)
        if machine_stack:
            new_name = container_registry.createUniqueName("machine", machine_stack[0].getName(), new_name, machine_stack[0].definition.getName())
            machine_stack[0].setName(new_name)

    def removeMachine(self, machine_id: str) -> None:
        # If the machine that is being removed is the currently active machine, set another machine as the active machine.
        activate_new_machine = (self._global_stack and self._global_stack.getId() == machine_id)

        # activate a new machine before removing a machine because this is safer
        if activate_new_machine:
            machine_stacks = self._container_registry.findContainerStacksMetadata(type = "machine")
            other_machine_stacks = [s for s in machine_stacks if s["id"] != machine_id]
            if other_machine_stacks:
                self.setActiveMachine(other_machine_stacks[0]["id"])

        metadata = self._container_registry.findContainerStacksMetadata(id = machine_id)[0]
        network_key = metadata["um_network_key"] if "um_network_key" in metadata else None
        containers = self._container_registry.findInstanceContainersMetadata(type = "user", machine = machine_id)
        for container in containers:
            self._container_registry.removeContainer(container["id"])
            self._container_registry.removeContainer(machine_id)

        # If the printer that is being removed is a network printer, the hidden printers have to be also removed
        if network_key:
            metadata_filter = {"um_network_key": network_key}
            hidden_containers = self._container_registry.findContainerStacks(type = "machine", **metadata_filter)
            if hidden_containers:
                # This reuses the method and remove all printers recursively
                self.removeMachine(hidden_containers[0].getId())

    def updateDefaultExtruder(self) -> None:
        extruder_items = sorted(self._global_stack.extruders.items())
        old_position = self._default_extruder_position
        new_default_position = "0"
        for position, extruder in extruder_items:
            if extruder.isEnabled:
                new_default_position = position
                break
        if new_default_position != old_position:
            self._default_extruder_position = new_default_position

    def _setGlobalVariant(self, container_node):
        self._global_stack.variant = container_node.getContainer()
        if not self._global_stack.variant:
            self._global_stack.variant = self._application.empty_variant_container

    def setGlobalVariant(self, container_node):
        self._setGlobalVariant(container_node)
        self.updateMaterialWithVariant(None)  # Update all materials
        self._updateQualityWithMaterial()

    def getUsedExtruderStacks(self) -> List["ExtruderStack"]:
        global_stack = self._active_machine.global_stack
        container_registry = self._container_registry

        used_extruder_stack_ids = set()

        # Get the extruders of all meshes in the scene
        support_enabled = False
        support_bottom_enabled = False
        support_roof_enabled = False

        scene_root = self._application.getController().getScene().getRoot()

        if not global_stack:
            return []

        from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator
        from UM.Scene.SceneNode import SceneNode

        # Get the extruders of all printable meshes in the scene
        meshes = [node for node in DepthFirstIterator(scene_root) if isinstance(node, SceneNode) and node.isSelectable()]
        for mesh in meshes:
            extruder_stack_id = mesh.callDecoration("getActiveExtruder")
            if not extruder_stack_id:
                # No per-object settings for this node
                extruder_stack_id = global_stack.extruders["0"].getId()
            used_extruder_stack_ids.add(extruder_stack_id)

            # Get whether any of them use support.
            stack_to_use = mesh.callDecoration("getStack")  # if there is a per-mesh stack, we use it
            if not stack_to_use:
                # if there is no per-mesh stack, we use the build extruder for this mesh
                stack_to_use = container_registry.findContainerStacks(id = extruder_stack_id)[0]

            support_enabled |= stack_to_use.getProperty("support_enable", "value")
            support_bottom_enabled |= stack_to_use.getProperty("support_bottom_enable", "value")
            support_roof_enabled |= stack_to_use.getProperty("support_roof_enable", "value")

            # Check limit to extruders
            limit_to_extruder_feature_list = ["wall_0_extruder_nr",
                                              "wall_x_extruder_nr",
                                              "roofing_extruder_nr",
                                              "top_bottom_extruder_nr",
                                              "infill_extruder_nr",
                                              ]
            for extruder_nr_feature_name in limit_to_extruder_feature_list:
                extruder_nr = int(global_stack.getProperty(extruder_nr_feature_name, "value"))
                if extruder_nr == -1:
                    continue
                used_extruder_stack_ids.add(global_stack.extruders[str(extruder_nr)].getId())

        # Check support extruders
        if support_enabled:
            used_extruder_stack_ids.add(global_stack.extruders[self.extruderValueWithDefault(str(global_stack.getProperty("support_infill_extruder_nr", "value")))].getId())
            used_extruder_stack_ids.add(global_stack.extruders[self.extruderValueWithDefault(str(global_stack.getProperty("support_extruder_nr_layer_0", "value")))].getId())
            if support_bottom_enabled:
                used_extruder_stack_ids.add(global_stack.extruders[self.extruderValueWithDefault(str(global_stack.getProperty("support_bottom_extruder_nr", "value")))].getId())
            if support_roof_enabled:
                used_extruder_stack_ids.add(global_stack.extruders[self.extruderValueWithDefault(str(global_stack.getProperty("support_roof_extruder_nr", "value")))].getId())

        # The platform adhesion extruder. Not used if using none.
        if global_stack.getProperty("adhesion_type", "value") != "none":
            extruder_nr = str(global_stack.getProperty("adhesion_extruder_nr", "value"))
            if extruder_nr == "-1":
                extruder_nr = self._default_extruder_position
            used_extruder_stack_ids.add(global_stack.extruders[extruder_nr].getId())

        used_extruders = [e for e in global_stack.extruders.values() if e.getId() in used_extruder_stack_ids]
        return used_extruders

    def extruderValueWithDefault(self, value):
        if value == "-1":
            return self._default_extruder_position
        else:
            return value
