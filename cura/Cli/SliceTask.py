import os
from typing import Dict, List, TYPE_CHECKING

import yaml

from UM.Logging.Logger import Logger
from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator

if TYPE_CHECKING:
    from UM.Application import Application
    from cura.Machines.Machine import Machine
    from cura.Settings.CuraContainerStack import CuraContainerStack


class SliceTask:

    def __init__(self, application: "Application", machine_yaml_file: str, model_file_list: List[str],
                 output_file: str) -> None:
        self._application = application
        self.machine_yaml_file = machine_yaml_file  # type: str
        self.model_file_list = model_file_list  # type: List[str]
        self.output_file = output_file  # type: str

        self._machine_dict = {}  # type: dict

    def validate(self) -> None:
        # Check if the files provided exists
        if not os.path.isfile(self.machine_yaml_file):
            raise RuntimeError("The given machine YAML file '{file_name}' does not exist".format(
                file_name = self.machine_yaml_file))
        for model_file_name in self.model_file_list:
            if not os.path.isfile(model_file_name):
                raise RuntimeError("The given model file '{file_name}' does not exist".format(
                    file_name = model_file_name))

    def initialize(self) -> None:
        # Parse machine YAML file
        with open(self.machine_yaml_file, "r", encoding = "utf-8") as f:
            machine_dict = yaml.load(f)
        self._machine_dict = machine_dict

    def start(self) -> None:
        machine = self._create_and_configure_machine()

        # Load model files
        file_manager = self._application.getFileManager()
        for file_name in self.model_file_list:
            reader = file_manager.getReaderForFileName(file_name)
            reader.read(file_name)

        # DEBUG: Show all scene nodes
        self.__debug_show_all_scene_nodes()

        # Slice
        backend = self._application.getBackend()
        backend.initialize()
        backend.slice()

        # Save to gcode
        gcode_file = self.output_file
        Logger.log("i", "Saving to Gcode file %s", gcode_file)
        writer = file_manager.getWriterByMimeType("text/x-gcode")
        root_scene_node = self._application.getController().getScene().getRoot()
        with open(gcode_file, "w", encoding = "utf-8") as f:
            writer.write(f, [root_scene_node])

    def _create_and_configure_machine(self) -> "Machine":
        """
        Configures the given machine according to the settings specified in the slice task file.
        """
        # Create machine
        machine_manager = self._application.getMachineManager()

        machine_name = self._machine_dict["machine"]["name"]
        machine_type = self._machine_dict["machine"]["type"]

        # Create and get the machine
        machine_manager.createMachine(machine_name, machine_type)
        machine = machine_manager.getMachine(machine_name)
        machine_manager._active_machine = machine

        # -> Configure machine
        # Configure each extruder stack
        for position, data_dict in self._machine_dict["machine"].get("extruders", {}).items():
            position = str(position)
            extruder = machine.extruders[position]

            enabled = data_dict.get("enabled", True)
            extruder.extruder_stack.setEnabled(enabled)

            variant_name = data_dict.get("variant_name")
            if variant_name:
                extruder.setVariantByName(variant_name)

            material_root_id = data_dict.get("material_root_id")
            if material_root_id:
                extruder.setMaterialByRootId(material_root_id)

        # Configure the global stack
        quality_type = self._machine_dict["machine"].get("quality_type")
        if quality_type:
            machine.setQualityGroupByQualityType(quality_type)

        # Apply custom settings
        settings_dict = self._machine_dict["machine"].get("settings", {})
        self._apply_custom_settings(machine.global_stack, settings_dict)
        for position, data_dict in self._machine_dict["machine"].get("extruders", {}).items():
            position = str(position)
            settings_dict = data_dict.get("settings", {})
            self._apply_custom_settings(machine.extruders[position].extruder_stack, settings_dict)

        # DEBUG
        self.__debug_show_machine_info(machine)
        return machine

    def _apply_custom_settings(self, stack: "CuraContainerStack", setting_dict: Dict[str, str]) -> None:
        for key, value in setting_dict.items():
            stack.setProperty(key, "value", str(value), target_container = "user")

    def __debug_show_machine_info(self, machine: "Machine") -> None:
        """
        Prints out the given machine's configuration.
        """
        for i in range(7):
            Logger.log("d", "[%s]  -  [%s]  - %s", machine.global_stack.getId(), i, machine.global_stack.getContainer(i).getId())
        user_container = machine.global_stack.userChanges
        for key in user_container.getAllKeys():
            Logger.log("d", "[%s]  -  [%s]  - %s", machine.global_stack.getId(),
                       key, user_container.getProperty(key, "value"))
        for position, extruder in machine.extruders.items():
            for i in range(7):
                Logger.log("d", "[%s]  [%s] (enabled: %s) -  [%s]  - %s", position,
                           extruder.extruder_stack.getId(), extruder.extruder_stack.isEnabled(),
                           i, extruder.extruder_stack.getContainer(i).getId())
            user_container = extruder.extruder_stack.userChanges
            for key in user_container.getAllKeys():
                Logger.log("d", "[%s]  [%s] (enabled: %s) -  custom setting -  [%s]  - %s", position,
                           extruder.extruder_stack.getId(), extruder.extruder_stack.isEnabled(),
                           key, user_container.getProperty(key, "value"))

    def __debug_show_all_scene_nodes(self) -> None:
        """
        Prints out all scene nodes.
        """
        main_scene = self._application.getController().getScene()
        for node in DepthFirstIterator(main_scene.getRoot()):
            if not node.callDecoration("isSliceable"):
                continue
            print("------> slicable node: ", node)
