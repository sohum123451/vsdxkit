"""Characterisation tests for `vsdx.geometry`.

Nothing in the suite exercised `Geometry`, `GeometryRow` or `GeometryCell`
directly, so this module pins down what they do today, several faults
included. A test whose docstring says the behaviour is wrong is recording it,
not endorsing it; issue #76 lists them all. Rewrite those tests when the
behaviour is fixed.
"""

import os
import xml.etree.ElementTree as ET

import pytest

import vsdx
from vsdx import Geometry, GeometryCell, GeometryRow, Shape, VisioFile, namespace

basedir = os.path.dirname(os.path.realpath(__file__))

# `Conn A` in test9 is the one instance shape in the suite that inherits a
# Geometry section: master page 2 supplies five section cells and rows IX 1-3,
# the instance overrides row 2 and deletes row 3.
TEST9 = os.path.join(basedir, "test9_rect_and_line.vsdx")
PALETTE = os.path.join(basedir, "fixtures", "palette_extended.vsdx")
HOUSE = os.path.join(basedir, "test3_house.vsdx")
NESTED = os.path.join(basedir, "test10_nested_shapes.vsdx")


def geometry_xml(shape: Shape) -> ET.Element:
    """The shape's own Geometry section element."""
    section = shape.xml.find(f'{namespace}Section[@N="Geometry"]')
    assert section is not None
    return section


def reparse(shape: Shape) -> Shape:
    """Rebuild a Shape from its (possibly edited) XML.

    `Shape.geometry` is built on first read and then held, so editing the raw
    XML of a section means re-reading it through a new Shape to see the effect.
    """
    return Shape(xml=shape.xml, parent=shape.parent, page=shape.page)


def row_element(shape: Shape, index: str) -> ET.Element:
    element = geometry_xml(shape).find(f'{namespace}Row[@IX="{index}"]')
    assert element is not None
    return element


def cell_values(row: ET.Element) -> dict[str | None, str | None]:
    return {cell.attrib.get("N"): cell.attrib.get("V") for cell in row}


def row_indexes(shape: Shape) -> list[str | None]:
    return [row.attrib.get("IX") for row in geometry_xml(shape).findall(f"{namespace}Row")]


# --- inheriting a Geometry section from a master ----------------------------


def test_rows_absent_from_the_instance_are_inherited_from_the_master():
    with VisioFile(TEST9) as vis:
        connector = vis.pages[0].find_shape_by_text("Conn A")

        rows = connector.geometry.rows

        # row 1 exists only in the master, row 2 only in the instance
        assert sorted(rows) == ["1", "2"]
        assert (rows["1"].row_type, rows["1"].x, rows["1"].y) == ("MoveTo", 0.0, 0.0)
        assert (rows["2"].row_type, rows["2"].x, rows["2"].y) == ("LineTo", 3.543307044802283, 0.7874015655116189)
        # every row belongs to this shape's Geometry; the inherited one is
        # flagged, which is what the setters below act on
        assert rows["1"].geometry is connector.geometry
        assert rows["2"].geometry is connector.geometry
        assert (rows["1"].inherited, rows["2"].inherited) == (True, False)


def test_an_overridden_row_keeps_the_master_cells_it_does_not_replace():
    """Merging happens cell by cell, so an X-only override inherits the master Y."""
    with VisioFile(TEST9) as vis:
        connector = vis.pages[0].find_shape_by_text("Conn A")
        instance_row = row_element(connector, "2")
        instance_row.remove(instance_row.find(f'{namespace}Cell[@N="Y"]'))

        row = reparse(connector).geometry.rows["2"]

        assert row.x == 3.543307044802283  # from the instance
        assert row.y == -1.181102362204724  # inherited from the master


def test_a_row_deleted_by_the_instance_is_dropped_from_the_merge():
    with VisioFile(TEST9) as vis:
        connector = vis.pages[0].find_shape_by_text("Conn A")

        # the master defines row 3; the instance carries `<Row IX="3" Del="1"/>`
        assert row_element(connector, "3").attrib["Del"] == "1"
        assert "3" not in connector.geometry.rows


def test_the_merge_leaves_the_master_geometry_alone(monkeypatch):
    """The merge copies the master's rows and cells rather than aliasing them.

    The instance deletes row 3 and overrides row 2. Both used to be applied to
    the master `Geometry` object's own dict, which only ever went unnoticed
    because `Shape.master_shape` rebuilt the master on every access and the
    mutated object was thrown away. Memoise the master, as #261 needs to, and
    one shape's merge would reach every other, so this test pins it.
    """
    with VisioFile(TEST9) as vis:
        connector = vis.pages[0].find_shape_by_text("Conn A")
        master = connector.master_shape
        # every instance resolves to this one master object, as memoising the
        # resolution makes it; the master itself has none, or it would be its
        # own master and its geometry would never finish building
        monkeypatch.setattr(Shape, "master_shape", property(lambda self: None if self is master else master))

        instance_geometry = reparse(connector).geometry

        assert sorted(instance_geometry.rows) == ["1", "2"]
        assert sorted(master.geometry.rows) == ["1", "2", "3"]
        assert [cell.name for cell in master.geometry.cells] == ["NoFill", "NoLine", "NoShow", "NoSnap", "NoQuickDrag"]
        assert master.geometry.rows["2"].x == 0.0  # not the instance's 3.543307044802283


def test_section_cells_are_inherited_and_instance_cells_appended():
    """`Geometry.cells` is a list, so an instance cell shadows nothing.

    An instance `NoFill` lands *after* the inherited one rather than replacing
    it, and both stay readable. Callers reading `cells` by name have to take
    the last match.
    """
    with VisioFile(TEST9) as vis:
        connector = vis.pages[0].find_shape_by_text("Conn A")
        assert [cell.name for cell in connector.geometry.cells] == [
            "NoFill",
            "NoLine",
            "NoShow",
            "NoSnap",
            "NoQuickDrag",
        ]
        assert connector.geometry.cells[0].value == "1"  # the master's NoFill

        geometry_xml(connector).insert(0, ET.fromstring(f'<Cell xmlns="{namespace[1:-1]}" N="NoFill" V="0"/>'))
        cells = reparse(connector).geometry.cells

        assert [cell.name for cell in cells] == ["NoFill", "NoLine", "NoShow", "NoSnap", "NoQuickDrag", "NoFill"]
        assert [cell.value for cell in cells if cell.name == "NoFill"] == ["1", "0"]


def test_a_row_without_an_index_is_dropped():
    """Rows are keyed by IX, so one without an IX cannot be addressed."""
    with VisioFile(TEST9) as vis:
        line = vis.pages[0].find_shape_by_text("Line A")
        geometry_xml(line).append(ET.fromstring(f'<Row xmlns="{namespace[1:-1]}" T="LineTo"><Cell N="X" V="1"/></Row>'))

        assert sorted(reparse(line).geometry.rows) == ["1", "2"]


def test_a_shape_without_a_master_starts_from_its_own_rows_alone():
    with VisioFile(TEST9) as vis:
        line = vis.pages[0].find_shape_by_text("Line A")

        assert line.master_shape is None
        assert [(row.row_type, row.index) for row in line.geometry.rows.values()] == [("MoveTo", "1"), ("LineTo", "2")]
        assert [cell.name for cell in line.geometry.cells] == ["NoFill", "NoLine", "NoShow", "NoSnap", "NoQuickDrag"]


# --- start_pos --------------------------------------------------------------


def test_start_pos_of_a_moveto_shape_is_in_shape_local_coordinates():
    with VisioFile(PALETTE) as vis:
        process = vis.pages[0].find_shape_by_text("PALETTE_PROCESS")

        # the MoveTo row's own X/Y, not the shape's position on the page
        assert process.geometry.start_pos() == (0.0, 0.0)
        assert (process.x, process.y) == (2.0, 8.5)


@pytest.mark.parametrize(
    ("path", "text"),
    [
        (PALETTE, "PALETTE_DECISION"),
        (TEST9, "Rect A"),
        (HOUSE, "Shape Text"),
        (NESTED, "Shape 1.1.1"),
    ],
)
def test_start_pos_of_a_relmoveto_shape_is_the_shape_pin(path, text):
    """The RelMoveTo branch answers with the shape's pin rather than a point
    on the path.

    `Geometry.start_pos()` mixes coordinate systems depending on the row type
    it finds, and ignores the RelMoveTo offset outright (the module's own
    todo). The pin is measured from the page, or from the enclosing group;
    the nested case below sits inside one. Callers have to check the row
    type before they can use the result.
    """
    with VisioFile(path) as vis:
        shape = vis.pages[0].find_shape_by_text(text)

        assert shape.geometry.rows["1"].row_type == "RelMoveTo"
        assert shape.geometry.start_pos() == (shape.x, shape.y)


def test_start_pos_of_a_grouped_shape_is_relative_to_its_group():
    """A grouped shape's pin is measured inside its group, so the answer is
    comparable only between shapes with the same parent."""
    with VisioFile(NESTED) as vis:
        shape = vis.pages[0].find_shape_by_text("Shape 1.1.1")

        assert shape.parent.shape_type == "Group"
        assert shape.parent.parent.shape_type == "Group"
        # the outermost group sits at x 2.36 on the page; this answer does not
        assert shape.geometry.start_pos() == (0.6692913306848756, 0.7086614089604568)


def test_start_pos_is_none_without_a_move_row():
    with VisioFile(TEST9) as vis:
        line = vis.pages[0].find_shape_by_text("Line A")
        section = geometry_xml(line)
        section.remove(section.find(f'{namespace}Row[@T="MoveTo"]'))

        assert reparse(line).geometry.start_pos() is None


# --- move -------------------------------------------------------------------


def test_move_shifts_absolute_rows():
    with VisioFile(TEST9) as vis:
        line = vis.pages[0].find_shape_by_text("Line A")

        line.geometry.move(1.0, 2.0)

        assert [(row.row_type, row.x, row.y) for row in line.geometry.rows.values()] == [
            ("MoveTo", 1.0, 2.0),
            ("LineTo", 4.629741869488193, 2.0),
        ]


def test_move_leaves_relative_rows_alone():
    """Relative rows are offsets from the previous point, so moving the shape
    must not touch them; `move()` skips every row type but MoveTo and LineTo."""
    with VisioFile(TEST9) as vis:
        rect = vis.pages[0].find_shape_by_text("Rect A")
        before = [(row.row_type, row.x, row.y) for row in rect.geometry.rows.values()]

        rect.geometry.move(1.0, 2.0)

        assert [(row.row_type, row.x, row.y) for row in rect.geometry.rows.values()] == before


def test_move_leaves_a_missing_coordinate_missing():
    with VisioFile(TEST9) as vis:
        line = vis.pages[0].find_shape_by_text("Line A")
        geometry_xml(line).append(ET.fromstring(f'<Row xmlns="{namespace[1:-1]}" T="MoveTo" IX="9"><Cell N="Y" V="1"/></Row>'))
        geometry = reparse(line).geometry

        geometry.move(1.0, 2.0)

        row = geometry.rows["9"]
        assert (row.x, row.y) == (None, 3.0)
        assert "X" not in row.cells


def test_move_copies_an_inherited_row_onto_the_instance():
    """Moving one instance leaves the master alone, so no other instance moves.

    Row 1 is the master's. `Geometry.move()` reads the coordinates from there
    and writes the shifted pair to a row of the instance's own (#239).
    """
    with VisioFile(TEST9) as vis:
        connector = vis.pages[0].find_shape_by_text("Conn A")
        assert cell_values(row_element(connector.master_shape, "1")) == {"X": "0", "Y": "0"}

        connector.move(1.0, 2.0)

        assert cell_values(row_element(connector.master_shape, "1")) == {"X": "0", "Y": "0"}
        assert cell_values(row_element(connector, "1")) == {"X": "1.0", "Y": "2.0"}
        assert row_indexes(connector) == ["1", "2", "3"]
        assert (connector.geometry.rows["1"].x, connector.geometry.rows["1"].y) == (1.0, 2.0)


def test_a_row_copied_down_by_move_lands_after_the_sections_cells():
    """`Conn A` overrides a section cell, and every row has to come after it.

    A Section is `Cell*, Trigger*, Row*`, so a row wedged among the cells is a
    file Visio offers to repair.
    """
    with VisioFile(TEST9) as vis:
        connector = vis.pages[0].find_shape_by_text("Conn A")
        geometry_xml(connector).insert(0, ET.fromstring(f'<Cell xmlns="{namespace[1:-1]}" N="NoShow" V="1"/>'))
        connector = reparse(connector)

        connector.move(1.0, 2.0)

        assert [child.tag.rpartition("}")[2] for child in geometry_xml(connector)] == ["Cell", "Row", "Row", "Row"]
        assert row_indexes(connector) == ["1", "2", "3"]


# --- set_move_to / set_line_to ----------------------------------------------


def test_set_move_to_materialises_an_inherited_row_on_the_instance(vsdx_copy):
    """The copy survives a round trip through the saved package."""
    path = vsdx_copy("test9_rect_and_line.vsdx")
    with VisioFile(path) as vis:
        connector = vis.pages[0].find_shape_by_text("Conn A")

        connector.geometry.set_move_to(1.25, 2.5)

        assert cell_values(row_element(connector, "1")) == {"X": "1.25", "Y": "2.5"}
        assert cell_values(row_element(connector.master_shape, "1")) == {"X": "0", "Y": "0"}
        vis.save_vsdx(path)

    with VisioFile(path) as vis:
        row = vis.pages[0].find_shape_by_text("Conn A").geometry.rows["1"]
        assert (row.row_type, row.x, row.y) == ("MoveTo", 1.25, 2.5)


def test_set_line_to_updates_an_instance_row_in_place():
    with VisioFile(TEST9) as vis:
        connector = vis.pages[0].find_shape_by_text("Conn A")

        connector.geometry.set_line_to(9.0, 8.0)

        assert cell_values(row_element(connector, "2")) == {"X": "9.0", "Y": "8.0"}
        # no duplicate row was added alongside the one already there
        assert row_indexes(connector) == ["2", "3"]


def test_set_line_to_materialises_an_inherited_row_on_the_instance():
    """A connector that has never been re-routed inherits its LineTo rows."""
    with VisioFile(TEST9) as vis:
        connector = vis.pages[0].find_shape_by_text("Conn A")
        geometry_xml(connector).remove(row_element(connector, "2"))
        connector = reparse(connector)
        assert connector.geometry.rows["2"].inherited

        connector.geometry.set_line_to(9.0, 8.0)

        assert cell_values(row_element(connector, "2")) == {"X": "9.0", "Y": "8.0"}
        assert cell_values(row_element(connector.master_shape, "2")) == {"X": "0", "Y": "-1.181102362204724"}


def test_set_move_to_leaves_a_formula_that_overrides_the_value_it_writes():
    """The value is written but the cell's F formula is left in place.

    `Line A`'s MoveTo X carries `F="Width*0"`. Visio recomputes V from F, so
    the coordinate written here is discarded when the file is opened.
    """
    with VisioFile(TEST9) as vis:
        line = vis.pages[0].find_shape_by_text("Line A")

        line.geometry.set_move_to(7.0, 8.0)

        x_cell = line.geometry.rows["1"].cells["X"]
        assert x_cell.value == "7.0"
        assert x_cell.formula == "Width*0"


def test_copying_an_inherited_row_down_drops_the_masters_formula():
    """The opposite of the case above, and just as wrong.

    A row copied down by `set_move_to()` gets fresh X/Y cells holding only a
    value, so a formula the master used to compute the coordinate is dropped
    instead of inherited.
    """
    with VisioFile(TEST9) as vis:
        connector = vis.pages[0].find_shape_by_text("Conn A")
        master_x = row_element(connector.master_shape, "1").find(f'{namespace}Cell[@N="X"]')
        master_x.attrib["F"] = "Width*0"
        connector = reparse(connector)
        assert connector.geometry.rows["1"].cells["X"].formula == "Width*0"

        connector.geometry.set_move_to(1.25, 2.5)

        assert row_element(connector, "1").find(f'{namespace}Cell[@N="X"]').attrib == {"N": "X", "V": "1.25"}
        assert connector.geometry.rows["1"].cells["X"].formula is None


@pytest.mark.parametrize("text", ["Rect A", "Line A"])
def test_setters_are_a_noop_when_the_row_type_is_absent(text):
    """`Rect A` has no MoveTo or LineTo row; `Line A` has one of each."""
    with VisioFile(TEST9) as vis:
        shape = vis.pages[0].find_shape_by_text(text)
        geometry = shape.geometry
        before = ET.tostring(geometry.xml)

        geometry.set_move_to(5.0, 5.0, move_to_index=1)
        geometry.set_line_to(5.0, 5.0, line_to_index=1)

        assert ET.tostring(geometry.xml) == before


def test_set_move_to_and_set_line_to_address_rows_by_position_not_index():
    """The index argument counts matching rows; it is not a row IX."""
    with VisioFile(PALETTE) as vis:
        process = vis.pages[0].find_shape_by_text("PALETTE_PROCESS")

        process.geometry.set_line_to(4.0, 5.0, line_to_index=2)

        # LineTo rows are IX 2, 3, 4 and 5; the third of them is IX 4
        assert cell_values(row_element(process, "4")) == {"X": "4.0", "Y": "5.0"}


# --- GeometryRow ------------------------------------------------------------


def test_creating_a_row_requires_a_type_and_an_index():
    with VisioFile(TEST9) as vis:
        geometry = vis.pages[0].find_shape_by_text("Line A").geometry

        with pytest.raises(ValueError, match="without T and IX"):
            GeometryRow(geometry=geometry, xml=None, master_geometry_row=None, T="", IX="1")


def test_creating_a_row_rejects_an_index_already_in_the_section():
    with VisioFile(TEST9) as vis:
        geometry = vis.pages[0].find_shape_by_text("Line A").geometry

        with pytest.raises(ValueError, match="IX=1 already exists"):
            GeometryRow(geometry=geometry, xml=None, master_geometry_row=None, T="MoveTo", IX="1")


def test_creating_a_row_with_no_index_yields_the_string_none():
    """`IX=None` is stringified before the guard sees it, so it passes.

    The row lands with `IX="None"`, which Visio will not accept.
    """
    with VisioFile(TEST9) as vis:
        geometry = vis.pages[0].find_shape_by_text("Line A").geometry

        row = GeometryRow(geometry=geometry, xml=None, master_geometry_row=None, T="MoveTo", IX=None)

        assert row.index == "None"
        assert geometry.rows["None"] is row


def test_a_new_row_is_placed_after_the_sections_cells_and_in_index_order():
    """A tenth row used to show two placement faults; it now shows neither.

    The row goes after the Cell children the Visio schema requires rows to
    follow, and IX 10 sorts after IX 2 rather than as the text "10" would, so
    the path is still drawn in index order.
    """
    with VisioFile(TEST9) as vis:
        line = vis.pages[0].find_shape_by_text("Line A")

        GeometryRow(geometry=line.geometry, xml=None, master_geometry_row=None, T="LineTo", IX=10)

        assert row_indexes(line) == ["1", "2", "10"]
        assert [child.tag.rpartition("}")[2] for child in geometry_xml(line)] == [
            "Cell",
            "Cell",
            "Cell",
            "Cell",
            "Cell",
            "Row",
            "Row",
            "Row",
        ]


def test_a_row_index_that_is_not_a_number_sorts_last():
    """`IX="None"` is unorderable against real indexes, so it goes at the end."""
    with VisioFile(TEST9) as vis:
        line = vis.pages[0].find_shape_by_text("Line A")

        GeometryRow(geometry=line.geometry, xml=None, master_geometry_row=None, T="LineTo", IX=None)
        GeometryRow(geometry=line.geometry, xml=None, master_geometry_row=None, T="LineTo", IX=3)

        assert row_indexes(line) == ["1", "2", "3", "None"]


def test_coordinate_setters_create_the_cells_they_need():
    with VisioFile(TEST9) as vis:
        line = vis.pages[0].find_shape_by_text("Line A")
        geometry_xml(line).append(ET.fromstring(f'<Row xmlns="{namespace[1:-1]}" T="MoveTo" IX="9"/>'))
        row = reparse(line).geometry.rows["9"]
        assert (row.x, row.y) == (None, None)

        row.x = 3  # int
        row.y = "4.5"  # string

        assert (row.x, row.y) == (3.0, 4.5)
        assert cell_values(row.xml) == {"X": "3", "Y": "4.5"}


def test_setting_a_coordinate_on_an_inherited_row_copies_it_onto_the_instance():
    """The row's own setter goes through the same path `move()` does.

    Only X is written, so the instance's row carries X alone and Y is still
    read from the master (#239).
    """
    with VisioFile(TEST9) as vis:
        connector = vis.pages[0].find_shape_by_text("Conn A")
        row = connector.geometry.rows["1"]

        row.x = 42.0

        assert cell_values(row_element(connector.master_shape, "1")) == {"X": "0", "Y": "0"}
        assert cell_values(row_element(connector, "1")) == {"X": "42.0"}
        assert (row.x, row.y) == (42.0, 0.0)
        assert row.inherited is False


def test_del_bool_can_be_set_and_cleared():
    with VisioFile(TEST9) as vis:
        row = vis.pages[0].find_shape_by_text("Line A").geometry.rows["1"]
        assert row.del_bool is None

        row.del_bool = True
        assert row.del_bool == "1"

        row.del_bool = 0
        assert row.del_bool is None


def test_clearing_del_bool_that_is_not_set_raises():
    """Clearing an absent Del raises KeyError instead of doing nothing."""
    with VisioFile(TEST9) as vis:
        row = vis.pages[0].find_shape_by_text("Line A").geometry.rows["1"]

        with pytest.raises(KeyError):
            row.del_bool = False


def test_changing_a_rows_index_does_not_rekey_the_geometry():
    """`Geometry.rows` is keyed at parse time, so renumbering desyncs it."""
    with VisioFile(TEST9) as vis:
        geometry = vis.pages[0].find_shape_by_text("Line A").geometry
        row = geometry.rows["1"]

        row.row_type = "LineTo"
        row.index = 7

        assert (row.row_type, row.index) == ("LineTo", "7")
        assert sorted(geometry.rows) == ["1", "2"]
        assert geometry.rows["1"] is row


# --- GeometryCell -----------------------------------------------------------


def test_a_new_cell_joins_its_section_and_the_cells_list():
    with VisioFile(TEST9) as vis:
        geometry = vis.pages[0].find_shape_by_text("Line A").geometry

        cell = GeometryCell(parent=geometry, xml=None, name="NoLine", value=1)

        assert geometry.cells[-1] is cell
        assert (cell.name, cell.value) == ("NoLine", "1")
        assert geometry.xml.findall(f'{namespace}Cell[@N="NoLine"]')[-1] is cell.xml


def test_a_new_cell_joins_its_row_under_its_name():
    with VisioFile(TEST9) as vis:
        row = vis.pages[0].find_shape_by_text("Line A").geometry.rows["1"]

        cell = GeometryCell(parent=row, xml=None, name="A", value="POLYLINE(0,0)")

        assert row.cells["A"] is cell
        assert row.xml.find(f'{namespace}Cell[@N="A"]') is cell.xml


def test_formula_and_func_read_the_same_attribute():
    with VisioFile(PALETTE) as vis:
        decision = vis.pages[0].find_shape_by_text("PALETTE_DECISION")
        cell = decision.geometry.rows["2"].cells["A"]

        assert cell.formula == cell.func == "POLYLINE(0, 0, 1,0.5, 0.5,0, 0,0.5)"

        cell.formula = "POLYLINE(0,0)"

        assert cell.func == "POLYLINE(0,0)"
        assert cell.xml.attrib["F"] == "POLYLINE(0,0)"


def test_reprs_identify_the_element_they_describe():
    """These show up in logs and debugger output, so they carry the identifiers."""
    with VisioFile(PALETTE) as vis:
        decision = vis.pages[0].find_shape_by_text("PALETTE_DECISION")
        geometry = decision.geometry

        assert repr(geometry.rows["2"].cells["A"]).startswith("A=POLYLINE(0, 0, 1,0.5, 0.5,0, 0,0.5) func=")
        assert repr(geometry.rows["1"]).startswith("Row[1] del:None: RelMoveTo=")
        assert "('PolylineTo', '2', 1.5, 2.0)" in repr(geometry)


def test_geometry_is_exported_from_the_package_root():
    assert (vsdx.Geometry, vsdx.GeometryRow, vsdx.GeometryCell) == (Geometry, GeometryRow, GeometryCell)


# --- when the Geometry is built ---------------------------------------------


def test_geometry_is_built_on_first_read_not_when_the_shape_is_built(monkeypatch):
    """Walking a page mints a Shape per element; none of them build a Geometry.

    Building one resolves the shape's master, which walks the master page, so
    doing it eagerly made every walk of a page pay for geometry nobody read
    (#261).
    """
    built: list[Shape] = []

    class CountedGeometry(Geometry):
        def __init__(self, xml, shape):
            built.append(shape)
            super().__init__(xml=xml, shape=shape)

    monkeypatch.setattr(vsdx, "Geometry", CountedGeometry)

    with VisioFile(TEST9) as vis:
        shapes = vis.pages[0].all_shapes

        assert shapes and built == []

        geometry = shapes[0].geometry

        assert len(built) == 1
        assert shapes[0].geometry is geometry  # held, not rebuilt on each read


def test_the_master_is_resolved_once_per_shape(monkeypatch):
    """Geometry, cells, text and data properties all read through the master."""
    resolutions = []
    resolve = Shape._resolve_master_shape

    def counting(self):
        resolutions.append(self)
        return resolve(self)

    monkeypatch.setattr(Shape, "_resolve_master_shape", counting)

    with VisioFile(TEST9) as vis:
        connector = vis.pages[0].find_shape_by_text("Conn A")

        assert connector.geometry is not None
        assert connector.master_shape is not None
        assert connector.data_properties is not None

        # by identity: the master resolves its own master (to None) in passing
        assert sum(1 for shape in resolutions if shape is connector) == 1


def test_the_section_is_located_when_the_shape_is_built():
    """Only building the Geometry is deferred; which section it reads is not.

    `Shape.cells` lists that same section's rows from `__init__`, so the two
    stay in step: a section removed from the XML afterwards is seen by neither
    until the shape is read again.
    """
    with VisioFile(TEST9) as vis:
        line = vis.pages[0].find_shape_by_text("Line A")
        line.xml.remove(geometry_xml(line))

        assert line.geometry is not None  # located before the removal
        assert "Geometry/LineTo/X" in line.cells
        assert reparse(line).geometry is None


def test_a_cell_added_to_the_master_is_picked_up_by_a_shape_holding_it():
    """The memo is keyed on the master element's children, not taken on trust."""
    with VisioFile(os.path.join(basedir, "test5_master.vsdx")) as vis:
        page = vis.pages[0]
        shape = next(s for s in page.all_shapes if s.master_page_ID)
        master_page = shape.master_page
        assert shape.cell_value("LockDelete") is None

        master_page.child_shapes[0].set_cell_value("LockDelete", 1)

        assert shape.cell_value("LockDelete") == "1"
