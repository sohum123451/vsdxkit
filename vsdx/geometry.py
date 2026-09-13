from __future__ import annotations

import copy
import sys
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

import vsdx

from .inheritance import InheritedRow
from .logging_support import get_logger
from .xmlio import xml_value

logger = get_logger(__name__)

namespace = "{http://schemas.microsoft.com/office/visio/2012/main}"  # visio file name space


def _row_index_sort_key(index: str) -> tuple[int, int, str]:
    """Order row indexes as numbers, with anything unparseable left at the end."""
    return (0, int(index), "") if index.isdigit() else (1, 0, index)


class Geometry:
    """The geometry of a shape: a Geometry section's cells and rows.

    A shape that has a master starts from the master's section and layers its
    own on top. Rows merge by index and then by cell name, so a row that
    overrides only X keeps the master's Y; a row carrying ``Del="1"`` removes
    the inherited row entirely. Section cells merge less carefully: they are a
    list, not a dict, so an instance cell is *appended* after the inherited one
    of the same name rather than replacing it.

    An inherited row reads the master's cells but is marked
    :attr:`~vsdx.inheritance.InheritedRow.inherited`. The first write to it,
    through :attr:`GeometryRow.x`, :meth:`move`, :meth:`set_move_to` or
    :meth:`set_line_to`, materialises an override row on this shape and leaves
    the master alone.

    The merge copies the master's :attr:`cells` list and :attr:`rows` dict
    rather than taking them by reference, so an instance applying a ``Del``
    row, or gaining a row of its own, does not change what the master
    Geometry sees. That holds however long the master object lives. The
    copies are shallow: an inherited :class:`GeometryCell` is still the
    master's until a setter replaces it, so writing a cell's value without
    going through the row still edits the master.
    """

    def __init__(self, xml: Element, shape: vsdx.Shape):
        # get shape master geometry, and append/overwrite with actual shape instance data

        self.xml = xml  # expect an Element of Section with attr N='Geometry'
        self.cells: list[GeometryCell] = []  # cells directly under Geometry section
        self.rows: dict[str, GeometryRow] = {}  # rows keyed by IX: type(T) + index(IX), each with named cells
        self.shape = shape

        # the master is resolved once per Shape and held there; ask for it
        # once here too, so a shape whose master this is the only reader of
        # still pays the walk of the master page a single time
        master_shape = shape.master_shape
        master_geometry = master_shape.geometry if master_shape else None

        if master_geometry is not None:
            # copy the list rather than alias it, so what this instance merges,
            # deletes or adds stays out of the master Geometry's view
            self.cells = list(master_geometry.cells)

        for cell in self.xml.findall(f"{namespace}Cell"):
            self.cells.append(GeometryCell(parent=self, xml=cell))

        if master_geometry is not None:
            self.rows = {index: row.inherited_by(self) for index, row in master_geometry.rows.items()}
        for row in self.xml.findall(f"{namespace}Row"):
            index = row.attrib.get("IX")
            if index is None:
                continue  # a row without IX cannot be addressed
            g_row = GeometryRow(geometry=self, xml=row, master_geometry_row=self.rows.get(index))
            self.rows[index] = g_row
            if g_row.del_bool:  # remove if master row over-ridden with a  deleted item
                del self.rows[index]

    def start_pos(self) -> tuple[float | None, float | None] | None:
        """The start of the path, from the first MoveTo or RelMoveTo row.

        The two row types answer in different coordinate systems. MoveTo gives
        the row's own X/Y, relative to the shape. RelMoveTo ignores the row's
        offset altogether and gives the shape's PinX/PinY, measured from the
        page or from the enclosing group. Check the row type before relying on
        the result. Returns ``None`` if the shape has neither row.
        """
        for row in self.rows.values():  # type: GeometryRow
            if str(row.row_type).lower() == "moveto":
                return row.x, row.y
            if str(row.row_type).lower() == "relmoveto":
                # todo: find actual x,y based on shape width/height and relmoveto x,y
                return self.shape.x, self.shape.y
        return None

    def move(self, x_delta: float, y_delta: float) -> None:
        """Shift the rows that hold absolute coordinates.

        Only MoveTo and LineTo rows are shifted; relative rows are offsets
        from the previous point and stay as they are. A coordinate the row
        does not define is left undefined rather than treated as zero.

        An inherited row is read from the master and written to a copy on this
        shape, so no other shape drawn from that master moves with it.
        """
        for r in self.rows.values():  # type: GeometryRow
            logger.debug("r=%s %s", type(r), r)
            if str(r.row_type).lower() in ["moveto", "lineto"]:  # todo: include other absolute row types
                x = r.x
                y = r.y
                if x is not None:
                    r.x = x + x_delta
                if y is not None:
                    r.y = y + y_delta
                logger.debug("r=%s %s after move %s, %s", type(r), r, x_delta, y_delta)

    def set_move_to(self, x: float, y: float, move_to_index: int = 0) -> None:
        """Set the coordinates of one MoveTo row.

        ``move_to_index`` counts MoveTo rows in order, and is not a row IX.
        Nothing happens if the shape has no MoveTo row at that position.

        An inherited row is copied down onto this shape first, so the master is
        left alone; the copy carries the value but not the master cell's ``F``
        formula. A cell this shape already owns keeps its formula, and Visio
        re-evaluates that formula over the value written here.
        """
        move_tos = [r for r in self.rows.values() if str(r.row_type).lower() == "moveto"]
        if len(move_tos) > move_to_index:
            move_to = move_tos[move_to_index]  # type: GeometryRow
            move_to.x = x
            move_to.y = y

    def set_line_to(self, x: float, y: float, line_to_index: int = 0) -> None:
        """Set the coordinates of one LineTo row.

        Behaves as :meth:`set_move_to` does, over LineTo rows.
        """
        line_tos = [r for r in self.rows.values() if str(r.row_type).lower() == "lineto"]
        if len(line_tos) > line_to_index:
            line_to = line_tos[line_to_index]  # type: GeometryRow
            line_to.x = x
            line_to.y = y

    def __repr__(self):
        s = f"Geometry: {self.cells} {[(r.row_type, r.index, r.x, r.y) for r in self.rows.values()]}"
        s += f"\nGeometry: {vsdx.pretty_print_element(self.xml)}"
        return s


class GeometryRow(InheritedRow):
    """A row with type(T) and index(IX), each containing a list of Cells"""

    """See: https://docs.microsoft.com/en-us/office/client-developer/visio/row-element-geometry-sectionvisio-xml """

    def __init__(
        self,
        geometry: Geometry,
        xml: Element | None,
        master_geometry_row: GeometryRow | None,
        T: str | None = None,
        IX: str | int | None = None,
    ):
        self.geometry = geometry  # parent of this row
        self.xml = xml if type(xml) is Element else self.create_row_xml(T or "", str(IX))
        # Create a dictionary of each Cell element, indexed by name
        # a row's cells are keyed by name (unlike Geometry.cells, a list)
        self.cells: dict[str, GeometryCell] = dict(master_geometry_row.cells) if master_geometry_row else {}
        # add/overwrite cells values with master as basis id present
        for cell in self.xml.findall(f"{namespace}Cell"):
            g_cell = GeometryCell(parent=self, xml=cell)
            if g_cell.name is not None:
                self.cells[g_cell.name] = g_cell

    def inherited_by(self, geometry: Geometry) -> GeometryRow:
        """This row as an instance's Geometry sees it, marked inherited.

        The copy reads the master's Row element and the master's cells; the
        first write to it calls :meth:`make_local`, which gives the instance a
        Row of its own to hold the change.
        """
        row = copy.copy(self)
        row.geometry = geometry
        row.cells = dict(self.cells)
        row.inherited = True
        return row

    @override
    def _materialise(self) -> None:
        """Add this row to the instance's Geometry section, in place.

        The object keeps its identity, because :attr:`Geometry.rows` already
        holds it and :meth:`Geometry.move` may be iterating over it. Only the
        XML changes, from the master's Row element to a new, empty one on the
        instance. The cells stay the master's until a setter replaces one, so
        a coordinate the caller does not write is still inherited.
        """
        row_type, index = self.row_type, self.index
        self.xml = self.create_row_xml(row_type or "", str(index))
        logger.debug("materialised inherited row on the instance: %s", self)

    def create_row_xml(self, T: str, IX: str) -> Element:
        """Add a Row element for this row to the parent Geometry section.

        The row is placed in index order among the section's existing rows,
        after the Cell and Trigger children the Visio schema requires them all
        to follow. Row order is the order the path is drawn in, so indexes are
        compared as numbers. Sorted as text, IX 10 would land ahead of IX 2 and
        redraw the path in a different order.

        Both arguments have already been stringified by the caller, so
        ``IX=None`` arrives as the literal ``"None"`` and passes the
        emptiness check.
        """
        if not T or not IX:
            raise ValueError(f"cannot create a geometry row without T and IX (got T={T!r}, IX={IX!r})")
        # Create new row xml
        row = ET.fromstring(f'<Row xmlns="{namespace[1:-1]}" T="{T}" IX="{IX}" />')
        children = list(self.geometry.xml)
        indexes = [x.attrib["IX"] for x in children if x.tag == f"{namespace}Row" and x.attrib.get("IX")]
        if IX in indexes:
            # todo: replace existing row with new one
            raise ValueError(f"geometry row IX={IX} already exists")
        indexes.append(IX)
        indexes.sort(key=_row_index_sort_key)
        # count positions from the section's first Row, so the Cells ahead of
        # it are not counted as places a Row could go
        first_row = next((i for i, child in enumerate(children) if child.tag == f"{namespace}Row"), len(children))
        self.geometry.xml.insert(first_row + indexes.index(IX), row)

        self.geometry.rows[IX] = self
        return row

    @property
    def row_type(self) -> str | None:
        return self.xml.attrib.get("T")

    @row_type.setter
    def row_type(self, value: str | int) -> None:
        self.xml.attrib["T"] = str(value)

    @property
    def index(self) -> str | None:
        """The row's IX attribute.

        :attr:`Geometry.rows` is keyed when the section is read, so setting
        this afterwards leaves the row filed under its old index.
        """
        return self.xml.attrib.get("IX")

    @index.setter
    def index(self, value: str | int) -> None:
        self.xml.attrib["IX"] = str(value)

    @property
    def x(self) -> float | None:
        """The row's X coordinate, or ``None`` if the row does not set one.

        Setting it adds the cell if the row lacks one. A row or cell inherited
        from a master is copied onto this shape first, so the master keeps the
        coordinate every other instance reads.
        """
        x_cell = self.cells.get("X")
        return float(x_cell.value) if x_cell and x_cell.value else None

    @x.setter
    def x(self, value: float | str) -> None:
        self.make_local()  # an inherited row gets one of its own before it is written
        cell_value = xml_value(value)
        x_cell = self.cells.get("X")  # type: GeometryCell
        if x_cell is None or x_cell.parent is not self:
            # create new cell if none exists, or if the existing one is the master's
            x_cell = GeometryCell(parent=self, xml=None, name="X", value=cell_value)
            logger.debug("x_cell=%s", x_cell)
        x_cell.value = cell_value

    @property
    def y(self) -> float | None:
        """The row's Y coordinate. Behaves as :attr:`x` does."""
        y_cell = self.cells.get("Y")
        return float(y_cell.value) if y_cell and y_cell.value else None

    @y.setter
    def y(self, value: float | str) -> None:
        self.make_local()
        cell_value = xml_value(value)
        y_cell = self.cells.get("Y")
        if y_cell is None or y_cell.parent is not self:
            # create new cell if none exists, or if the existing one is the master's
            y_cell = GeometryCell(parent=self, xml=None, name="Y", value=cell_value)
            logger.debug("y_cell=%s", y_cell)
        y_cell.value = cell_value

    @property
    def del_bool(self) -> str | None:
        """The Del attribute: whether a row inherited from a master is deleted.

        Assigning a falsy value removes the attribute, and raises ``KeyError``
        if it was not set to begin with.
        """
        return self.xml.attrib.get("Del")

    @del_bool.setter
    def del_bool(self, value: object) -> None:
        if value:
            self.xml.attrib["Del"] = "1"  # set to 1 if truthy
        else:
            del self.xml.attrib["Del"]  # remove attribute if falsy

    def __repr__(self):
        s = f"Row[{self.index}] del:{self.del_bool}: {self.row_type}={self.cells}"
        return s


class GeometryCell:
    """class to represent a Cell element, a name value pair. This may be a child of Geometry or of GeometryRow"""

    def __init__(
        self,
        parent: GeometryRow | Geometry,
        xml: Element | None,
        name: str | None = None,
        value: float | str | None = None,
    ):
        self.parent = parent
        self.parent_xml = parent.xml
        self.xml = xml if type(xml) is Element else self.create_cell_xml(name or "")
        if name:
            self.name = name
        if value is not None:
            self.value = value

    def create_cell_xml(self, name: str) -> Element:
        cell = ET.fromstring(f'<Cell xmlns="{namespace[1:-1]}"  />')
        self.parent_xml.append(cell)
        if isinstance(self.parent, GeometryRow):
            self.parent.cells[name] = self
        else:
            self.parent.cells.append(self)
        return cell

    @property
    def value(self) -> str | None:
        return self.xml.attrib.get("V")

    @value.setter
    def value(self, value: float | str) -> None:
        self.xml.attrib["V"] = xml_value(value)

    @property
    def formula(self) -> str | None:
        return self.xml.attrib.get("F")

    @formula.setter
    def formula(self, value: str) -> None:
        self.xml.attrib["F"] = xml_value(value)

    @property
    def name(self) -> str | None:
        return self.xml.attrib.get("N")

    @name.setter
    def name(self, value: str) -> None:
        self.xml.attrib["N"] = xml_value(value)

    @property
    def func(self) -> str | None:  # assume F stands for function, i.e. F="Width*0.5"
        return self.xml.attrib.get("F")

    def __repr__(self):
        s = f"{self.name}={self.value}"
        if self.func:
            s += f" func={self.func}"
        return s
