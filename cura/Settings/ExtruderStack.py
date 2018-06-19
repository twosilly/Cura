# Copyright (c) 2017 Ultimaker B.V.
# Cura is released under the terms of the LGPLv3 or higher.

from typing import Any, TYPE_CHECKING, Optional

from UM.Application import Application
from UM.Decorators import override
from UM.MimeTypeDatabase import MimeType, MimeTypeDatabase
from UM.Settings.ContainerStack import ContainerStack
from UM.Settings.ContainerRegistry import ContainerRegistry
from UM.Settings.Interfaces import ContainerInterface, PropertyEvaluationContext
from UM.Util import parseBool

from . import Exceptions
from .CuraContainerIndexes import CuraContainerIndexes
from .CuraContainerStack import CuraContainerStack

if TYPE_CHECKING:
    from cura.Settings.GlobalStack import GlobalStack


##  Represents an Extruder and its related containers.
#
#
class ExtruderStack(CuraContainerStack):
    def __init__(self, container_id: str):
        super().__init__(container_id)

        self.addMetaDataEntry("type", "extruder_train") # For backward compatibility

    @override(ContainerStack)
    def setNextStack(self, stack: "GlobalStack") -> None:
        super().setNextStack(stack)
        stack.addExtruder(self)
        self.addMetaDataEntry("machine", stack.getId())

    @override(ContainerStack)
    def getNextStack(self) -> Optional["GlobalStack"]:
        return super().getNextStack()

    def setEnabled(self, enabled):
        if "enabled" not in self._metadata:
            self.addMetaDataEntry("enabled", "True")
        self.setMetaDataEntry("enabled", str(enabled))

    def isEnabled(self):
        return parseBool(self.getMetaDataEntry("enabled", "True"))

    @classmethod
    def getLoadingPriority(cls) -> int:
        return 3

    ##  Return the filament diameter that the machine requires.
    #
    #   If the machine has no requirement for the diameter, -1 is returned.
    #   \return The filament diameter for the printer
    @property
    def materialDiameter(self) -> float:
        context = PropertyEvaluationContext(self)
        context.context["evaluate_from_container_index"] = CuraContainerIndexes.Variant

        return self.getProperty("material_diameter", "value", context = context)

    @property
    def approximateMaterialDiameter(self) -> float:
        return round(float(self.materialDiameter))

    ##  Overridden from ContainerStack
    #
    #   It will perform a few extra checks when trying to get properties.
    #
    #   The two extra checks it currently does is to ensure a next stack is set and to bypass
    #   the extruder when the property is not settable per extruder.
    #
    #   \throws Exceptions.NoGlobalStackError Raised when trying to get a property from an extruder without
    #                                         having a next stack set.
    @override(ContainerStack)
    def getProperty(self, key: str, property_name: str, context: Optional[PropertyEvaluationContext] = None) -> Any:
        if not self._next_stack:
            raise Exceptions.NoGlobalStackError("Extruder {id} is missing the next stack!".format(id = self.id))

        if context is None:
            context = PropertyEvaluationContext()
        context.pushContainer(self)

        if not super().getProperty(key, "settable_per_extruder", context):
            result = self.getNextStack().getProperty(key, property_name, context)
            context.popContainer()
            return result

        limit_to_extruder = super().getProperty(key, "limit_to_extruder", context)
        if limit_to_extruder is not None:
            if limit_to_extruder == -1:
                limit_to_extruder = int(Application.getInstance().getMachineManager().defaultExtruderPosition)
            limit_to_extruder = str(limit_to_extruder)
        if (limit_to_extruder is not None and limit_to_extruder != "-1") and self.getMetaDataEntry("position") != str(limit_to_extruder):
            if str(limit_to_extruder) in self.getNextStack().extruders:
                result = self.getNextStack().extruders[str(limit_to_extruder)].getProperty(key, property_name, context)
                if result is not None:
                    context.popContainer()
                    return result

        result = super().getProperty(key, property_name, context)
        context.popContainer()
        return result

    @override(CuraContainerStack)
    def _getMachineDefinition(self) -> ContainerInterface:
        if not self.getNextStack():
            raise Exceptions.NoGlobalStackError("Extruder {id} is missing the next stack!".format(id = self.id))

        return self.getNextStack()._getMachineDefinition()

    @override(CuraContainerStack)
    def deserialize(self, contents: str, file_name: Optional[str] = None) -> None:
        super().deserialize(contents, file_name)
        if "enabled" not in self.getMetaData():
            self.addMetaDataEntry("enabled", "True")
        stacks = ContainerRegistry.getInstance().findContainerStacks(id = self.getMetaDataEntry("machine", ""))
        if stacks:
            self.setNextStack(stacks[0])


extruder_stack_mime = MimeType(
    name = "application/x-cura-extruderstack",
    comment = "Cura Extruder Stack",
    suffixes = ["extruder.cfg"]
)

MimeTypeDatabase.addMimeType(extruder_stack_mime)
ContainerRegistry.addContainerTypeByName(ExtruderStack, "extruder_stack", extruder_stack_mime.name)
