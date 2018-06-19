# Copyright (c) 2015 Ultimaker B.V.
# Cura is released under the terms of the LGPLv3 or higher.

from UM.OS import OS
from UM.Logging.Logger import Logger
from UM.i18n import i18nCatalog
catalog = i18nCatalog("cura")

def getMetaData():
    return {
    }

def register(app):
    if OS.isWindows():
        from . import WindowsRemovableDrivePlugin
        return { "output_device": WindowsRemovableDrivePlugin.WindowsRemovableDrivePlugin() }
    elif OS.isOSX():
        from . import OSXRemovableDrivePlugin
        return { "output_device": OSXRemovableDrivePlugin.OSXRemovableDrivePlugin() }
    elif OS.isLinux():
        from . import LinuxRemovableDrivePlugin
        return { "output_device": LinuxRemovableDrivePlugin.LinuxRemovableDrivePlugin() }
    else:
        Logger.log("e", "Unsupported system, thus no removable device hotplugging support available.")
        return { }
