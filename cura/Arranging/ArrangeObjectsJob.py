# Copyright (c) 2017 Ultimaker B.V.
# Cura is released under the terms of the LGPLv3 or higher.

from typing import List, TYPE_CHECKING

from UM.Application import Application
from UM.Math.Vector import Vector
from UM.Operations.TranslateOperation import TranslateOperation
from UM.Operations.GroupedOperation import GroupedOperation
from UM.Logging.Logger import Logger
from UM.i18n import i18nCatalog

from cura.Arranging.Arrange import Arrange
from cura.Arranging.ShapeArray import ShapeArray
from cura.Scene.ZOffsetDecorator import ZOffsetDecorator

i18n_catalog = i18nCatalog("cura")

if TYPE_CHECKING:
    from UM.Scene.SceneNode import SceneNode


def arrange_objects(nodes: List["SceneNode"], fixed_nodes: List["SceneNode"], min_offset = 8):
    global_container_stack = Application.getInstance().getMachineManager().getActiveMachine()
    machine_width = global_container_stack.getProperty("machine_width", "value")
    machine_depth = global_container_stack.getProperty("machine_depth", "value")

    arranger = Arrange.create(x = machine_width, y = machine_depth, fixed_nodes = fixed_nodes, min_offset = min_offset)

    # Collect nodes to be placed
    nodes_arr = []  # fill with (size, node, offset_shape_arr, hull_shape_arr)
    for node in nodes:
        offset_shape_arr, hull_shape_arr = ShapeArray.fromNode(node, min_offset = min_offset)
        if offset_shape_arr is None:
            Logger.log("w", "Node [%s] could not be converted to an array for arranging...", str(node))
            continue
        nodes_arr.append((offset_shape_arr.arr.shape[0] * offset_shape_arr.arr.shape[1], node, offset_shape_arr, hull_shape_arr))

    # Sort the nodes with the biggest area first.
    nodes_arr.sort(key=lambda item: item[0])
    nodes_arr.reverse()

    # Place nodes one at a time
    start_priority = 0
    last_priority = start_priority
    last_size = None
    grouped_operation = GroupedOperation()
    not_fit_count = 0
    for idx, (size, node, offset_shape_arr, hull_shape_arr) in enumerate(nodes_arr):
        # For performance reasons, we assume that when a location does not fit,
        # it will also not fit for the next object (while what can be untrue).
        if last_size == size:  # This optimization works if many of the objects have the same size
            start_priority = last_priority
        else:
            start_priority = 0
        best_spot = arranger.bestSpot(hull_shape_arr, start_prio = start_priority)
        x, y = best_spot.x, best_spot.y
        node.removeDecorator(ZOffsetDecorator)
        if node.getBoundingBox():
            center_y = node.getWorldPosition().y - node.getBoundingBox().bottom
        else:
            center_y = 0
        if x is not None:  # We could find a place
            last_size = size
            last_priority = best_spot.priority

            arranger.place(x, y, offset_shape_arr)  # take place before the next one
            grouped_operation.addOperation(TranslateOperation(node, Vector(x, center_y, y), set_position = True))
        else:
            Logger.log("d", "Arrange all: could not find spot!")
            found_solution_for_all = False
            grouped_operation.addOperation(TranslateOperation(node, Vector(200, center_y, -not_fit_count * 20), set_position = True))
            not_fit_count += 1

    grouped_operation.push()
