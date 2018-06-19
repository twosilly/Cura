# Copyright (c) 2018 Ultimaker B.V.
# Cura is released under the terms of the LGPLv3 or higher.

from UM.i18n import i18nCatalog
from UM.OS import OS

from . import GCodeGzReader

i18n_catalog = i18nCatalog("cura")

def getMetaData():
    file_extension = "gz" if OS.isOSX() else "gcode.gz"
    return {
        "mesh_reader": [
            {
                "extension": file_extension,
                "description": i18n_catalog.i18nc("@item:inlistbox", "Compressed G-code File")
            }
        ]
    }

def register(app):
    app.addNonSliceableExtension(".gz")
    return { "mesh_reader": GCodeGzReader.GCodeGzReader(app) }
