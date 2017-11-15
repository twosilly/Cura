from PyQt5.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt5.QtQml import qmlRegisterType

from UM.Application import Application
from UM.Settings.ContainerRegistry import ContainerRegistry

from .Machine import Machine


class NewMachineManager(QObject):

    def __init__(self, parent = None):
        super().__init__(parent)

        self._machine_dict = {}  # <id> -> <Machine>
        self._active_machine = None

        self._container_registry = ContainerRegistry.getInstance()

        qmlRegisterType(Machine, "Cura", 1, 0, "Machine")

    __instance = None

    activeMachineChanged = pyqtSignal()

    @classmethod
    def getInstance(cls):
        if cls.__instance is None:
            cls.__instance = NewMachineManager()
        return cls.__instance

    def initialize(self):
        machine_stack_list = self._container_registry.findContainerStacks(type = "machine")
        for machine_stack in machine_stack_list:
            machine = Machine(machine_stack.getId(), machine_stack.getName())
            self._machine_dict[machine_stack.getId()] = machine

            machine.initialize()

    def setActiveMachine(self, machine_name: str):
        machine = self._machine_dict.get(machine_name)
        if machine is None:
            # TODO: Use logging instead and do nothing
            raise RuntimeError("Could not find machine [%s]" % machine_name)

        # deactivate the currently active machine
        if self._active_machine:
            self._active_machine = None

        # active the specified machine
        Application.getInstance().setGlobalContainerStack(machine)
        self._active_machine = machine
        self.activeMachineChanged.emit()

    @pyqtProperty(Machine, fset = setActiveMachine, notify = activeMachineChanged)
    def activeMachine(self):
        return self._active_machine
