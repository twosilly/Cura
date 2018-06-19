# Copyright (c) 2018 Ultimaker B.V.
# Cura is released under the terms of the LGPLv3 or higher.
from enum import IntEnum  # For the connection state tracking.
from typing import List, Optional

from UM.i18n import i18nCatalog
from UM.OutputDevice.OutputDevice import OutputDevice


MYPY = False
if MYPY:
    from cura.PrinterOutput.PrinterOutputModel import PrinterOutputModel
    from cura.PrinterOutput.ConfigurationModel import ConfigurationModel

i18n_catalog = i18nCatalog("cura")

##  Printer output device adds extra interface options on top of output device.
#
#   The assumption is made the printer is a FDM printer.
#
#   Note that a number of settings are marked as "final". This is because decorators
#   are not inherited by children. To fix this we use the private counter part of those
#   functions to actually have the implementation.
#
#   For all other uses it should be used in the same way as a "regular" OutputDevice.
class PrinterOutputDevice(OutputDevice):

    def __init__(self, device_id, parent = None):
        super().__init__(device_id = device_id, parent = parent)

        self._printers = []  # type: List[PrinterOutputModel]
        self._unique_configurations = []   # type: List[ConfigurationModel]

        self._monitor_view_qml_path = ""
        self._monitor_component = None
        self._monitor_item = None

        self._control_view_qml_path = ""
        self._control_component = None
        self._control_item = None

        self._qml_context = None
        self._accepts_commands = False

        self._connection_state = ConnectionState.closed

        self._firmware_name = None
        self._address = ""
        self._connection_text = ""

    def address(self):
        return self._address

    def setConnectionText(self, connection_text):
        if self._connection_text != connection_text:
            self._connection_text = connection_text

    def connectionText(self):
        return self._connection_text

    def isConnected(self):
        return self._connection_state != ConnectionState.closed and self._connection_state != ConnectionState.error

    def setConnectionState(self, connection_state):
        if self._connection_state != connection_state:
            self._connection_state = connection_state

    def connectionState(self):
        return self._connection_state

    def _update(self):
        pass

    def _getPrinterByKey(self, key) -> Optional["PrinterOutputModel"]:
        for printer in self._printers:
            if printer.key == key:
                return printer

        return None

    def requestWrite(self, nodes, file_name = None, filter_by_machine = False, file_handler = None, **kwargs):
        raise NotImplementedError("requestWrite needs to be implemented")

    def activePrinter(self) -> Optional["PrinterOutputModel"]:
        if len(self._printers):
            return self._printers[0]
        return None

    def printers(self):
        return self._printers

    ##  Attempt to establish connection
    def connect(self):
        self.setConnectionState(ConnectionState.connecting)

    ##  Attempt to close the connection
    def close(self):
        self.setConnectionState(ConnectionState.closed)

    ##  Ensure that close gets called when object is destroyed
    def __del__(self):
        self.close()

    def acceptsCommands(self):
        return self._accepts_commands

    ##  Set a flag to signal the UI that the printer is not (yet) ready to receive commands
    def _setAcceptsCommands(self, accepts_commands):
        if self._accepts_commands != accepts_commands:
            self._accepts_commands = accepts_commands

    # Returns the unique configurations of the printers within this output device
    def uniqueConfigurations(self):
        return self._unique_configurations

    def _updateUniqueConfigurations(self):
        self._unique_configurations = list(set([printer.printerConfiguration for printer in self._printers if printer.printerConfiguration is not None]))
        self._unique_configurations.sort(key = lambda k: k.printerType)

    def _onPrintersChanged(self):
        # At this point there may be non-updated configurations
        self._updateUniqueConfigurations()

    ##  Set the device firmware name
    #
    #   \param name \type{str} The name of the firmware.
    def _setFirmwareName(self, name):
        self._firmware_name = name

    ##  Get the name of device firmware
    #
    #   This name can be used to define device type
    def getFirmwareName(self):
        return self._firmware_name


##  The current processing state of the backend.
class ConnectionState(IntEnum):
    closed = 0
    connecting = 1
    connected = 2
    busy = 3
    error = 4
