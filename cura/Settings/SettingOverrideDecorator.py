# Copyright (c) 2016 Ultimaker B.V.
# Cura is released under the terms of the LGPLv3 or higher.

import copy
import uuid

from UM.Application import Application
from UM.Logging.Logger import Logger
from UM.Scene.SceneNodeDecorator import SceneNodeDecorator
from UM.Settings.InstanceContainer import InstanceContainer
from UM.Settings.ContainerRegistry import ContainerRegistry

from cura.Settings.PerObjectContainerStack import PerObjectContainerStack


##  A decorator that adds a container stack to a Node. This stack should be queried for all settings regarding
#   the linked node. The Stack in question will refer to the global stack (so that settings that are not defined by
#   this stack still resolve.
class SettingOverrideDecorator(SceneNodeDecorator):

    ##  Non-printing meshes
    #
    #   If these settings are True for any mesh, the mesh does not need a convex hull,
    #   and is sent to the slicer regardless of whether it fits inside the build volume.
    #   Note that Support Mesh is not in here because it actually generates
    #   g-code in the volume of the mesh.
    _non_printing_mesh_settings = {"anti_overhang_mesh", "infill_mesh", "cutting_mesh"}
    _non_thumbnail_visible_settings = {"anti_overhang_mesh", "infill_mesh", "cutting_mesh", "support_mesh"}

    def __init__(self):
        super().__init__()
        self._application = Application.getInstance()
        self._machine_manager = self._application.getMachineManager()

        self._stack = PerObjectContainerStack(container_id = "per_object_stack_" + str(id(self)))
        self._stack.setDirty(False)  # This stack does not need to be saved.
        user_container = InstanceContainer(container_id = self._generateUniqueName())
        user_container.addMetaDataEntry("type", "user")
        self._stack.userChanges = user_container
        self._extruder_stack = self._machine_manager.getActiveMachine().global_stack.extruders["0"].getId()

        self._is_non_printing_mesh = False
        self._is_non_thumbnail_visible_mesh = False

        self._application.getContainerRegistry().addContainer(self._stack)

        self._updateNextStack()

    def _generateUniqueName(self):
        return "SettingOverrideInstanceContainer-%s" % uuid.uuid1()

    def __deepcopy__(self, memo):
        ## Create a fresh decorator object
        deep_copy = SettingOverrideDecorator()

        ## Copy the instance
        instance_container = copy.deepcopy(self._stack.getContainer(0), memo)

        # A unique name must be added, or replaceContainer will not replace it
        instance_container.setMetaDataEntry("id", self._generateUniqueName())

        ## Set the copied instance as the first (and only) instance container of the stack.
        deep_copy._stack.replaceContainer(0, instance_container)

        # Properly set the right extruder on the copy
        deep_copy.setActiveExtruder(self._extruder_stack)

        # use value from the stack because there can be a delay in signal triggering and "_is_non_printing_mesh"
        # has not been updated yet.
        deep_copy._is_non_printing_mesh = self.evaluateIsNonPrintingMesh()
        deep_copy._is_non_thumbnail_visible_mesh = self.evaluateIsNonThumbnailVisibleMesh()

        return deep_copy

    ##  Gets the currently active extruder to print this object with.
    #
    #   \return An extruder's container stack.
    def getActiveExtruder(self):
        return self._extruder_stack

    ##  Gets the currently active extruders position
    #
    #   \return An extruder's position, or None if no position info is available.
    def getActiveExtruderPosition(self):
        containers = ContainerRegistry.getInstance().findContainers(id = self.getActiveExtruder())
        if containers:
            container_stack = containers[0]
            return container_stack.getMetaDataEntry("position", default=None)

    def isNonPrintingMesh(self):
        return self._is_non_printing_mesh

    def evaluateIsNonPrintingMesh(self):
        return any(bool(self._stack.getProperty(setting, "value")) for setting in self._non_printing_mesh_settings)

    def isNonThumbnailVisibleMesh(self):
        return self._is_non_thumbnail_visible_mesh

    def evaluateIsNonThumbnailVisibleMesh(self):
        return any(bool(self._stack.getProperty(setting, "value")) for setting in self._non_thumbnail_visible_settings)

    def _onSettingChanged(self, instance, property_name): # Reminder: 'property' is a built-in function
        if property_name == "value":
            # Trigger slice/need slicing if the value has changed.
            self._is_non_printing_mesh = self.evaluateIsNonPrintingMesh()
            self._is_non_thumbnail_visible_mesh = self.evaluateIsNonThumbnailVisibleMesh()

            self._application.getBackend().needsSlicing()
            self._application.getBackend().tickle()

    ##  Makes sure that the stack upon which the container stack is placed is
    #   kept up to date.
    def _updateNextStack(self):
        if self._extruder_stack:
            extruder_stack = ContainerRegistry.getInstance().findContainerStacks(id = self._extruder_stack)
            if extruder_stack:
                self._stack.setNextStack(extruder_stack[0])
            else:
                Logger.log("e", "Extruder stack %s below per-object settings does not exist.", self._extruder_stack)
        else:
            self._stack.setNextStack(self._machine_manager.getActiveMachine())

    ##  Changes the extruder with which to print this node.
    #
    #   \param extruder_stack_id The new extruder stack to print with.
    def setActiveExtruder(self, extruder_stack_id):
        self._extruder_stack = extruder_stack_id
        self._updateNextStack()

    def getStack(self):
        return self._stack
