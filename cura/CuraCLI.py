# Copyright (c) 2018 Ultimaker B.V.
# Cura is released under the terms of the LGPLv3 or higher.

import os
import sys
import tempfile
import time

import numpy

from UM.Application import Application
from UM.Logging.Logger import Logger
from UM.MimeTypeDatabase import MimeType, MimeTypeDatabase
from UM.Resources import Resources
from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator
from UM.Scene.SceneNode import SceneNode
from UM.Settings.SettingDefinition import SettingDefinition, DefinitionPropertyType
from UM.Settings.SettingFunction import SettingFunction
from UM.Settings.Validator import Validator

from cura.Arranging.Arrange import Arrange
from cura.Arranging import ArrangeObjectsJob
from cura.Arranging import ArrangeObjectsAllBuildPlatesJob
from cura.BuildVolume import BuildVolume
from cura.Machines.VariantManager import VariantManager
from cura.Machines.MachineManager import MachineManager
from cura.Machines.MaterialManager import MaterialManager
from cura.Machines.QualityManager import QualityManager
from cura.Settings.CuraContainerRegistry import CuraContainerRegistry
from cura.Settings.CuraStackBuilder import CuraStackBuilder
from cura.Settings.ExtruderManager import ExtruderManager
from cura.Settings.Material.XmlMaterialProfile import XmlMaterialProfile
from cura.Scene.CuraSceneController import CuraSceneController

from cura.Cli.SliceTask import SliceTask

numpy.seterr(all = "ignore")


MYPY = False
if not MYPY:
    try:
        from cura.CuraVersion import CuraVersion, CuraBuildType, CuraDebugMode
    except ImportError:
        CuraVersion = "master"  # [CodeStyle: Reflecting imported value]
        CuraBuildType = ""
        CuraDebugMode = False


class CuraCLI(Application):
    # SettingVersion represents the set of settings available in the machine/extruder definitions.
    # You need to make sure that this version number needs to be increased if there is any non-backwards-compatible
    # changes of the settings.
    SettingVersion = 5

    class ResourceTypes:
        QmlFiles = Resources.UserType + 1
        Firmware = Resources.UserType + 2
        QualityInstanceContainer = Resources.UserType + 3
        QualityChangesInstanceContainer = Resources.UserType + 4
        MaterialInstanceContainer = Resources.UserType + 5
        VariantInstanceContainer = Resources.UserType + 6
        UserInstanceContainer = Resources.UserType + 7
        MachineStack = Resources.UserType + 8
        ExtruderStack = Resources.UserType + 9
        DefinitionChangesContainer = Resources.UserType + 10
        SettingVisibilityPreset = Resources.UserType + 11

    def __init__(self, *args, **kwargs):
        super().__init__(name = "cura",
                         version = CuraVersion,
                         buildtype = CuraBuildType,
                         is_debug_mode = CuraDebugMode,
                         **kwargs)
        self._boot_loading_time = time.time()

        self._container_registry_class = CuraContainerRegistry

        # Use a temporary directory for CLI application so it will not interfere the normal GUI application and other
        # running CLI processes.
        self._app_home_dir = tempfile.mkdtemp(prefix = "cura-cli-", suffix = "-" + str(time.time()))

        self._variant_manager = None
        self._material_manager = None
        self._quality_manager = None
        self._cura_stack_builder = None
        self._machine_manager = None
        self._extruder_manager = None
        self._volume = None

        self._cura_scene_controller = None
        self._platform_activity = False

        self._i18n_catalog = None

        self._slice_task = None  # type: SliceTask

    # Adds command line options to the command line parser. This should be called after the application is created and
    # before the pre-start.
    def addCommandLineOptions(self):
        super().addCommandLineOptions()
        self._cli_parser.add_argument("--help", "-h",
                                      action = "store_true",
                                      default = False,
                                      help = "Show this help message and exit.")
        self._cli_parser.add_argument("--machine-yaml", "-j",
                                      action = "store",
                                      default = "",
                                      help = "The JSON file with the machine configuration to use.")
        self._cli_parser.add_argument("--model-file", "-f",
                                      action = "append",
                                      dest = "model_file_list",
                                      nargs = "+",
                                      help = "A list of model files in the format of '<f1>,<f2>,...'.")
        self._cli_parser.add_argument("--output-file", "-o",
                                      action = "store",
                                      dest = "output_file",
                                      help = "The file to output.")

    def parseCliOptions(self):
        super().parseCliOptions()

        if self._cli_args.help:
            self._cli_parser.print_help()
            sys.exit(0)

        machine_yaml = self._cli_args.machine_yaml
        if not machine_yaml:
            print("machine YAML file is not specified, please check the help information.")
            self._cli_parser.print_help()
            sys.exit(1)

        model_file_list = self._cli_args.model_file_list
        if not model_file_list:
            print("No model file is given, please check the help information.")
            self._cli_parser.print_help()
            sys.exit(1)
        all_model_file_list = list()
        for file_list in model_file_list:
            all_model_file_list += file_list
        model_file_list = all_model_file_list

        output_file = self._cli_args.output_file
        if not output_file:
            print("Output file is not given, please check the help information.")
            self._cli_parser.print_help()
            sys.exit(1)

        self._slice_task = SliceTask(self, machine_yaml, model_file_list, output_file)
        try:
            self._slice_task.validate()
        except Exception as e:
            print(e)
            self._cli_parser.print_help()
            sys.exit(2)

        # Initialize the slice task
        self._slice_task.initialize()

    def initialize(self) -> None:
        self.__addExpectedResourceDirsAndSearchPaths()  # Must be added before init of super

        super().initialize()

        from cura.Backends.CuraEngine.CuraEngineBackend import CuraEngineBackend
        self._backend = CuraEngineBackend(self)

        from cura.Mesh import MeshHandling
        self._mesh_manager.add_mesh_read_finished_callback(MeshHandling.process_read_mesh)

        from cura.files.writers.GCodeWriter import GCodeWriter
        self._file_manager.addWriter(GCodeWriter(self))

        mime_type = MimeType(
            name = "text/x-gcode",
            comment = "G-code File",
            suffixes = ["gcode"],
        )
        MimeTypeDatabase.addMimeType(mime_type)

        self.__initializeSettingDefinitionsAndFunctions()
        self.__addAllResourcesAndContainerResources()
        self.__setLatestResouceVersionsForVersionUpgrade()

    # Adds expected directory names and search paths for Resources.
    def __addExpectedResourceDirsAndSearchPaths(self):
        # this list of dir names will be used by UM to detect an old cura directory
        for dir_name in ["extruders", "machine_instances", "materials", "plugins", "quality", "quality_changes", "user", "variants"]:
            Resources.addExpectedDirNameInData(dir_name)

        Resources.addSearchPath(os.path.join(self._app_install_dir, "share", "cura", "resources"))
        if not hasattr(sys, "frozen"):
            resource_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), "..", "resources")
            Resources.addSearchPath(resource_path)

    # Adds custom property types, settings types, and extra operators (functions) that need to be registered in
    # SettingDefinition and SettingFunction.
    def __initializeSettingDefinitionsAndFunctions(self):
        # Need to do this before ContainerRegistry tries to load the machines
        SettingDefinition.addSupportedProperty("settable_per_mesh", DefinitionPropertyType.Any, default = True, read_only = True)
        SettingDefinition.addSupportedProperty("settable_per_extruder", DefinitionPropertyType.Any, default = True, read_only = True)
        # this setting can be changed for each group in one-at-a-time mode
        SettingDefinition.addSupportedProperty("settable_per_meshgroup", DefinitionPropertyType.Any, default = True, read_only = True)
        SettingDefinition.addSupportedProperty("settable_globally", DefinitionPropertyType.Any, default = True, read_only = True)

        # From which stack the setting would inherit if not defined per object (handled in the engine)
        # AND for settings which are not settable_per_mesh:
        # which extruder is the only extruder this setting is obtained from
        SettingDefinition.addSupportedProperty("limit_to_extruder", DefinitionPropertyType.Function, default = "-1", depends_on = "value")

        # For settings which are not settable_per_mesh and not settable_per_extruder:
        # A function which determines the glabel/meshgroup value by looking at the values of the setting in all (used) extruders
        SettingDefinition.addSupportedProperty("resolve", DefinitionPropertyType.Function, default = None, depends_on = "value")

        SettingDefinition.addSettingType("extruder", None, str, Validator)
        SettingDefinition.addSettingType("optional_extruder", None, str, None)
        SettingDefinition.addSettingType("[int]", None, str, None)

        SettingFunction.registerOperator("extruderValues", ExtruderManager.getExtruderValues)
        SettingFunction.registerOperator("extruderValue", ExtruderManager.getExtruderValue)
        SettingFunction.registerOperator("resolveOrValue", ExtruderManager.getResolveOrValue)
        SettingFunction.registerOperator("defaultExtruderPosition", ExtruderManager.getDefaultExtruderPosition)

    # Adds all resources and container related resources.
    def __addAllResourcesAndContainerResources(self) -> None:
        Resources.addStorageType(self.ResourceTypes.QualityInstanceContainer, "quality")
        Resources.addStorageType(self.ResourceTypes.QualityChangesInstanceContainer, "quality_changes")
        Resources.addStorageType(self.ResourceTypes.VariantInstanceContainer, "variants")
        Resources.addStorageType(self.ResourceTypes.MaterialInstanceContainer, "materials")
        Resources.addStorageType(self.ResourceTypes.UserInstanceContainer, "user")
        Resources.addStorageType(self.ResourceTypes.ExtruderStack, "extruders")
        Resources.addStorageType(self.ResourceTypes.MachineStack, "machine_instances")
        Resources.addStorageType(self.ResourceTypes.DefinitionChangesContainer, "definition_changes")
        Resources.addStorageType(self.ResourceTypes.SettingVisibilityPreset, "setting_visibility")

        self._container_registry.addResourceType(self.ResourceTypes.QualityInstanceContainer, "quality")
        self._container_registry.addResourceType(self.ResourceTypes.QualityChangesInstanceContainer, "quality_changes")
        self._container_registry.addResourceType(self.ResourceTypes.VariantInstanceContainer, "variant")
        self._container_registry.addResourceType(self.ResourceTypes.MaterialInstanceContainer, "material")
        self._container_registry.addResourceType(self.ResourceTypes.UserInstanceContainer, "user")
        self._container_registry.addResourceType(self.ResourceTypes.ExtruderStack, "extruder_train")
        self._container_registry.addResourceType(self.ResourceTypes.MachineStack, "machine")
        self._container_registry.addResourceType(self.ResourceTypes.DefinitionChangesContainer, "definition_changes")

        Resources.addType(self.ResourceTypes.QmlFiles, "qml")
        Resources.addType(self.ResourceTypes.Firmware, "firmware")

    # Initializes the version upgrade manager with by providing the paths for each resource type and the latest
    # versions.
    def __setLatestResouceVersionsForVersionUpgrade(self):
        """
        self._version_upgrade_manager.setCurrentVersions(
            {
                ("quality", InstanceContainer.Version * 1000000 + self.SettingVersion):            (self.ResourceTypes.QualityInstanceContainer, "application/x-uranium-instancecontainer"),
                ("quality_changes", InstanceContainer.Version * 1000000 + self.SettingVersion):    (self.ResourceTypes.QualityChangesInstanceContainer, "application/x-uranium-instancecontainer"),
                ("machine_stack", ContainerStack.Version * 1000000 + self.SettingVersion):         (self.ResourceTypes.MachineStack, "application/x-cura-globalstack"),
                ("extruder_train", ContainerStack.Version * 1000000 + self.SettingVersion):        (self.ResourceTypes.ExtruderStack, "application/x-cura-extruderstack"),
                ("preferences", Preferences.Version * 1000000 + self.SettingVersion):              (Resources.Preferences, "application/x-uranium-preferences"),
                ("user", InstanceContainer.Version * 1000000 + self.SettingVersion):               (self.ResourceTypes.UserInstanceContainer, "application/x-uranium-instancecontainer"),
                ("definition_changes", InstanceContainer.Version * 1000000 + self.SettingVersion): (self.ResourceTypes.DefinitionChangesContainer, "application/x-uranium-instancecontainer"),
                ("variant", InstanceContainer.Version * 1000000 + self.SettingVersion):            (self.ResourceTypes.VariantInstanceContainer, "application/x-uranium-instancecontainer"),
            }
        )
        """

        mime_type = MimeType(
            name="application/x-ultimaker-material-profile",
            comment="Ultimaker Material Profile",
            suffixes=["xml.fdm_material"]
        )
        MimeTypeDatabase.addMimeType(mime_type)
        self._container_registry_class.addContainerTypeByName(XmlMaterialProfile, "material", mime_type.name)

    # Runs preparations that needs to be done before the starting process.
    def startSplashWindowPhase(self):
        # set the setting version for Preferences
        preferences = self.getPreferences()
        preferences.addPreference("metadata/setting_version", 0)
        preferences.setValue("metadata/setting_version", self.SettingVersion) #Don't make it equal to the default so that the setting version always gets written to the file.

        preferences.addPreference("mesh/scale_to_fit", False)
        preferences.addPreference("mesh/scale_tiny_meshes", True)
        preferences.addPreference("cura/use_multi_build_plate", False)

        preferences.addPreference("cura/currency", "€")
        preferences.addPreference("cura/material_settings", "{}")

        preferences.addPreference("local_file/last_used_type", "text/x-gcode")

    # Cura has multiple locations where instance containers need to be saved, so we need to handle this differently.
    def saveSettings(self):
        self._container_registry.saveDirtyContainers()
        self.savePreferences()

    def saveStack(self, stack):
        self._container_registry.saveContainer(stack)

    def run(self):
        self._container_registry.loadAllMetadata()

        Logger.log("i", "Initializing variant manager")
        self._variant_manager = VariantManager(self)
        self._variant_manager.initialize()

        Logger.log("i", "Initializing material manager")
        self._material_manager = MaterialManager(self)
        self._material_manager.initialize()

        Logger.log("i", "Initializing quality manager")
        self._quality_manager = QualityManager(self)
        self._quality_manager.initialize()

        Logger.log("i", "Initializing quality manager")
        self._cura_stack_builder = CuraStackBuilder(self)

        Logger.log("i", "Initializing machine manager")
        self._machine_manager = MachineManager(self)

        Logger.log("i", "Initializing extruder manager")
        self._extruder_manager = ExtruderManager(self)

        Logger.log("i", "Initializing cura scene controller")
        self._cura_scene_controller = CuraSceneController(self)
        self._cura_scene_controller.setActiveBuildPlate(0)

        # Setup scene and build volume
        root = self.getController().getScene().getRoot()
        self._volume = BuildVolume(self, root)
        Arrange.build_volume = self._volume

        Logger.log("d", "Booting Cura took %s seconds", time.time() - self._boot_loading_time)

        self._processCuraScript("")

    def _processCuraScript(self, script_file: str) -> None:
        # TODO: Main process
        self._slice_task.start()
        sys.exit(0)

    def getMachineManager(self) -> "MachineManager":
        return self._machine_manager

    def getExtruderManager(self) -> "ExtruderManager":
        return self._extruder_manager

    def getCuraStackBuilder(self) -> "CuraStackBuilder":
        return self._cura_stack_builder

    def getVariantManager(self):
        return self._variant_manager

    def getMaterialManager(self):
        return self._material_manager

    def getQualityManager(self):
        return self._quality_manager

    def platformActivity(self) -> bool:
        return self._platform_activity

    ##  Arrange all objects.
    def arrangeObjectsToAllBuildPlates(self):
        nodes = []
        for node in DepthFirstIterator(self.getController().getScene().getRoot()):
            if not isinstance(node, SceneNode):
                continue
            if not node.getMeshData() and not node.callDecoration("isGroup"):
                continue  # Node that doesnt have a mesh and is not a group.
            if node.getParent() and node.getParent().callDecoration("isGroup"):
                continue  # Grouped nodes don't need resetting as their parent (the group) is resetted)
            if not node.callDecoration("isSliceable") and not node.callDecoration("isGroup"):
                continue  # i.e. node with layer data
            # Skip nodes that are too big
            if node.getBoundingBox().width < self._volume.getBoundingBox().width or node.getBoundingBox().depth < self._volume.getBoundingBox().depth:
                nodes.append(node)
        ArrangeObjectsAllBuildPlatesJob.arrange_objects_all_build_plates(nodes)
        self._cura_scene_controller.setActiveBuildPlate(0)  # Select first build plate

    ##  Arrange a set of nodes given a set of fixed nodes
    #   \param nodes nodes that we have to place
    #   \param fixed_nodes nodes that are placed in the arranger before finding spots for nodes
    def arrange(self, nodes, fixed_nodes):
        min_offset = self.getBuildVolume().getEdgeDisallowedSize() + 2  # Allow for some rounding errors
        ArrangeObjectsJob.arrange_objects(nodes, fixed_nodes, min_offset = max(min_offset, 8))

    def getBuildVolume(self):
        return self._volume
