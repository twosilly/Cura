# Copyright (c) 2018 Ultimaker B.V.
# Cura is released under the terms of the LGPLv3 or higher.

from typing import Optional, TYPE_CHECKING

from UM.Logging.Logger import Logger
from UM.Settings.Interfaces import DefinitionContainerInterface
from UM.Settings.InstanceContainer import InstanceContainer

from cura.Machines.VariantManager import VariantType
from .GlobalStack import GlobalStack
from .ExtruderStack import ExtruderStack

if TYPE_CHECKING:
    from UM.Application import Application


##  Contains helper functions to create new machines.
class CuraStackBuilder:

    def __init__(self, application: "Application"):
        self._application = application
        self._variant_manager = self._application.getVariantManager()
        self._material_manager = self._application.getMaterialManager()
        self._quality_manager = self._application.getQualityManager()
        self._container_registry = self._application.getContainerRegistry()

    ##  Create a new instance of a machine.
    #
    #   \param name The name of the new machine.
    #   \param definition_id The ID of the machine definition to use.
    #
    #   \return The new global stack or None if an error occurred.
    def createMachine(self, name: str, definition_id: str) -> Optional[GlobalStack]:
        definitions = self._container_registry.findDefinitionContainers(id = definition_id)
        if not definitions:
            msg = "Definition {definition} was not found!".format(definition = definition_id)
            Logger.log("w", msg)
            raise RuntimeError(msg)

        machine_definition = definitions[0]

        # get variant container for the global stack
        global_variant_container = self._container_registry.empty_variant_container
        global_variant_node = self._variant_manager.getDefaultVariantNode(machine_definition, VariantType.BUILD_PLATE)
        if global_variant_node:
            global_variant_container = global_variant_node.getContainer()
        if not global_variant_container:
            global_variant_container = self._container_registry.empty_variant_container

        # get variant container for extruders
        extruder_variant_container = self._container_registry.empty_variant_container
        extruder_variant_node = self._variant_manager.getDefaultVariantNode(machine_definition, VariantType.NOZZLE)
        extruder_variant_name = None
        if extruder_variant_node:
            extruder_variant_container = extruder_variant_node.getContainer()
            if not extruder_variant_container:
                extruder_variant_container = self._container_registry.empty_variant_container
            extruder_variant_name = extruder_variant_container.getName()

        generated_name = self._container_registry.createUniqueName("machine", "", name, machine_definition.getName())
        # Make sure the new name does not collide with any definition or (quality) profile
        # createUniqueName() only looks at other stacks, but not at definitions or quality profiles
        # Note that we don't go for uniqueName() immediately because that function matches with ignore_case set to true
        if self._container_registry.findContainersMetadata(id = generated_name):
            generated_name = self._container_registry.uniqueName(generated_name)

        new_global_stack = self.createGlobalStack(
            new_stack_id = generated_name,
            definition = machine_definition,
            variant_container = global_variant_container,
            material_container = self._container_registry.empty_material_container,
            quality_container = self._container_registry.empty_quality_container,
        )
        new_global_stack.setName(generated_name)

        # get material container for extruders
        material_container = self._container_registry.empty_material_container
        material_node = self._material_manager.getDefaultMaterial(new_global_stack, extruder_variant_name)
        if material_node and material_node.getContainer():
            material_container = material_node.getContainer()

        # Create ExtruderStacks
        extruder_dict = machine_definition.getMetaDataEntry("machine_extruder_trains")

        for position, extruder_definition_id in extruder_dict.items():
            # Sanity check: make sure that the positions in the extruder definitions are same as in the machine
            # definition
            extruder_definition = self._container_registry.findDefinitionContainers(id = extruder_definition_id)[0]
            position_in_extruder_def = extruder_definition.getMetaDataEntry("position")
            if position_in_extruder_def != position:
                # TODO:
                raise RuntimeError()

            new_extruder_id = self._container_registry.uniqueName(extruder_definition_id)
            new_extruder = self.createExtruderStack(
                new_extruder_id,
                extruder_definition = extruder_definition,
                machine_definition_id = definition_id,
                position = position,
                variant_container = extruder_variant_container,
                material_container = material_container,
                quality_container = self._container_registry.empty_quality_container
            )
            new_extruder.setNextStack(new_global_stack)
            new_global_stack.addExtruder(new_extruder)

        for new_extruder in new_global_stack.extruders.values():
            self._container_registry.addContainer(new_extruder)

        preferred_quality_type = machine_definition.getMetaDataEntry("preferred_quality_type")
        quality_group_dict = self._quality_manager.getQualityGroups(new_global_stack)
        quality_group = quality_group_dict.get(preferred_quality_type)

        new_global_stack.quality = quality_group.node_for_global.getContainer()
        if not new_global_stack.quality:
            new_global_stack.quality = self._container_registry.empty_quality_container
        for position, extruder_stack in new_global_stack.extruders.items():
            if position in quality_group.nodes_for_extruders and quality_group.nodes_for_extruders[position].getContainer():
                extruder_stack.quality = quality_group.nodes_for_extruders[position].getContainer()
            else:
                extruder_stack.quality = self._container_registry.empty_quality_container

        # Register the global stack after the extruder stacks are created. This prevents the registry from adding another
        # extruder stack because the global stack didn't have one yet (which is enforced since Cura 3.1).
        self._container_registry.addContainer(new_global_stack)

        return new_global_stack

    ##  Create a new Extruder stack
    #
    #   \param new_stack_id The ID of the new stack.
    #   \param definition The definition to base the new stack on.
    #   \param machine_definition_id The ID of the machine definition to use for
    #   the user container.
    #   \param kwargs You can add keyword arguments to specify IDs of containers to use for a specific type, for example "variant": "0.4mm"
    #
    #   \return A new Global stack instance with the specified parameters.
    def createExtruderStack(self, new_stack_id: str, extruder_definition: DefinitionContainerInterface, machine_definition_id: str,
                            position: int,
                            variant_container, material_container, quality_container) -> ExtruderStack:
        stack = ExtruderStack(new_stack_id)
        stack.setName(extruder_definition.getName())
        stack.setDefinition(extruder_definition)

        stack.addMetaDataEntry("position", position)

        user_container = self.createUserChangesContainer(new_stack_id + "_user", machine_definition_id, new_stack_id,
                                                         is_global_stack = False)

        stack.definitionChanges = self.createDefinitionChangesContainer(stack, new_stack_id + "_settings")
        stack.variant = variant_container
        stack.material = material_container
        stack.quality = quality_container
        stack.qualityChanges = self._container_registry.empty_quality_changes_container
        stack.userChanges = user_container

        # Only add the created containers to the registry after we have set all the other
        # properties. This makes the create operation more transactional, since any problems
        # setting properties will not result in incomplete containers being added.
        self._container_registry.addContainer(user_container)

        return stack

    ##  Create a new Global stack
    #
    #   \param new_stack_id The ID of the new stack.
    #   \param definition The definition to base the new stack on.
    #   \param kwargs You can add keyword arguments to specify IDs of containers to use for a specific type, for example "variant": "0.4mm"
    #
    #   \return A new Global stack instance with the specified parameters.
    def createGlobalStack(self, new_stack_id: str, definition: DefinitionContainerInterface,
                          variant_container, material_container, quality_container) -> GlobalStack:
        stack = GlobalStack(new_stack_id)
        stack.setDefinition(definition)

        # Create user container
        user_container = self.createUserChangesContainer(new_stack_id + "_user", definition.getId(), new_stack_id,
                                                         is_global_stack = True)

        stack.definitionChanges = self.createDefinitionChangesContainer(stack, new_stack_id + "_settings")
        stack.variant = variant_container
        stack.material = material_container
        stack.quality = quality_container
        stack.qualityChanges = self._container_registry.empty_quality_changes_container
        stack.userChanges = user_container

        self._container_registry.addContainer(user_container)

        return stack

    def createUserChangesContainer(self, container_name: str, definition_id: str, stack_id: str,
                                   is_global_stack: bool) -> "InstanceContainer":
        unique_container_name = self._container_registry.uniqueName(container_name)

        container = InstanceContainer(unique_container_name)
        container.setDefinition(definition_id)
        container.addMetaDataEntry("type", "user")
        container.addMetaDataEntry("setting_version", self._application.SettingVersion)

        metadata_key_to_add = "machine" if is_global_stack else "extruder"
        container.addMetaDataEntry(metadata_key_to_add, stack_id)

        return container

    def createDefinitionChangesContainer(self, container_stack, container_name):
        unique_container_name = self._container_registry.uniqueName(container_name)

        definition_changes_container = InstanceContainer(unique_container_name)
        definition_changes_container.setDefinition(container_stack.getBottom().getId())
        definition_changes_container.addMetaDataEntry("type", "definition_changes")
        definition_changes_container.addMetaDataEntry("setting_version", self._application.SettingVersion)

        self._container_registry.addContainer(definition_changes_container)
        container_stack.definitionChanges = definition_changes_container

        return definition_changes_container
