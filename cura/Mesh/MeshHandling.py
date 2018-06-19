import os
from typing import List, TYPE_CHECKING

from UM.Math.Vector import Vector
from UM.Operations.AddSceneNodeOperation import AddSceneNodeOperation
from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator

from cura.Arranging.Arrange import Arrange
from cura.Arranging.ShapeArray import ShapeArray
from cura.Scene.BuildPlateDecorator import BuildPlateDecorator
from cura.Scene.CuraSceneNode import CuraSceneNode
from cura.Scene.ConvexHullDecorator import ConvexHullDecorator
from cura.Scene.SliceableObjectDecorator import SliceableObjectDecorator

if TYPE_CHECKING:
    from UM.Scene.SceneNode import SceneNode


def process_read_mesh(file_name: str, nodes: List["SceneNode"]) -> List["SceneNode"]:
    from UM.Application import Application
    application = Application.getInstance()
    machine_manager = application.getMachineManager()
    global_stack = machine_manager.getActiveMachine().global_stack
    build_volume = application.getBuildVolume()

    target_build_plate = -1

    root = application.getController().getScene().getRoot()
    fixed_nodes = []
    for node_ in DepthFirstIterator(root):
        if node_.callDecoration("isSliceable") and node_.callDecoration(
                "getBuildPlateNumber") == target_build_plate:
            fixed_nodes.append(node_)
    machine_width = global_stack.getProperty("machine_width", "value")
    machine_depth = global_stack.getProperty("machine_depth", "value")
    arranger = Arrange.create(x = machine_width, y = machine_depth, fixed_nodes = fixed_nodes)
    min_offset = 8
    default_extruder_position = "0"
    default_extruder_id = global_stack.extruders[default_extruder_position].getId()

    new_nodes = []
    for original_node in nodes:
        # Create a CuraSceneNode just if the original node is not that type
        if isinstance(original_node, CuraSceneNode):
            node = original_node
        else:
            node = CuraSceneNode()
            node.setMeshData(original_node.getMeshData())

            # Setting meshdata does not apply scaling.
            if original_node.getScale() != Vector(1.0, 1.0, 1.0):
                node.scale(original_node.getScale())

        node.setSelectable(True)
        node.setName(os.path.basename(file_name))
        build_volume.checkBoundsAndUpdate(node)

        sliceable_decorator = SliceableObjectDecorator()
        node.addDecorator(sliceable_decorator)

        scene = application.getController().getScene()

        # If there is no convex hull for the node, start calculating it and continue.
        if not node.getDecorator(ConvexHullDecorator):
            node.addDecorator(ConvexHullDecorator())
        for child in node.getAllChildren():
            if not child.getDecorator(ConvexHullDecorator):
                child.addDecorator(ConvexHullDecorator())

        # Arrange object
        if node.callDecoration("isSliceable"):
            # Only check position if it's not already blatantly obvious that it won't fit.
            if node.getBoundingBox() is None or build_volume.getBoundingBox() is None or node.getBoundingBox().width < build_volume.getBoundingBox().width or node.getBoundingBox().depth < build_volume.getBoundingBox().depth:
                # Find node location
                offset_shape_arr, hull_shape_arr = ShapeArray.fromNode(node, min_offset=min_offset)

                # If a model is to small then it will not contain any points
                if offset_shape_arr is None and hull_shape_arr is None:
                    break

                # Step is for skipping tests to make it a lot faster. it also makes the outcome somewhat rougher
                arranger.findNodePlacement(node, offset_shape_arr, hull_shape_arr, step=10)

        # This node is deep copied from some other node which already has a BuildPlateDecorator, but the deepcopy
        # of BuildPlateDecorator produces one that's associated with build plate -1. So, here we need to check if
        # the BuildPlateDecorator exists or not and always set the correct build plate number.
        build_plate_decorator = node.getDecorator(BuildPlateDecorator)
        if build_plate_decorator is None:
            build_plate_decorator = BuildPlateDecorator(target_build_plate)
            node.addDecorator(build_plate_decorator)
        build_plate_decorator.setBuildPlateNumber(target_build_plate)

        op = AddSceneNodeOperation(node, scene.getRoot())
        op.redo()

        node.callDecoration("setActiveExtruder", default_extruder_id)
        new_nodes.append(node)

    return new_nodes
