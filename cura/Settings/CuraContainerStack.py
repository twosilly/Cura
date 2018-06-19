# Copyright (c) 2017 Ultimaker B.V.
# Cura is released under the terms of the LGPLv3 or higher.

from typing import Any, Optional

from UM.Decorators import override
from UM.Settings.ContainerStack import ContainerStack, InvalidContainerStackError
from UM.Settings.InstanceContainer import InstanceContainer
from UM.Settings.DefinitionContainer import DefinitionContainer
from UM.Settings.ContainerRegistry import ContainerRegistry
from UM.Settings.Interfaces import ContainerInterface, DefinitionContainerInterface

from . import Exceptions
from .CuraContainerIndexes import CuraContainerIndexes


##  Base class for Cura related stacks that want to enforce certain containers are available.
#
#   This class makes sure that the stack has the following containers set: user changes, quality
#   changes, quality, material, variant, definition changes and finally definition. Initially,
#   these will be equal to the empty instance container.
#
#   The container types are determined based on the following criteria:
#   - user: An InstanceContainer with the metadata entry "type" set to "user".
#   - quality changes: An InstanceContainer with the metadata entry "type" set to "quality_changes".
#   - quality: An InstanceContainer with the metadata entry "type" set to "quality".
#   - material: An InstanceContainer with the metadata entry "type" set to "material".
#   - variant: An InstanceContainer with the metadata entry "type" set to "variant".
#   - definition changes: An InstanceContainer with the metadata entry "type" set to "definition_changes".
#   - definition: A DefinitionContainer.
#
#   Internally, this class ensures the mentioned containers are always there and kept in a specific order.
#   This also means that operations on the stack that modifies the container ordering is prohibited and
#   will raise an exception.
class CuraContainerStack(ContainerStack):
    def __init__(self, container_id: str):
        super().__init__(container_id)

        self._container_registry = ContainerRegistry.getInstance()

        self._empty_instance_container = self._container_registry.getEmptyInstanceContainer()

        self._empty_quality_changes = self._container_registry.findInstanceContainers(id = "empty_quality_changes")[0]
        self._empty_quality = self._container_registry.findInstanceContainers(id = "empty_quality")[0]
        self._empty_material = self._container_registry.findInstanceContainers(id = "empty_material")[0]
        self._empty_variant = self._container_registry.findInstanceContainers(id = "empty_variant")[0]

        self._containers = [self._empty_instance_container for _ in range(len(CuraContainerIndexes.IndexTypeMap))]
        self._containers[CuraContainerIndexes.QualityChanges] = self._empty_quality_changes
        self._containers[CuraContainerIndexes.Quality] = self._empty_quality
        self._containers[CuraContainerIndexes.Material] = self._empty_material
        self._containers[CuraContainerIndexes.Variant] = self._empty_variant

    def setUserChanges(self, new_user_changes: InstanceContainer) -> None:
        self.replaceContainer(CuraContainerIndexes.UserChanges, new_user_changes)

    def getUserChanges(self) -> InstanceContainer:
        return self._containers[CuraContainerIndexes.UserChanges]

    def setQualityChanges(self, new_quality_changes: InstanceContainer) -> None:
        self.replaceContainer(CuraContainerIndexes.QualityChanges, new_quality_changes)

    def getQualityChanges(self) -> InstanceContainer:
        return self._containers[CuraContainerIndexes.QualityChanges]

    def setQuality(self, new_quality: InstanceContainer) -> None:
        self.replaceContainer(CuraContainerIndexes.Quality, new_quality)

    def getQuality(self) -> InstanceContainer:
        return self._containers[CuraContainerIndexes.Quality]

    def setMaterial(self, new_material: InstanceContainer) -> None:
        self.replaceContainer(CuraContainerIndexes.Material, new_material)

    def getMaterial(self) -> InstanceContainer:
        return self._containers[CuraContainerIndexes.Material]

    def getVariant(self) -> InstanceContainer:
        return self._containers[CuraContainerIndexes.Variant]

    def setVariant(self, new_variant: InstanceContainer) -> None:
        self.replaceContainer(CuraContainerIndexes.Variant, new_variant)

    def setDefinitionChanges(self, new_definition_changes: InstanceContainer) -> None:
        self.replaceContainer(CuraContainerIndexes.DefinitionChanges, new_definition_changes)

    def getDefinitionChanges(self) -> InstanceContainer:
        return self._containers[CuraContainerIndexes.DefinitionChanges]

    def setDefinition(self, new_definition: DefinitionContainerInterface) -> None:
        self.replaceContainer(CuraContainerIndexes.Definition, new_definition)

    def getDefinition(self) -> DefinitionContainer:
        return self._containers[CuraContainerIndexes.Definition]

    userChanges = property(getUserChanges, setUserChanges)
    qualityChanges = property(getQualityChanges, setQualityChanges)
    quality = property(getQuality, setQuality)
    material = property(getMaterial, setMaterial)
    variant = property(getVariant, setVariant)
    definitionChanges = property(getDefinitionChanges, setDefinitionChanges)
    definition = property(getDefinition, setDefinition)

    @override(ContainerStack)
    def getBottom(self) -> "DefinitionContainer":
        return self.definition

    @override(ContainerStack)
    def getTop(self) -> "InstanceContainer":
        return self.userChanges

    def setProperty(self, key: str, property_name: str, new_value: Any, target_container: str = "user") -> None:
        container_index = CuraContainerIndexes.TypeIndexMap.get(target_container, -1)
        if container_index != -1:
            self._containers[container_index].setProperty(key, property_name, new_value)
        else:
            raise IndexError("Invalid target container {type}".format(type = target_container))

    @override(ContainerStack)
    def addContainer(self, container: ContainerInterface) -> None:
        raise Exceptions.InvalidOperationError("Cannot add a container to Global stack")

    @override(ContainerStack)
    def insertContainer(self, index: int, container: ContainerInterface) -> None:
        raise Exceptions.InvalidOperationError("Cannot insert a container into Global stack")

    @override(ContainerStack)
    def removeContainer(self, index: int = 0) -> None:
        raise Exceptions.InvalidOperationError("Cannot remove a container from Global stack")

    @override(ContainerStack)
    def replaceContainer(self, index: int, container: ContainerInterface) -> None:
        expected_type = CuraContainerIndexes.IndexTypeMap[index]
        if expected_type == "definition":
            if not isinstance(container, DefinitionContainer):
                raise Exceptions.InvalidContainerError("Cannot replace container at index {index} with a container that is not a DefinitionContainer".format(index = index))
        elif container != self._empty_instance_container and container.getMetaDataEntry("type") != expected_type:
            raise Exceptions.InvalidContainerError("Cannot replace container at index {index} with a container that is not of {type} type, but {actual_type} type.".format(index = index, type = expected_type, actual_type = container.getMetaDataEntry("type")))

        current_container = self._containers[index]
        if current_container.getId() == container.getId():
            return

        super().replaceContainer(index, container)

    @override(ContainerStack)
    def deserialize(self, contents: str, file_name: Optional[str] = None) -> None:
        super().deserialize(contents, file_name)

        new_containers = self._containers.copy()
        while len(new_containers) < len(CuraContainerIndexes.IndexTypeMap):
            new_containers.append(self._empty_instance_container)

        # Validate and ensure the list of containers matches with what we expect
        for index, type_name in CuraContainerIndexes.IndexTypeMap.items():
            try:
                container = new_containers[index]
            except IndexError:
                container = None

            if type_name == "definition":
                if not container or not isinstance(container, DefinitionContainer):
                    definition = self.findContainer(container_type = DefinitionContainer)
                    if not definition:
                        raise InvalidContainerStackError("Stack {id} does not have a definition!".format(id = self.getId()))

                    new_containers[index] = definition
                continue

            if not container or container.getMetaDataEntry("type") != type_name:
                actual_container = self.findContainer(type = type_name)
                if actual_container:
                    new_containers[index] = actual_container
                else:
                    new_containers[index] = self._empty_instance_container

        self._containers = new_containers

    def _getMachineDefinition(self) -> DefinitionContainer:
        return self.definition

    ##  getProperty for extruder positions, with translation from -1 to default extruder number
    def getExtruderPositionValueWithDefault(self, key):
        value = self.getProperty(key, "value")
        if value == -1:
            from UM.Application import Application
            value = int(Application.getInstance().getMachineManager().defaultExtruderPosition)
        return value
