# Copyright (c) 2018 Ultimaker B.V.
# Cura is released under the terms of the LGPLv3 or higher.

from .QualityGroup import QualityGroup


class QualityChangesGroup(QualityGroup):
    def __init__(self, name: str, quality_type: str, parent = None):
        super().__init__(name, quality_type, parent)

    def addNode(self, node: "QualityNode"):
        extruder_position = node.metadata.get("position")

        if extruder_position is None and self.node_for_global is not None or extruder_position in self.nodes_for_extruders:
            # TODO
            raise RuntimeError()

        if extruder_position is None:
            self.node_for_global = node
        else:
            self.nodes_for_extruders[extruder_position] = node

    def __str__(self) -> str:
        return "%s[<%s>, available = %s]" % (self.__class__.__name__, self.name, self.is_available)
