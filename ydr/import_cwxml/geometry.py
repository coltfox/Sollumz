import bpy
from mathutils import Vector
from typing import NamedTuple

from ...cwxml.drawable import GeometryItem, BoneItem
from ...sollumz_converter import CWXMLConverter
from ...sollumz_properties import SollumType
from ...tools.meshhelper import create_uv_layer, create_vertexcolor_layer
from ...tools.blenderhelper import create_sollumz_object
from ..shader_materials import create_tinted_shader_graph


class VertexComponents(NamedTuple):
    positions: list[Vector]
    normals: list[Vector]
    uv_map: dict[str, list[tuple[float, float]]]
    color_map: dict[str, list[tuple[float, float]]]
    vertex_groups: dict[int, list[tuple[float, float]]]


class GeometryCWXMLConverter(CWXMLConverter[GeometryItem]):
    """Converts geometry inside drawables to bpy objects."""
    @property
    def vertex_components(self) -> VertexComponents:
        """Access vertex data as separate data structures."""
        if self._vertex_components is None:
            vertices = self.cwxml.vertex_buffer.get_data()
            self._vertex_components = GeometryCWXMLConverter.get_vertex_components(
                vertices)

        return self._vertex_components

    @vertex_components.setter
    def vertex_components(self, new_vertex_components):
        self._vertex_components = new_vertex_components

    def __init__(self, cwxml: GeometryItem):
        super().__init__(cwxml)
        self._vertex_components = None
        self.mesh: bpy.types.Mesh = None

    def create_bpy_object(self, name: str, bones: list[BoneItem], materials: list[bpy.types.Material]) -> bpy.types.Object:
        # Editing mesh data-block before assigning it to an object is a lot quicker for some reason
        mesh = self.create_mesh(name, materials)

        geometry_object = create_sollumz_object(
            SollumType.DRAWABLE_GEOMETRY, mesh, name=name)
        self.bpy_object = geometry_object

        self.create_vertex_groups(bones)
        self.set_geometry_weights()

        create_tinted_shader_graph(geometry_object)

        return geometry_object

    def create_mesh(self, name: str, materials: list[bpy.types.Material]) -> bpy.types.Mesh:
        """Create the mesh data-block for this geometry."""

        # Split indices into groups of 3
        indices = self.cwxml.index_buffer.data
        faces = [indices[i:i + 3] for i in range(0, len(indices), 3)]

        mesh: bpy.types.Mesh = bpy.data.meshes.new(name)
        self.mesh = mesh
        mesh.from_pydata(self.vertex_components.positions, [], faces)
        mesh.validate()

        self.create_material(materials)
        self.set_smooth_normals()

        self.create_uv_layers()
        self.create_vertex_color_layers()

        return mesh

    def create_material(self, materials: list[bpy.types.Material]):
        """Set material for this geometry based on the index of the shader on the drawable.
        Displays warning when not found."""
        shader_index = self.cwxml.shader_index
        if not 0 <= shader_index < len(materials):
            self.import_operator.report(
                {"WARNING"}, f"Material not set for {self.mesh}. Shader index of {shader_index} not found!")
            return

        self.mesh.materials.append(materials[shader_index])

    def set_smooth_normals(self):
        """Set the normals of this geometry and smooth them."""
        self.mesh.polygons.foreach_set(
            "use_smooth", [True] * len(self.mesh.polygons))
        self.mesh.normals_split_custom_set_from_vertices(
            self.vertex_components.normals)
        self.mesh.use_auto_smooth = True

    def create_uv_layers(self):
        """Create all uv layers for this geometry."""
        for i, (name, coords) in enumerate(self.vertex_components.uv_map.items()):
            create_uv_layer(self.mesh, i, name, coords)

    def create_vertex_color_layers(self):
        """Create all vertex color layers for this geometry."""
        for i, (name, coords) in enumerate(self.vertex_components.color_map.items()):
            create_vertexcolor_layer(self.mesh, i, name, coords)

    def create_vertex_groups(self, bones: list[BoneItem]):
        """Create vertex groups for this geometry based on the number
        of bones present in the drawable skeleton."""

        # Some drawables have weights defined, but no associated bones (just the bone indices).
        # This is common in mp clothing, where the weights are defined, but the bone
        # indices index the bones on the mp skeleton (which has to be acquired externally).
        # These weights will still be imported, but under the name "EXTERNAL_BONE". This will
        # allow the remaining bones to be acquired later if need be.
        bone_ids = self.cwxml.bone_ids
        bpy_vertex_groups = self.bpy_object.vertex_groups

        for bone_index in self.vertex_components.vertex_groups.keys():
            bone_name = "UNKNOWN_BONE"

            if bones and bone_index < len(bones):
                bone_name = bones[bone_index].name
            elif bone_ids and bone_index < len(bone_ids):
                bone_name = f"EXTERNAL_BONE.{bone_index}"

            bpy_vertex_groups.new(name=bone_name)

    def set_geometry_weights(self):
        """Set weights for this geometry."""
        for i, vertex_group in enumerate(self.vertex_components.vertex_groups.values()):
            for vertex_index, weight in vertex_group:
                self.bpy_object.vertex_groups[i].add(
                    [vertex_index], weight, "ADD")

    def create_armature_modifier(self, armature_object: bpy.types.Object):
        modifier = self.bpy_object.modifiers.new("Armature", "ARMATURE")
        modifier.object = armature_object

    @staticmethod
    def get_vertex_components(vertices: list[tuple]):
        """Split vertex buffer into separate componenets."""
        positions = []
        normals = []
        uv_map = {}
        color_map = {}
        vertex_groups = {}

        for vertex_index, vertex in enumerate(vertices):
            positions.append(vertex.position)

            # Vertex layouts differ, so we have to check if a given vertex has the desired attribute
            if hasattr(vertex, "normal"):
                normals.append(Vector(vertex.normal))

            if hasattr(vertex, "blendweights"):
                for i in range(0, 4):
                    weight = vertex.blendweights[i] / 255

                    # if weight <= 0.0:
                    #     continue

                    bone_index = vertex.blendindices[i]
                    if bone_index not in vertex_groups:
                        vertex_groups[bone_index] = []

                    vertex_groups[bone_index].append((vertex_index, weight))

            for key, value in vertex._asdict().items():
                if "texcoord" in key:
                    if not key in uv_map.keys():
                        uv_map[key] = []
                    uv_map[key].append(tuple(value))
                if "colour" in key:
                    if not key in color_map.keys():
                        color_map[key] = []
                    color_map[key].append(tuple(value))

        return VertexComponents(positions, normals, uv_map, color_map, vertex_groups)
