# Copyright (c) 2017 Ultimaker B.V.
# Cura is released under the terms of the LGPLv3 or higher.

from UM.Application import Application  # To get the global container stack to find the current machine.
from UM.Settings.SettingFunction import SettingFunction
from UM.Settings.PropertyEvaluationContext import PropertyEvaluationContext


class ExtruderManager:

    ##  Registers listeners and such to listen to changes to the extruders.
    def __init__(self, application):
        if ExtruderManager.__instance is not None:
            raise RuntimeError("Try to create singleton '%s' more than once" % self.__class__.__name__)
        ExtruderManager.__instance = self

        super().__init__()

        self._application = application

    ##  Get all extruder values for a certain setting.
    #
    #   This is exposed to SettingFunction so it can be used in value functions.
    #
    #   \param key The key of the setting to retrieve values for.
    #
    #   \return A list of values for all extruders. If an extruder does not have a value, it will not be in the list.
    #           If no extruder has the value, the list will contain the global value.
    @staticmethod
    def getExtruderValues(key):
        global_stack = Application.getInstance().getMachineManager().getActiveMachine().global_stack

        result = []
        for extruder in global_stack.extruders.values():
            if not extruder.isEnabled:
                continue
            # only include values from extruders that are "active" for the current machine instance
            if int(extruder.getMetaDataEntry("position")) >= global_stack.getProperty("machine_extruder_count", "value"):
                continue

            value = extruder.getRawProperty(key, "value")

            if value is None:
                continue

            if isinstance(value, SettingFunction):
                value = value(extruder)

            result.append(value)

        if not result:
            result.append(global_stack.getProperty(key, "value"))

        return result

    ##  Get all extruder values for a certain setting. This function will skip the user settings container.
    #
    #   This is exposed to SettingFunction so it can be used in value functions.
    #
    #   \param key The key of the setting to retrieve values for.
    #
    #   \return A list of values for all extruders. If an extruder does not have a value, it will not be in the list.
    #           If no extruder has the value, the list will contain the global value.
    @staticmethod
    def getDefaultExtruderValues(key):
        global_stack = Application.getInstance().getMachineManager().getActiveMachine().global_stack
        context = PropertyEvaluationContext(global_stack)
        context.context["evaluate_from_container_index"] = 1  # skip the user settings container
        context.context["override_operators"] = {
            "extruderValue": ExtruderManager.getDefaultExtruderValue,
            "extruderValues": ExtruderManager.getDefaultExtruderValues,
            "resolveOrValue": ExtruderManager.getDefaultResolveOrValue
        }

        result = []
        for extruder in global_stack.extruders.values():
            # only include values from extruders that are "active" for the current machine instance
            if int(extruder.getMetaDataEntry("position")) >= global_stack.getProperty("machine_extruder_count", "value", context = context):
                continue

            value = extruder.getRawProperty(key, "value", context = context)

            if value is None:
                continue

            if isinstance(value, SettingFunction):
                value = value(extruder, context = context)

            result.append(value)

        if not result:
            result.append(global_stack.getProperty(key, "value", context = context))

        return result

    ##  Return the default extruder position from the machine manager
    @staticmethod
    def getDefaultExtruderPosition() -> str:
        return "0"

    ##  Get the value for a setting from a specific extruder.
    #
    #   This is exposed to SettingFunction to use in value functions.
    #
    #   \param extruder_index The index of the extruder to get the value from.
    #   \param key The key of the setting to get the value of.
    #
    #   \return The value of the setting for the specified extruder or for the
    #   global stack if not found.
    @staticmethod
    def getExtruderValue(extruder_index, key):
        global_stack = Application.getInstance().getMachineManager().getActiveMachine().global_stack
        if extruder_index == -1:
            extruder_index = int(0)
        extruder = global_stack.extruders[str(extruder_index)]

        if extruder:
            value = extruder.getRawProperty(key, "value")
            if isinstance(value, SettingFunction):
                value = value(extruder)
        else:
            # Just a value from global.
            value = global_stack.getProperty(key, "value")

        return value

    ##  Get the default value from the given extruder. This function will skip the user settings container.
    #
    #   This is exposed to SettingFunction to use in value functions.
    #
    #   \param extruder_index The index of the extruder to get the value from.
    #   \param key The key of the setting to get the value of.
    #
    #   \return The value of the setting for the specified extruder or for the
    #   global stack if not found.
    @staticmethod
    def getDefaultExtruderValue(extruder_index, key):
        global_stack = Application.getInstance().getMachineManager().getActiveMachine().global_stack
        extruder = global_stack.extruders[str(extruder_index)]
        context = PropertyEvaluationContext(extruder)
        context.context["evaluate_from_container_index"] = 1  # skip the user settings container
        context.context["override_operators"] = {
            "extruderValue": ExtruderManager.getDefaultExtruderValue,
            "extruderValues": ExtruderManager.getDefaultExtruderValues,
            "resolveOrValue": ExtruderManager.getDefaultResolveOrValue
        }

        if extruder:
            value = extruder.getRawProperty(key, "value", context = context)
            if isinstance(value, SettingFunction):
                value = value(extruder, context = context)
        else:  # Just a value from global.
            value = global_stack.getProperty(key, "value", context = context)

        return value

    ##  Get the resolve value or value for a given key
    #
    #   This is the effective value for a given key, it is used for values in the global stack.
    #   This is exposed to SettingFunction to use in value functions.
    #   \param key The key of the setting to get the value of.
    #
    #   \return The effective value
    @staticmethod
    def getResolveOrValue(key):
        global_stack = Application.getInstance().getMachineManager().getActiveMachine().global_stack
        resolved_value = global_stack.getProperty(key, "value")

        return resolved_value

    ##  Get the resolve value or value for a given key without looking the first container (user container)
    #
    #   This is the effective value for a given key, it is used for values in the global stack.
    #   This is exposed to SettingFunction to use in value functions.
    #   \param key The key of the setting to get the value of.
    #
    #   \return The effective value
    @staticmethod
    def getDefaultResolveOrValue(key):
        global_stack = Application.getInstance().getGlobalContainerStack().global_stack
        context = PropertyEvaluationContext(global_stack)
        context.context["evaluate_from_container_index"] = 1  # skip the user settings container
        context.context["override_operators"] = {
            "extruderValue": ExtruderManager.getDefaultExtruderValue,
            "extruderValues": ExtruderManager.getDefaultExtruderValues,
            "resolveOrValue": ExtruderManager.getDefaultResolveOrValue
        }

        resolved_value = global_stack.getProperty(key, "value", context = context)

        return resolved_value

    __instance = None

    @classmethod
    def getInstance(cls, *args, **kwargs) -> "ExtruderManager":
        return cls.__instance
