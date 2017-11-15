from collections import namedtuple

from UM.Logger import Logger
from UM.Settings.ContainerRegistry import ContainerRegistry
from UM import Util


AllQualityResults = namedtuple("AllQualityResults",
                               ["usable_quality_types", "usable_quality_changes_names", "qualities", "quality_changes"])


class QualityGroup(object):

    def __init__(self, quality_type: str, usable: bool):
        self.quality_type = quality_type
        self.machine_quality = None
        self.extruder_qualities = []
        self.usable = usable
        self.max_extruder_count = 0
        self.user_specified_extruder_count = 0

    def initialize(self, max_extruder_count: int, user_specified_extruder_count: int):
        self.max_extruder_count = max_extruder_count
        self.user_specified_extruder_count = user_specified_extruder_count

        empty_quality_container = ContainerRegistry.getInstance().findInstanceContainers(id = "empty_quality")[0]
        self.machine_quality = empty_quality_container
        self.extruder_qualities = [empty_quality_container for _ in range(max_extruder_count)]

    def setQuality(self, extruder_position: int, quality_container):
        self.extruder_qualities[extruder_position] = quality_container

    def finalize(self):
        # If there is any empty quality, then this quality type is not supported
        # Only check the extruders that are enabled by user through setting the "number of extruders" for a machine
        all_qualities = [self.machine_quality] + self.extruder_qualities.values()[:self.user_specified_extruder_count]
        self.usable = not any(q.getId() == "empty_quality" for q in all_qualities)


class QualityChangesGroup(object):

    def __init__(self, name: str, usable: bool):
        self.name = name
        self.machine_quality_changes = None
        self.extruder_quality_changes = []
        self.usable = usable
        self.max_extruder_count = 0
        self.user_specified_extruder_count = 0

    def initialize(self, max_extruder_count: int, user_specified_extruder_count: int):
        self.max_extruder_count = max_extruder_count
        self.user_specified_extruder_count = user_specified_extruder_count

        empty_quality_changes_container = ContainerRegistry.getInstance().findInstanceContainers(id = "empty_quality_changes")[0]
        self.machine_quality_changes = empty_quality_changes_container
        self.extruder_quality_changes = [empty_quality_changes_container for _ in range(max_extruder_count)]

    def setMachineQualityChanges(self, quality_changes_container):
        self.machine_quality_changes = quality_changes_container

    def setExtruderQualityChanges(self, extruder_position: int, quality_changes_container):
        self.extruder_quality_changes[extruder_position] = quality_changes_container

    def finalize(self):
        # If there is any empty quality, then this quality type is not supported
        # Only check the extruders that are enabled by user through setting the "number of extruders" for a machine
        all_qualities = [self.machine_quality_changes] + self.extruder_quality_changes.values()[:self.user_specified_extruder_count]
        self.usable = not any(q.getId() == "empty_quality" for q in all_qualities)


class CuraCoreAPI(object):

    def __init__(self):
        self._container_registry = ContainerRegistry.getInstance()
        self._machine_manager = None

    def getQualitiesForMachineByName(self, machine_name, pending_container_changes = None):
        # get the machine and its definition
        machine = self._container_registry.findContainerStacks(name = machine_name,
                                                               type = "machine")
        if not machine:
            Logger.log("e", "Could not find machine with name [%s]", machine_name)
            return
        machine = machine[0]

        pending_container_changes_dict = {}
        if pending_container_changes:
            for change in pending_container_changes:
                position = int(change["stack"].getMetaDataEntry("position"))
                if position not in pending_container_changes_dict:
                    pending_container_changes_dict[position] = {}
                for k, v in change.items():
                    if k != "stack":
                        pending_container_changes_dict[position][k] = v

        # only check the extruders that are enabled
        max_extruder_count = len(machine.extruders)
        user_specified_extruder_count = int(machine.getMetaDataEntry("machine_extruder_count", max_extruder_count))

        # for convenience, will be used to find the extruder positions in quality changes.
        machine_extruder_id_to_position_map = {}
        for position, stack in machine.extruders.items():
            machine_extruder_id_to_position_map[stack.definition.getId()] = int(position)

        # get usable qualities for each extruder and use the intersection
        # Aggregate all qualities and quality_changes with the commonly usable quality types
        all_results = AllQualityResults(usable_quality_types = [],
                                        usable_quality_changes_names = [],
                                        qualities = {},
                                        quality_changes = {})
        result_list = []
        commonly_usable_quality_types = set()
        for position in sorted([int(p) for p in machine.extruders]):
            extruder_stack = machine.extruders[str(position)]

            variant_to_use = pending_container_changes_dict.get(position, {}).get("variant")
            if variant_to_use is None:
                variant_to_use = extruder_stack.variant
            material_to_use = pending_container_changes_dict.get(position, {}).get("variant")
            if material_to_use is None:
                material_to_use = extruder_stack.material

            results = self.getUsableQualities(machine, variant_to_use, material_to_use)
            result_list.append(results)

            Logger.log("d", "---- position [%s] usable quality types = [%s]", position, results["usable_quality_types"])

            # update commonly usable quality types
            if position == 0:
                commonly_usable_quality_types.update(results["usable_quality_types"])

            # for commonly usable quality types, only take into account the extruders that are used
            if position < user_specified_extruder_count:
                commonly_usable_quality_types = commonly_usable_quality_types.intersection(set(results["usable_quality_types"]))

        for quality_type in commonly_usable_quality_types:
            all_results.usable_quality_types.append(quality_type)
        Logger.log("d", "---- all usable quality types = [%s]", ", ".join(all_results.usable_quality_types))

        # Organize the results
        for idx, result in enumerate(result_list):
            # Process quality results
            # For qualities, there will be a set of quality containers for each quality type, one container for each
            # stack.
            # Here, we aggregate the quality results according to quality types, so if a quality type is selected,
            # the corresponding quality containers for each stack can be easily found.
            for quality in result["qualities"]:
                quality_type = quality.getMetaDataEntry("quality_type")
                usable = quality_type in all_results.usable_quality_types

                if quality_type not in all_results.qualities:
                    quality_group = QualityGroup(quality_type, usable)
                    quality_group.initialize(max_extruder_count, user_specified_extruder_count)
                    all_results.qualities[quality_type] = quality_group
                else:
                    quality_group = all_results.qualities[quality_type]

                if quality_group.machine_quality.getId() == "empty_quality":
                    # get the global quality for the machine stack
                    search_criteria = {"type": "quality",
                                       "definition": machine.definition.getId(),
                                       "quality_type": quality_type,
                                       "global_quality": "True"}
                    Logger.log("d", "---- search criteria = [%s]", search_criteria)
                    fallback_remove_keys = ["definition"]
                    while True:
                        machine_quality = self._container_registry.findInstanceContainers(**search_criteria)
                        if not machine_quality:
                            Logger.log("d", "!!!! could not find global quality, move on")
                            if not fallback_remove_keys:
                                break
                            del search_criteria[fallback_remove_keys.pop(0)]
                            continue
                        else:
                            quality_group.machine_quality = machine_quality[0]
                            Logger.log("d", "!!! got machine quality = [%s]", quality_group.machine_quality.getId())
                            break

                quality_group.setQuality(idx, quality)

            # Process quality_changes results
            # For quality_changes, we aggregate the results according their Names, because quality_type is not unique.
            # There can be multiple custom quality_changes profile based on the same quality_type.
            for quality_changes_name, quality_changes_list in result["quality_changes"].items():
                quality_changes_name = quality_changes_list[0].getName()
                quality_type = quality_changes_list[0].getMetaDataEntry("quality_type")
                usable = quality_type in all_results.usable_quality_types

                if quality_changes_name not in all_results.quality_changes:
                    quality_changes_group = QualityChangesGroup(quality_changes_name, usable)
                    quality_changes_group.initialize(max_extruder_count, user_specified_extruder_count)
                    all_results.quality_changes[quality_changes_name] = quality_changes_group
                else:
                    quality_changes_group = all_results.quality_changes[quality_changes_name]

                for quality_changes_container in quality_changes_list:
                    quality_changes_extruder_id = quality_changes_container.getMetaDataEntry("extruder", None)
                    if not quality_changes_extruder_id:
                        quality_changes_group.setMachineQualityChanges(quality_changes_container)
                    else:
                        quality_changes_group.setExtruderQualityChanges(machine_extruder_id_to_position_map[quality_changes_extruder_id],
                                                                        quality_changes_container)

                all_results.quality_changes[quality_changes_name] = quality_changes_group
                if usable:
                    all_results.usable_quality_changes_names.append(quality_changes_name)

        for quality_type, quality_group in all_results.qualities.items():
            Logger.log("d", "--- quality group [%10s], usable = [%s]",
                       quality_type, quality_group.usable)
            for c in [quality_group.machine_quality] + quality_group.extruder_qualities:
                Logger.log("d", "  --- [%s]", c.getId())
        for quality_changes_id, quality_changes_group in all_results.quality_changes.items():
            Logger.log("d", "--- quality_changes group [%50s] - [%s]",
                       quality_changes_id, quality_changes_group.usable)
            for c in [quality_changes_group.machine_quality_changes] + quality_changes_group.extruder_quality_changes:
                Logger.log("d", "  --- [%s]", c.getId())

        return all_results

    def getUsableQualitiesByIDs(self, machine_name, variant_name, material_id):
        """
        Gets all usable quality and quality_changes for the given machine, variant, and material.
        :param machine_name: Mame of the machine such as "My UM3".
        :param variant_name: Name of the variant such as "AA 0.4".
        :param material_id: ID of the material (may or may not be the general name such as "generic_pla"
        :return: A dict which contains all usable quality and quality_changes containers.
        """
        # get the machine and its definition
        machine = self._container_registry.findContainerStacks(name = machine_name,
                                                               type = "machine")
        if not machine:
            Logger.log("e", "Could not find machine with name [%s]", machine_name)
            return
        machine = machine[0]

        # get specific variant and material
        variant = self.getSpecificVariantByName(variant_name, machine)
        material = self.getSpecificMaterialById(material_id, machine, variant)

        return self.getUsableQualities(machine, variant, material)

    def getUsableQualities(self, machine, variant, material):
        machine_definition = machine.definition

        # prepare search criteria
        search_criteria = {"type": "quality"}
        has_machine_quality = Util.parseBool(machine_definition.getMetaDataEntry("has_machine_quality", False))
        if has_machine_quality:
            search_criteria["definition"] = machine_definition.getId()
            search_criteria["material"] = self.getSpecificMaterialById(material.getId(), machine, variant).getId()

        # get all usable qualities
        usable_quality_list = self._container_registry.findInstanceContainers(**search_criteria)
        usable_quality_type_list = set([q.getMetaDataEntry("quality_type") for q in usable_quality_list])

        # get quality_changes
        all_quality_changes_list = self._container_registry.findInstanceContainers(definition = search_criteria["definition"],
                                                                                   type = "quality_changes")
        usable_quality_changes_list = []
        for quality_changes in all_quality_changes_list:
            if quality_changes.getMetaDataEntry("quality_type") in usable_quality_type_list:
                usable_quality_changes_list.append(quality_changes)

        Logger.log("d", "-> for machine [%s], variant [%s], material [%s]",
                   machine.getName(), variant.getName(), material.getId())
        for q in usable_quality_list:
            Logger.log("d", "---> [quality] [%s] [%s]", q.getId(), q.getMetaDataEntry("quality_type"))
        for q in usable_quality_changes_list:
            Logger.log("d", "---> [quality_changes] [%s] [%s]", q.getId(), q.getMetaDataEntry("quality_type"))

        # There are one or more quality_changes for each global_stack and extruder_stack.
        # Group them according to names so later it will be easier to access.
        usable_quality_changes_dict = {}
        for quality_changes in usable_quality_changes_list:
            if quality_changes.getName() not in usable_quality_changes_dict:
                usable_quality_changes_dict[quality_changes.getName()] = []
            usable_quality_changes_dict[quality_changes.getName()].append(quality_changes)

        return {"usable_quality_types": usable_quality_type_list,
                "qualities": usable_quality_list,
                "quality_changes": usable_quality_changes_dict}

    def getBaseMaterialById(self, material_id):
        materials = self._container_registry.findInstanceContainers(id = material_id,
                                                                    type = "material")
        if not materials:
            raise RuntimeError("Could not find material [%s]" % material_id)
        return self.getBaseMaterial(materials[0])

    def getBaseMaterial(self, material):
        base_id = material.getMetaDataEntry("base_file")
        base_material = material
        if base_id != material.getId():
            materials = self._container_registry.findInstanceContainers(id = base_id,
                                                                        type = "material")
            if not materials:
                raise RuntimeError("Could not find base material container [%s] for material [%s]" %
                                   (base_id, material.getId()))
            base_material = materials[0]
        return base_material

    def getSpecificMaterialById(self, material_id, machine, variant):
        return self.getSpecificMaterial(self.getBaseMaterialById(material_id), machine, variant)

    def getSpecificMaterial(self, material, machine, variant):
        """
        Gets the specific material container for the given machine and variant.
        """
        base_material = self.getBaseMaterial(material)

        search_criteria = {"GUID": base_material.getMetaDataEntry("GUID"),
                           "base_file": base_material.getId(),
                           "type": "material"}

        machine_definition = machine.definition
        has_machine_materials = Util.parseBool(machine_definition.getMetaDataEntry("has_machine_materials", False))
        has_variants = Util.parseBool(machine_definition.getMetaDataEntry("has_variants", False))
        has_variant_materials = Util.parseBool(machine_definition.getMetaDataEntry("has_variant_materials", False))

        search_criteria["definition"] = machine_definition.getId() if has_machine_materials else "fdmprinter"
        if has_variants or has_variant_materials:
            search_criteria["variant"] = variant.getId()

        Logger.log("d", "--- look for specific material with [%s]", search_criteria)

        materials = self._container_registry.findInstanceContainers(**search_criteria)
        if not materials:
            raise RuntimeError("Could not find specific material for material [%s], machine type [%s], variant [%s]" %
                               (material.getId(), machine_definition.getId(), variant.getId()))
        elif len(materials) > 1:
            material_id_list = [m.getId() for m in materials]
            raise RuntimeError("Found more than 1 specific material for material [%s], machine type [%s], variant [%s]: [%s]" %
                               (material.getId(), machine_definition.getId(), variant.getId(), ", ".join(material_id_list)))
        return materials[0]

    def getSpecificVariantByName(self, variant_name, machine):
        """
        Gets the specific variant container for given machine.
        """
        machine_definition = machine.definition
        # variants are always machine-specific. There is no generic variant.
        variants = self._container_registry.findInstanceContainers(name = variant_name,
                                                                   type = "variant",
                                                                   definition = machine_definition.getId())
        if not variants:
            raise RuntimeError("Could not find variant named as [%s] for machine type [%s]" %
                               (variant_name, machine_definition.getId()))
        if len(variants) > 1:
            variant_id_list = [v.getId() for v in variants]
            raise RuntimeError("Found more than one variants with name [%s] for machine type [%s]: [%s]" %
                               (variant_name, machine_definition.getId(), ", ".join(variant_id_list)))
        return variants[0]
