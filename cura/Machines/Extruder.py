from typing import Optional, TYPE_CHECKING

from UM.Logging.Logger import Logger

if TYPE_CHECKING:
    from UM.Application import Application
    from cura.Machines.ContainerNode import ContainerNode
    from cura.Settings.ExtruderStack import ExtruderStack
    from .Machine import Machine


class Extruder:

    def __init__(self, application: "Application", machine: "Machine", extruder_stack: "ExtruderStack") -> None:
        self._application = application  # type: Application
        self._container_registry = self._application.getContainerRegistry()
        self._variant_manager = self._application.getVariantManager()
        self._material_manager = self._application.getMaterialManager()

        self._machine = machine  # type: "Machine"
        self._extruder_stack = extruder_stack  # type: ExtruderStack

    def initialize(self) -> None:
        self.extruder_stack.setNextStack(self.machine.global_stack)

    @property
    def machine(self) -> "Machine":
        return self._machine

    @property
    def extruder_stack(self) -> "ExtruderStack":
        return self._extruder_stack

    def setMaterialByRootId(self, material_root_id: str) -> None:
        machine_definition_id = self.machine.global_stack.definition.getId()
        variant_name = self.extruder_stack.variant.getName()
        material_diameter = self.extruder_stack.approximateMaterialDiameter
        material_node = self._material_manager.getMaterialNode(machine_definition_id, variant_name, material_diameter,
                                                               material_root_id)
        self._setMaterialByContainerNode(material_node)

    def _setMaterialByContainerNode(self, container_node: Optional["ContainerNode"] = None):
        container = container_node.getContainer()
        if container is None:
            container = self._container_registry.empty_material_container
        self.extruder_stack.material = container

        # Update the machine quality
        self.machine.updateQuality()

    def updateMaterial(self) -> None:
        current_material_base_name = self.extruder_stack.material.getMetaDataEntry("base_file")
        current_variant_name = None
        if self.extruder_stack.variant.getId() != self._container_registry.empty_variant_container.getId():
            current_variant_name = self.extruder_stack.variant.getMetaDataEntry("name")

        approximate_material_diameter = self.extruder_stack.approximateMaterialDiameter
        candidate_materials = self._material_manager.getAvailableMaterials(
            self.machine.global_stack.definition,
            current_variant_name,
            approximate_material_diameter)

        if not candidate_materials:
            self._setMaterialByContainerNode(container_node = None)
            return

        if current_material_base_name in candidate_materials:
            new_material = candidate_materials[current_material_base_name]
            self._setMaterialByContainerNode(new_material)
            return

        # The current material is not available, find the preferred one
        material_node = self._material_manager.getDefaultMaterial(self.machine.global_stack, current_variant_name)
        if material_node is not None:
            self._setMaterialByContainerNode(material_node)

    def setVariantByName(self, variant_name: str) -> None:
        machine_definition_id = self.machine.global_stack.definition.getId()
        variant_node = self._variant_manager.getVariantNode(machine_definition_id, variant_name)
        if variant_node.getContainer() is None:
            Logger.log("e", "Could not find variant with name '{variant_name}', failed to set variant.",
                       variant_name = variant_name)
            return
        self._extruder_stack.variant = variant_node.getContainer()

        # Update material
        self.updateMaterial()
        self.machine.updateQuality()
