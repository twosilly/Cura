# Copyright (c) 2018 Ultimaker B.V.
# Cura is released under the terms of the LGPLv3 or higher.

import copy
import os
import re

from UM.Decorators import override
from UM.Logging.Logger import Logger
from UM.Settings.ContainerRegistry import ContainerRegistry
from UM.Settings.ContainerStack import ContainerStack
from UM.Settings.InstanceContainer import InstanceContainer

from . import ExtruderStack
from . import GlobalStack

from UM.i18n import i18nCatalog
catalog = i18nCatalog("cura")


class CuraContainerRegistry(ContainerRegistry):

    def initialize(self):
        super().initialize()

        self.__add_specific_empty_containers()

    def __add_specific_empty_containers(self) -> None:
        """
        Add empty containers for each type.
        """
        empty_definition_changes_container = copy.deepcopy(self.empty_container)
        empty_definition_changes_container.setMetaDataEntry("id", "empty_definition_changes")
        empty_definition_changes_container.addMetaDataEntry("type", "definition_changes")
        self.addContainer(empty_definition_changes_container)
        self.empty_definition_changes_container = empty_definition_changes_container

        empty_variant_container = copy.deepcopy(self.empty_container)
        empty_variant_container.setMetaDataEntry("id", "empty_variant")
        empty_variant_container.addMetaDataEntry("type", "variant")
        self.addContainer(empty_variant_container)
        self.empty_variant_container = empty_variant_container

        empty_material_container = copy.deepcopy(self.empty_container)
        empty_material_container.setMetaDataEntry("id", "empty_material")
        empty_material_container.addMetaDataEntry("type", "material")
        self.addContainer(empty_material_container)
        self.empty_material_container = empty_material_container

        empty_quality_container = copy.deepcopy(self.empty_container)
        empty_quality_container.setMetaDataEntry("id", "empty_quality")
        empty_quality_container.setName("Not Supported")
        empty_quality_container.addMetaDataEntry("quality_type", "not_supported")
        empty_quality_container.addMetaDataEntry("type", "quality")
        empty_quality_container.addMetaDataEntry("supported", False)
        self.addContainer(empty_quality_container)
        self.empty_quality_container = empty_quality_container

        empty_quality_changes_container = copy.deepcopy(self.empty_container)
        empty_quality_changes_container.setMetaDataEntry("id", "empty_quality_changes")
        empty_quality_changes_container.addMetaDataEntry("type", "quality_changes")
        empty_quality_changes_container.addMetaDataEntry("quality_type", "not_supported")
        self.addContainer(empty_quality_changes_container)
        self.empty_quality_changes_container = empty_quality_changes_container

    @override(ContainerRegistry)
    def addContainer(self, container):
        # Note: Intentional check with type() because we want to ignore subclasses
        if type(container) == ContainerStack:
            container = self._convertContainerStack(container)

        if isinstance(container, InstanceContainer) and isinstance(container, type(self.getEmptyInstanceContainer())):
            # Check against setting version of the definition.
            required_setting_version = self._application.SettingVersion
            actual_setting_version = int(container.getMetaDataEntry("setting_version", default = 0))
            if required_setting_version != actual_setting_version:
                Logger.log("w", "Instance container {container_id} is outdated. Its setting version is {actual_setting_version} but it should be {required_setting_version}.".format(container_id = container.getId(), actual_setting_version = actual_setting_version, required_setting_version = required_setting_version))
                return

        super().addContainer(container)

    def createUniqueName(self, container_type, current_name, new_name, fallback_name):
        new_name = new_name.strip()
        num_check = re.compile("(.*?)\s*#\d+$").match(new_name)
        if num_check:
            new_name = num_check.group(1)
        if new_name == "":
            new_name = fallback_name

        unique_name = new_name
        i = 1
        # In case we are renaming, the current name of the container is also a valid end-result
        while self._containerExists(container_type, unique_name) and unique_name != current_name:
            i += 1
            unique_name = "%s #%d" % (new_name, i)

        return unique_name

    def _containerExists(self, container_type: str, container_name: str):
        container_class = ContainerStack if container_type in ("machine", "extruder_train") else InstanceContainer

        results = self.findContainersMetadata(container_type = container_class, type = container_type)
        exists = False
        for result in results:
            names = {result["id"].lower(),
                     result["name"].lower(),
                     }
            if container_name.lower() in names:
                exists = True
                break
        return exists

    def _convertContainerStack(self, container):
        assert type(container) == ContainerStack

        container_type = container.getMetaDataEntry("type")
        if container_type not in ("extruder_train", "machine"):
            # It is not an extruder or machine, so do nothing with the stack
            return container

        Logger.log("d", "Converting ContainerStack {stack} to {type}", stack = container.getId(), type = container_type)

        if container_type == "extruder_train":
            new_stack = ExtruderStack.ExtruderStack(container.getId())
        else:
            new_stack = GlobalStack.GlobalStack(container.getId())

        container_contents = container.serialize()
        new_stack.deserialize(container_contents)

        # Delete the old configuration file so we do not get double stacks
        if os.path.isfile(container.getPath()):
            os.remove(container.getPath())

        return new_stack
