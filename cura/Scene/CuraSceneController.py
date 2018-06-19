from UM.Logging.Logger import Logger

from UM.Application import Application
from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator
from UM.Scene.Selection import Selection


class CuraSceneController:

    def __init__(self, application):
        super().__init__()
        self._application = application

        self._active_build_plate = -1

        self._last_selected_index = 0
        self._max_build_plate = 1  # default

    def _calcMaxBuildPlate(self):
        max_build_plate = 0
        for node in DepthFirstIterator(Application.getInstance().getController().getScene().getRoot()):
            if node.callDecoration("isSliceable"):
                build_plate_number = node.callDecoration("getBuildPlateNumber")
                if build_plate_number is None:
                    build_plate_number = 0
                max_build_plate = max(build_plate_number, max_build_plate)
        return max_build_plate

    def setActiveBuildPlate(self, nr):
        if nr == self._active_build_plate:
            return
        Logger.log("d", "Select build plate: %s" % nr)
        self._active_build_plate = nr
        Selection.clear()
