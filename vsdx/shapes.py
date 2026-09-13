from __future__ import annotations

import copy
import html
import re
import sys
import warnings
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING
from xml.etree.ElementTree import Element

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

import deprecation

import vsdx
from vsdx import namespace

from .inheritance import InheritedRow
from .logging_support import get_logger
from .xmlio import xml_value

if TYPE_CHECKING:
    from vsdx.connectors import Connect

logger = get_logger(__name__)


def __getattr__(name: str):
    # Module-level lazy attribute (PEP 562): typing.get_type_hints on the
    # quoted 'Connect' annotation resolves through module globals, and
    # vsdx.connectors imports this module, so the reference is provided on
    # demand instead of at import time (which would be a cycle).
    if name == "Connect":
        from vsdx.connectors import Connect

        return Connect
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


shape_type_names = {  # a map from English language shape to a list of know names for that Shape type
    # note that Shape names may be appended with a number e.g. 'Dynamischer Verbinder.2'
    "Dynamic Connector": ["dynamic connector", "dynamischer verbinder"]
}


def to_float(val: str | None, cell: str | None = None) -> float | None:
    """Convert a ShapeSheet value to float.

    ``None`` input stays ``None``: an absent cell is distinct from a malformed
    one. A malformed numeric value raises rather than masquerading as a real
    zero coordinate; the message carries the cell name and raw value.
    """
    if val is None:
        return None
    try:
        return float(val)
    except ValueError as error:
        label = f" for {cell}" if cell else ""
        raise ValueError(f"malformed numeric ShapeSheet value{label}: {val!r}") from error


def _coordinate_value(value: float | str | None) -> str:
    """Return a ShapeSheet coordinate value without serialising nulls."""
    if value is None:
        raise TypeError("coordinate value cannot be None")
    return xml_value(value)


# Visio brackets a shape's text with character (`cp`) and paragraph (`pp`)
# formatting runs. Editing the text has to leave those runs in place, so they
# are located by walking the Text element's children: the serialised form they
# take depends on which namespace prefix is in force, and matching it as text
# is what tied the old implementation to ElementTree's `ns0:` prefix.
_TEXT_RUN_TAGS = frozenset({f"{namespace}cp", f"{namespace}pp"})


def _is_formatting_run(element: Element) -> bool:
    """True for a self-closing character/paragraph formatting element."""
    return element.tag in _TEXT_RUN_TAGS and len(element) == 0 and not element.text


class Cell:
    """Represents a Cell element in a vsdx xml file"""

    def __init__(self, xml: Element, shape: Shape):
        self.xml = xml
        self.shape = shape

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

    @property
    def func(self) -> str | None:  # assume F stands for function, i.e. F="Width*0.5"
        return self.xml.attrib.get("F")

    def __repr__(self):
        return f"Cell: name={self.name} val={self.value} func={self.func}"


class DataProperty(InheritedRow):
    """Represents a single Data Property item associated with a Shape object

    A property a shape inherits from its master is handed out marked
    :attr:`~vsdx.inheritance.InheritedRow.inherited`. Setting :attr:`value` on
    one materialises an override row on the instance rather than writing to the
    master page's XML.
    """

    shape: Shape
    xml: Element
    name: str | None
    value_type: str | None
    label: str | None
    prompt: str | None
    sort_key: str | None

    def __init__(self, *, xml: Element, shape: Shape):
        """init a DataProperty from a property xml element in a Shape object"""
        name = xml.attrib.get("N")
        # get Cell element for each property of DataProperty
        label_cell = xml.find(f'{namespace}Cell[@N="Label"]')

        # initialise empty DataProperty properties
        self.shape = shape  # reference back to Shape object
        self.xml = xml  # reference to xml used to create DataProperty
        self.name = name
        self.value_type = None
        self.label = None
        self.prompt = None
        self.sort_key = None

        self.shape = shape  # reference back to Shape object
        self.xml = xml  # reference to xml used to create DataProperty

        if isinstance(label_cell, Element):
            value_type_cell = xml.find(f'{namespace}Cell[@N="Type"]')
            prompt_cell = xml.find(f'{namespace}Cell[@N="Prompt"]')
            sort_key_cell = xml.find(f'{namespace}Cell[@N="SortKey"]')

            # get values from each Cell Element
            self.value_type = value_type_cell.attrib.get("V") if isinstance(value_type_cell, Element) else None
            self.label = label_cell.attrib.get("V") if isinstance(label_cell, Element) else None
            self.prompt = prompt_cell.attrib.get("V") if isinstance(prompt_cell, Element) else None
            self.sort_key = sort_key_cell.attrib.get("V") if isinstance(sort_key_cell, Element) else None
        else:
            # over-ridden master shape properties have no label - only a name and value
            master_shape = shape.master_shape
            master_props: list[DataProperty] = (
                [p for p in master_shape.data_properties.values() if p.name == name] if master_shape is not None else []
            )
            if master_props:
                # get first match 0 - there should always be one item
                master_prop = master_props[0]  # type: DataProperty
                self.label = master_prop.label
                self.value_type = master_prop.value_type
                self.prompt = master_prop.prompt
                self.sort_key = master_prop.sort_key

    def inherited_by(self, shape: Shape) -> DataProperty:
        """This property as an instance of the master sees it, marked inherited.

        The copy reads the master's Row element, so label, type and prompt are
        already resolved; the first write to :attr:`value` calls
        :meth:`make_local`, which gives ``shape`` a row of its own.
        """
        prop = copy.copy(self)
        prop.shape = shape
        prop.inherited = True
        return prop

    @override
    def _materialise(self) -> None:
        """Add an override row for this property to the instance's shape.

        Visio matches an override to the master's row by the row's ``N``
        attribute, and reads label, type and prompt from the master, so the
        new row needs nothing but that name; the caller is about to write the
        ``Value`` cell. A master row with no name has nothing to match on, so
        the label is carried down to keep the property addressable.
        """
        section = self.shape.xml.find(f'{namespace}Section[@N="Property"]')
        if section is None:
            section = ET.fromstring(f'<Section xmlns="{namespace[1:-1]}" N="Property"/>')
            # Sections follow the shape's Cell and Trigger children and precede
            # its Text and Shapes, so append to the run of them rather than to
            # the shape (see Shape.get_or_create_cell)
            insert_at = 0
            for index, child in enumerate(list(self.shape.xml)):
                if child.tag in (f"{namespace}Cell", f"{namespace}Trigger", f"{namespace}Section"):
                    insert_at = index + 1
            self.shape.xml.insert(insert_at, section)

        row = ET.fromstring(f'<Row xmlns="{namespace[1:-1]}"/>')
        if self.name is not None:
            row.attrib["N"] = self.name
        else:
            label_cell = self.xml.find(f'{namespace}Cell[@N="Label"]')
            if label_cell is not None:
                row.append(copy.deepcopy(label_cell))
        section.append(row)
        self.xml = row
        logger.debug("materialised inherited data property %r on shape %s", self.label, self.shape.ID)

    @property
    def value(self) -> str | None:
        """Get the value of the data property, or None when it has none.

        Reading is free of side effects: it neither creates the ``Value`` cell
        nor tidies a ``No Formula`` formula, so inspecting a document does not
        change the bytes it saves.
        """
        value_cell = self.xml.find(f'{namespace}Cell[@N="Value"]')
        if not isinstance(value_cell, Element):
            return None
        if value_cell.attrib.get("V") is not None:
            return value_cell.attrib.get("V")  # value from the V attribute
        return value_cell.text or None  # or from the element's inner text

    @value.setter
    def value(self, value: float | str | None) -> None:
        """Set the value of the data property, creating the cell if absent.

        Writing is also where a placeholder ``No Formula`` formula is cleared:
        leaving it beside a new value would make the cell disagree with itself,
        and Visio may not show the value at all. Upstream dave-howard/vsdx#79.

        The cell's declared unit is left alone. Stamping ``STR`` over it would
        retype a date or numeric property as a string, and a cell created here
        declares no unit rather than guessing one from the value.

        A property inherited from a master is given an override row on this
        shape first, so the master's value is left as it was, and with it every
        other shape drawn from that master.
        """
        self.make_local()
        text = "" if value is None else str(value)
        value_cell = self.xml.find(f'{namespace}Cell[@N="Value"]')
        if not isinstance(value_cell, Element):
            value_cell = Element(f"{namespace}Cell")
            value_cell.attrib["N"] = "Value"
            value_cell.attrib["V"] = text
            self.xml.append(value_cell)
            return
        if value_cell.attrib.get("V") is None and value_cell.text:
            value_cell.text = text  # this row carries its value as inner text
        else:
            value_cell.attrib["V"] = text
        if value_cell.attrib.get("F") == "No Formula":
            del value_cell.attrib["F"]

    def get_attribute(self, name: str, attrib: str) -> str | None:
        """Get the attribute value of the cell element"""
        element = self._get_element(name)
        if isinstance(element, Element):
            return element.attrib.get(attrib)

    def set_attribute(self, name: str, attrib: str, value: str) -> bool:
        """Set the attribute value of the cell element"""
        element = self._get_element(name)
        if isinstance(element, Element):
            element.attrib[attrib] = value
            return True
        return False

    def remove_attribute(self, name: str, attrib: str) -> bool:
        """Remove the attribute from the cell element"""
        element = self._get_element(name)
        if isinstance(element, Element) and attrib in element.attrib:
            del element.attrib[attrib]
            return True
        return False

    def _get_element(self, name: str) -> Element | None:
        """Get the value of the data property as an xml element"""
        element = self.xml.find(f'{namespace}Cell[@N="{name}"]')
        return element


class Shape:
    """Represents a single shape, or a group shape containing other shapes"""

    xml: Element
    parent: vsdx.Page | Shape
    tag: str
    ID: str | None
    master_shape_ID: str | None
    master_page_ID: str | None
    shape_type: str | None
    shape_name: str | None
    page: vsdx.Page
    cells: dict[str, Cell]
    _geometry: vsdx.Geometry | None
    _geometry_xml: Element | None
    _master_shape: Shape | None
    _master_shape_resolved: bool
    _master_shape_key: tuple[Element, ...] | None
    _data_properties: dict[str, DataProperty] | None
    _data_properties_key: tuple[Element, ...] | None

    def __init__(self, xml: Element, parent: vsdx.Page | Shape, page: vsdx.Page):
        self.xml = xml
        self.parent = parent
        self.tag = xml.tag
        self.ID = xml.attrib.get("ID", None)
        self.master_shape_ID = xml.attrib.get("MasterShape", None)
        self.master_page_ID = xml.attrib.get("Master", None)  # i.e. '2', note: the master_page.name not list index
        if self.master_page_ID is None and isinstance(parent, Shape):  # in case of a sub_shape
            self.master_page_ID = parent.master_page_ID
        self.shape_type = xml.attrib.get("Type", None)
        self.shape_name = xml.attrib.get("NameU") or xml.get("Name")
        self.page = page

        # get Cells in Shape
        self.cells = {}
        self._geometry = None
        self._master_shape = None
        self._master_shape_resolved = False
        self._master_shape_key = None
        for e in self.xml.findall(f"{namespace}Cell"):
            cell = Cell(xml=e, shape=self)
            if cell.name is not None:
                self.cells[cell.name] = cell
        geometry = self.xml.find(f'{namespace}Section[@N="Geometry"]')
        # the section is located here, alongside the cells read out of it, but
        # the Geometry object over it is left to the property: building one
        # resolves this shape's master, and a caller walking a page for ids or
        # text never looks at geometry at all
        self._geometry_xml = geometry if type(geometry) is Element else None
        if type(geometry) is Element:
            # this shape's own Geometry cells, read straight from the XML; the
            # merged view of the master's is Shape.geometry's job
            for r in geometry.findall(f"{namespace}Row"):
                row_type = r.attrib["T"]
                if row_type:
                    for e in r.findall(f"{namespace}Cell"):
                        cell = vsdx.Cell(xml=e, shape=self)
                        if cell.name is not None:
                            self.cells[f"Geometry/{row_type}/{cell.name}"] = cell

        control = self.xml.find(f'{namespace}Section[@N="Control"]')
        if type(control) is Element:
            for r in control.findall(f"{namespace}Row"):
                row_type = r.attrib["N"]
                if row_type:
                    for e in r.findall(f"{namespace}Cell"):
                        cell = vsdx.Cell(xml=e, shape=self)
                        if cell.name is not None:
                            self.cells[f"Control/{row_type}/{cell.name}"] = cell

        self._data_properties = None  # internal field to hold Shape.data_properties, set by property
        self._data_properties_key = None  # the Property section state the cache was built from

    def __repr__(self):
        return f"<Shape tag={self.tag} ID={self.ID} is_master=({self.is_master_shape}) type={self.shape_type} text='{self.text}' >"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, vsdx.Shape):
            return False

        return hash(self) == hash(other)

    def __hash__(self):
        return hash((self.ID, self.page.name, self.page.vis.filename))

    @property
    def geometry(self) -> vsdx.Geometry | None:
        """This shape's Geometry section, merged with the master's, or ``None``.

        Built on first read and then held for as long as this Shape object
        lives, so ``shape.geometry`` twice gives the same object and a row
        written through one read is seen by the next.

        Building it resolves the shape's master, which is why it is deferred:
        walking a page for ids or text mints a Shape per element and touches
        no geometry at all.

        Only the building is deferred. Which section it reads is decided when
        the Shape is built, as :attr:`cells` decides which of that section's
        rows it lists, so the two stay in step: a section added to or removed
        from the XML afterwards is seen by neither until the shape is read
        again. This attribute is read-only - a Geometry is a view of this
        shape's own section, not something to assign from elsewhere.
        """
        if self._geometry_xml is None:
            return None
        if self._geometry is None:
            self._geometry = vsdx.Geometry(xml=self._geometry_xml, shape=self)
        return self._geometry

    @property
    def is_master_shape(self) -> bool:
        """Returns True if the shape is a master or False if the shape inherits from a master shape or has no master"""
        return self.page.is_master_page  # shape is a 'master' if it is contained by a master page

    @property
    def universal_name(self) -> str | None:
        name_univ = self.xml.attrib.get("NameU")  # default to shapes own unicode name
        if self.master_shape:
            page_sheet = self.master_shape.page._pagesheet_xml
            layer = page_sheet.find(f'{namespace}Section[@N="Layer"]')
            name_univ_cell = layer.find(f'{namespace}Cell[@N="NameUniv"]') if layer is not None else None
            if name_univ_cell is not None:
                name_univ = name_univ_cell.attrib.get("V") or name_univ
        return name_univ

    def copy(self, page: vsdx.Page | None = None) -> Shape:
        """Copy this Shape to the specified destination Page, and return the copy.

        If the destination page is not specified, the Shape is copied to its containing Page.

        :param page: The page where the new Shape will be placed.
            If not specified, the copy will be placed in the original shape's page.
        :type page: :class:`Page` (Optional)

        :return: :class:`Shape` the new copy of shape
        """
        dst_page = page or self.page
        new_shape_xml = self.page.vis.copy_shape(self.xml, dst_page)

        # parent decides where the new shape tag lands: the destination
        # page's Shapes tag, or the source shape's own parent
        parent: vsdx.Page | Shape
        if page is not None:
            # copy_shape() above guarantees a Shapes tag exists on the page
            page_shapes = page._shapes
            parent = page_shapes[0] if page_shapes else page
        else:
            parent = self.parent

        return Shape(xml=new_shape_xml, parent=parent, page=dst_page)

    @property
    def master_shape(self) -> Shape | None:
        """Get this shapes master

        Returns this Shape's master as a Shape object (or None)

        The result is held rather than rebuilt on every read. Resolving a
        master walks the master page and builds a Shape there, and a shape
        reads through its master for geometry, cells, text and data
        properties, so the same answer was being paid for several times over.

        The memo is checked against the master element's children, by
        identity, in the way :attr:`data_properties` is checked against this
        shape's Property rows: a cell added to, removed from or swapped on the
        master is picked up on the next read. One limitation remains, the same
        one :attr:`data_properties` has: the key covers the master shape's own
        children, not their contents, so a row added *inside* the master's
        Geometry or Property section leaves the memo in place. Walking the
        page again resolves it - ``child_shapes`` and ``all_shapes`` mint a
        Shape per element, so no memo survives a traversal.
        """
        if self._master_shape_resolved and self._master_shape_key == self._master_shape_state():
            return self._master_shape
        self._master_shape = self._resolve_master_shape()
        self._master_shape_resolved = True
        self._master_shape_key = self._master_shape_state()
        return self._master_shape

    def _master_shape_state(self) -> tuple[Element, ...] | None:
        """The master element's children, by identity: what the memo was built from."""
        master = self._master_shape
        return None if master is None else tuple(master.xml)

    def _resolve_master_shape(self) -> Shape | None:
        if self.master_page_ID is None:
            return None  # no master set for this Shape
        master_page = self.page.vis.get_master_page_by_id(self.master_page_ID)
        if not master_page:
            return None  # None if no master page set for this Shape
        master_shape = master_page.child_shapes[0]  # there's always a single master shape in a master page

        if self.master_shape_ID is not None:
            master_sub_shape = master_shape.find_shape_by_id(self.master_shape_ID)
            return master_sub_shape

        return master_shape

    @property
    def master_page(self) -> vsdx.Page | None:
        """Get this pages master

        Returns this Page's master as a Page object (or None)

        """
        if self.master_page_ID is None:
            return None
        return self.page.vis.get_master_page_by_id(self.master_page_ID)

    @property
    def data_properties(self) -> dict[str, DataProperty]:
        """
        Get data properties of the shape - which labels, names, and values
        returns a dictionary of DataProperty objects indexed by property label

        The result is cached against this shape's own ``Property`` rows, so
        adding, removing or replacing one is picked up on the next read. A row
        edited *in place* is not: the cache is keyed on row identity, so
        renaming a property's ``Label`` leaves the dictionary keyed under the
        old label until some row is added or removed. One limitation remains,
        over inherited properties:

        - A property inherited from a master is resolved when this shape is
          first read. Editing the master afterwards is not reflected here: the
          cache key covers this shape's own rows, not the master's, and this
          shape holds the master it resolved for as long as it lives.

        Setting :attr:`DataProperty.value` on an inherited property is safe:
        the property is marked inherited, so writing to it creates an override
        row on this shape and leaves the master alone.
        :meth:`DataProperty.set_attribute` and
        :meth:`DataProperty.remove_attribute` do not yet do this, and still
        write an inherited property's cells in the master.

        :return: Dict[str, DataProperty]
        """
        properties_xml = self.xml.find(f'{namespace}Section[@N="Property"]')
        property_rows: list[Element] = [] if properties_xml is None else properties_xml.findall(f"{namespace}Row")
        # The rows themselves, by identity: a tuple of them costs no more to
        # build than a count and also catches a row that was swapped for a
        # different one, which leaves the count unchanged.
        key = tuple(property_rows)
        if self._data_properties is not None and self._data_properties_key == key:
            return self._data_properties

        # marked copies, so neither this shape's rows nor a write through an
        # inherited property reaches what the master hands back
        master = self.master_shape
        properties: dict[str, DataProperty] = (
            {label: prop.inherited_by(self) for label, prop in master.data_properties.items()} if master is not None else {}
        )
        for prop in property_rows:
            data_prop = DataProperty(xml=prop, shape=self)
            # add properties to dict to allow fast lookup by property.label
            # (a property row without a Label cell keys under "")
            properties[data_prop.label or ""] = data_prop
        self._data_properties = properties  # cache for next call
        self._data_properties_key = key
        return properties

    def shape_value(self, name: str) -> str | None:
        return self.xml.attrib.get(name, None)

    def cell_value(self, name: str) -> str | None:
        cell = self.cells.get(name)
        if cell:
            return cell.value

        if self.master_page_ID is not None:
            master = self.master_shape
            if master is not None:
                return master.cell_value(name)
        return None

    def cell_formula(self, name: str) -> str | None:
        cell = self.cells.get(name)
        if cell:
            return cell.formula

        if self.master_page_ID is not None:
            master = self.master_shape
            if master is not None:
                return master.cell_formula(name)
        return None

    def set_cell_value(self, name: str, value: float | str) -> None:
        cell = self.cells.get(name)
        if cell:  # only set value of existing item
            cell.value = value
            return
        cell_xml = None
        if self.master_page_ID is not None and self.master_shape:
            # copy master if master has this Cell (this will default same formula)
            master_cell_xml = self.master_shape.xml.find(f'{namespace}Cell[@N="{name}"]')
            if master_cell_xml is not None:  # use master Cell if found
                logger.debug("creating cell from: %s", ET.tostring(master_cell_xml))
                cell_xml = ET.fromstring(ET.tostring(master_cell_xml))
        if cell_xml is None:  # create a new Cell
            cell_xml = ET.fromstring(f'<Cell xmlns="{namespace[1:-1]}" N="{name}" />')
        # create new Cell from xml
        self.cells[name] = Cell(xml=cell_xml, shape=self)
        self.cells[name].value = value
        cells = self.xml.findall(f"{namespace}Cell")
        if len(cells):
            self.xml.insert(list(self.xml).index(cells[-1]) + 1, cell_xml)  # insert after last Cell
        else:
            self.xml.insert(0, cell_xml)

    def set_cell_formula(self, name: str, value: str) -> None:
        cell = self.cells.get(name)
        if cell:  # only set value of existing item
            cell.formula = value
            return
        cell_xml = None
        if self.master_page_ID is not None and self.master_shape:
            # copy master if master has this Cell (this will default same value)
            master_cell_xml = self.master_shape.xml.find(f'{namespace}Cell[@N="{name}"]')
            if master_cell_xml is not None:  # use master Cell if found
                logger.debug("creating cell from: %s", ET.tostring(master_cell_xml))
                cell_xml = ET.fromstring(ET.tostring(master_cell_xml))
        if cell_xml is None:  # create a new Cell
            cell_xml = ET.fromstring(f'<Cell xmlns:ns0="{namespace[1:-1]}" N="{name}" />')
        # create new Cell from xml
        self.cells[name] = Cell(xml=cell_xml, shape=self)
        self.cells[name].formula = value
        cells = self.xml.findall(f"{namespace}Cell")
        if len(cells):
            self.xml.insert(list(self.xml).index(cells[-1]) + 1, cell_xml)  # insert after last Cell
        else:
            self.xml.insert(0, cell_xml)

    @property
    def line_style_id(self) -> str | None:
        return self.xml.attrib.get("LineStyle")

    @line_style_id.setter
    def line_style_id(self, value: str | int) -> None:
        self.xml.attrib["LineStyle"] = str(value)

    @property
    def fill_style_id(self) -> str | None:
        return self.xml.attrib.get("FillStyle")

    @fill_style_id.setter
    def fill_style_id(self, value: str | int) -> None:
        self.xml.attrib["FillStyle"] = str(value)

    @property
    def text_style_id(self) -> str | None:
        return self.xml.attrib.get("TextStyle")

    @text_style_id.setter
    def text_style_id(self, value: str | int) -> None:
        self.xml.attrib["TextStyle"] = str(value)

    @property
    def line_weight(self) -> float | None:
        val = self.cell_value("LineWeight")
        return to_float(val, cell="LineWeight")

    @line_weight.setter
    def line_weight(self, value: float | str) -> float | None:
        self.set_cell_value("LineWeight", xml_value(value))

    @property
    def line_color(self) -> str | None:
        return self.cell_value("LineColor")

    @line_color.setter
    def line_color(self, value: str) -> None:
        self.set_cell_value("LineColor", xml_value(value))

    @property
    def fill_color(self) -> str | None:
        return self.cell_value("FillForegnd")

    @fill_color.setter
    def fill_color(self, value: str) -> None:
        self.set_cell_value("FillForegnd", xml_value(value))

    @property
    def text_color(self) -> str | None:
        """Get text color of shape - returns only first color attribute if there are many"""
        char_section = self.xml.find(f'{namespace}Section[@N="Character"]')
        color_cells = char_section.findall(f'{namespace}Row/{namespace}Cell[@N="Color"]') if char_section is not None else None
        if color_cells:
            return color_cells[0].attrib.get("V")

    @text_color.setter
    def text_color(self, value: str | int) -> None:
        """Set text color of shape - sets only first color attribute if there are many"""
        char_section = self.xml.find(f'{namespace}Section[@N="Character"]')
        color_cells = char_section.findall(f'{namespace}Row/{namespace}Cell[@N="Color"]') if char_section is not None else None
        if color_cells:
            color_cells[0].attrib["V"] = str(value)

    @property
    def end_arrow(self) -> str | None:
        return self.cell_value("EndArrow")

    @end_arrow.setter
    def end_arrow(self, value: int) -> None:
        if value is True:
            value = 13  # 13 is standard arrow
        if value is False:
            value = 0  # no arrow
        self.set_cell_value("EndArrow", xml_value(value))

    @property
    def x(self) -> float | None:
        return to_float(self.cell_value("PinX"), cell="PinX")

    @x.setter
    def x(self, value: float | str) -> None:
        self.set_cell_value("PinX", _coordinate_value(value))

    @property
    def y(self) -> float | None:
        return to_float(self.cell_value("PinY"), cell="PinY")

    @y.setter
    def y(self, value: float | str) -> None:
        self.set_cell_value("PinY", _coordinate_value(value))

    @property
    def loc_x(self) -> float | None:
        return to_float(self.cell_value("LocPinX"), cell="LocPinX")

    @loc_x.setter
    def loc_x(self, value: float | str) -> None:
        self.set_cell_value("LocPinX", _coordinate_value(value))

    @property
    def loc_x_f(self) -> str | None:
        return self.cell_formula("LocPinX")

    @property
    def loc_y(self) -> float | None:
        return to_float(self.cell_value("LocPinY"), cell="LocPinY")

    @loc_y.setter
    def loc_y(self, value: float | str) -> None:
        self.set_cell_value("LocPinY", _coordinate_value(value))

    @property
    def loc_y_f(self) -> str | None:
        return self.cell_formula("LocPinY")

    @property
    def line_to_x(self) -> float | None:
        return to_float(self.cell_value("Geometry/LineTo/X"), cell="Geometry/LineTo/X")

    @line_to_x.setter
    def line_to_x(self, value: float | str) -> None:
        self.set_cell_value("Geometry/LineTo/X", _coordinate_value(value))

    @property
    def line_to_y(self) -> float | None:
        return to_float(self.cell_value("Geometry/LineTo/Y"), cell="Geometry/LineTo/Y")

    @line_to_y.setter
    def line_to_y(self, value: float | str) -> None:
        self.set_cell_value("Geometry/LineTo/Y", _coordinate_value(value))

    @property
    def begin_x(self) -> float | None:
        return to_float(self.cell_value("BeginX"), cell="BeginX")

    @begin_x.setter
    def begin_x(self, value: float | str) -> None:
        self.set_cell_value("BeginX", _coordinate_value(value))

    @property
    def begin_y(self) -> float | None:
        return to_float(self.cell_value("BeginY"), cell="BeginY")

    @begin_y.setter
    def begin_y(self, value: float | str) -> None:
        self.set_cell_value("BeginY", _coordinate_value(value))

    @property
    def end_x(self) -> float | None:
        return to_float(self.cell_value("EndX"), cell="EndX")

    @end_x.setter
    def end_x(self, value: float | str) -> None:
        self.set_cell_value("EndX", _coordinate_value(value))

    @property
    def end_y(self) -> float | None:
        return to_float(self.cell_value("EndY"), cell="EndY")

    @end_y.setter
    def end_y(self, value: float | str) -> None:
        self.set_cell_value("EndY", _coordinate_value(value))

    def move(self, x_delta: float, y_delta: float) -> None:
        if self.geometry:
            self.geometry.move(x_delta, y_delta)
        if self.begin_x is not None:
            self.begin_x = self.begin_x + x_delta
        self.x = (self.x or 0.0) + x_delta
        if self.begin_y is not None:
            self.begin_y = self.begin_y + y_delta
        self.y = (self.y or 0.0) + y_delta

    def get_or_create_cell(self, name: str, v: str | None = None, f: str | None = None) -> vsdx.Cell:
        """Set or create a named cell on this shape.

        Existing cells have their V/F attributes updated in place. New cells
        are inserted after the last direct Cell child so the shape keeps the
        schema ordering (cells ahead of Text/Sections).

        :param name: cell name (N attribute), e.g. 'PinX'
        :param v: value to set on the V attribute (optional)
        :param f: formula to set on the F attribute (optional)
        :return: the Cell object
        """
        cell = self.cells.get(name)
        if cell is not None:
            if f is not None:
                cell.formula = f
            if v is not None:
                cell.value = v
            return cell
        attribs = f'N="{name}"'
        if v is not None:
            attribs += f' V="{v}"'
        if f is not None:
            attribs += f' F="{f}"'
        cell_el = ET.fromstring(f'<Cell xmlns="{vsdx.namespace[1:-1]}" {attribs}/>')
        insert_at = 0
        for i, child in enumerate(list(self.xml)):
            if child.tag == f"{vsdx.namespace}Cell":
                insert_at = i + 1
        self.xml.insert(insert_at, cell_el)
        cell = vsdx.Cell(xml=cell_el, shape=self)
        self.cells[name] = cell
        return cell

    @property
    def height(self) -> float | None:
        return to_float(self.cell_value("Height"), cell="Height")

    @height.setter
    def height(self, value: float | str) -> float | None:
        self.set_cell_value("Height", _coordinate_value(value))

    @property
    def width(self) -> float | None:
        return to_float(self.cell_value("Width"), cell="Width")

    @width.setter
    def width(self, value: float | str) -> float | None:
        self.set_cell_value("Width", _coordinate_value(value))

    @property
    def angle(self) -> float | None:
        return to_float(self.cell_value("Angle"), cell="Angle")

    @angle.setter
    def angle(self, value: float | str) -> None:
        self.set_cell_value("Angle", _coordinate_value(value))

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        # get absolute bounds of a shape relative to page
        s = self
        if s.begin_x is None and s.x is None and s.loc_x is None:
            return 0.0, 0.0, 0.0, 0.0  # shape has no bounds
        bx = s.begin_x if s.begin_x is not None else (s.x or 0.0) - (s.loc_x or 0.0)
        by = s.begin_y if s.begin_y is not None else (s.y or 0.0) - (s.loc_y or 0.0)
        ex = s.end_x if s.end_x is not None else bx + (s.width or 0.0)
        ey = s.end_y if s.end_y is not None else by + (s.height or 0.0)

        return bx, by, ex, ey

    @property
    def relative_bounds(self) -> tuple[float, float, float, float]:
        # get bounds of a shape relative to it's parent (if shape has a parent)
        bx, by, ex, ey = self.bounds
        if isinstance(self.parent, Shape) and self.parent.shape_type == "Group":
            pbx, pby, _pex, _pey = self.parent.bounds
            bx += pbx
            by += pby
            ex += pbx
            ey += pby

        return bx, by, ex, ey

    @property
    def center_x_y(self) -> tuple[float | None, float | None]:
        if self.begin_x is not None:
            x = self.begin_x + ((self.width or 0.0) / 2)
            y = (self.begin_y or 0.0) + ((self.height or 0.0) / 2)
        else:
            x = self.x
            y = self.y
        return x, y

    def set_start_and_finish(
        self, start: tuple[float | None, float | None], finish: tuple[float | None, float | None]
    ) -> None:
        # set start and finish of a simple line or connector
        if self.begin_x is not None:  # only apply changes to lines and connector shapes
            start_x, start_y = start
            finish_x, finish_y = finish
            if start_x is None or start_y is None or finish_x is None or finish_y is None:
                raise ValueError("connector start and finish coordinates cannot be None")
            self.x, self.y = start_x, start_y
            # lines/connectors are defined in different ways
            # Check whether shape is a connector based on name in known languages
            is_connector = self.universal_name == "Dynamic connector"

            self.begin_x, self.begin_y = start_x, start_y
            self.end_x, self.end_y = finish_x, finish_y
            width = finish_x - start_x
            height = finish_y - start_y if is_connector else 0.0
            self.width = width
            self.height = height
            self.x, self.y = start_x, start_y
            if self.geometry is not None:
                self.geometry.set_move_to(0.0, 0.0)
                self.geometry.set_line_to(width, height)
            txt_pin_x = self.cells.get("TxtPinX")
            txt_pin_y = self.cells.get("TxtPinY")
            if txt_pin_x and txt_pin_y:
                if is_connector:
                    text_x = width / 2
                    text_y = height / 2
                else:
                    text_x, text_y = self.center_x_y
                    if text_x is None or text_y is None:
                        raise ValueError("shape text coordinates cannot be None")
                txt_pin_x.value = text_x
                txt_pin_y.value = text_y
                self.set_cell_value(name="Control/TextPosition/X", value=text_x)
                self.set_cell_value(name="Control/TextPosition/Y", value=text_y)
                self.set_cell_value(name="Control/TextPosition/XDyn", value=text_x)
                self.set_cell_value(name="Control/TextPosition/YDyn", value=text_y)
                # print(cp1.cells.keys())
            cells: list[Cell | vsdx.GeometryCell] = list(self.cells.values())
            if self.geometry is not None:
                cells.extend(self.geometry.cells)
                for r in self.geometry.rows.values():
                    cells.extend(r.cells.values())
            # print(cells)
            for c in cells:  # type: Cell
                v = None
                formula = c.formula
                if formula and c.name is not None:
                    master = self.master_shape
                    if formula == "Inh" and master is not None:
                        master_c = master.cells.get(c.name)
                        formula = master_c.formula if master_c else formula
                    if formula is None:
                        continue
                    v = vsdx.calc_value(self, formula)
                    if v is not None:
                        c.value = v

    @property
    def text_raw(self) -> str:
        # return contents of Text element, or Master shape (if referenced), or empty string
        text_element = self.xml.find(f"{namespace}Text")

        if isinstance(text_element, Element):
            return (text_element.text or "") + "".join(html.unescape(ET.tostring(e, encoding="unicode")) for e in text_element)
        elif self.master_page_ID:
            master = self.master_shape
            if master is not None and master.text:
                return master.text  # get text from master shape
        return ""

    def _text_runs(self) -> tuple[list[Element], str, list[Element], str]:
        """Split the shape's text into leading runs, content, trailing runs and trailing newlines.

        The leading and trailing runs are the Text element's own child
        elements, not copies, so a caller may re-append them after clearing it.
        Visio ends a Text element with a newline that is not part of the text;
        it is reported separately so that setting the text puts it back.
        """
        text_element = self.xml.find(f"{namespace}Text")
        if not isinstance(text_element, Element):
            # A shape with no Text element of its own shows its master's text,
            # and inherits none of the master's formatting runs.
            if self.master_page_ID:
                master = self.master_shape
                if master is not None and master.text:
                    return [], master.text, [], ""
            return [], "", [], ""

        children = list(text_element)
        start = 0
        if not text_element.text:
            while start < len(children) and _is_formatting_run(children[start]):
                start += 1
                if children[start - 1].tail:
                    break  # this run's trailing text is where the content starts

        end = len(children)
        while end > start:
            candidate = children[end - 1]
            tail = candidate.tail or ""
            if not _is_formatting_run(candidate):
                break
            # only whitespace may follow the final run; nothing at all may sit
            # between two runs, or the text before it belongs to the content
            if tail.strip() if end == len(children) else tail:
                break
            end -= 1

        leading = (text_element.text if start == 0 else children[start - 1].tail) or ""
        content = leading + "".join(html.unescape(ET.tostring(child, encoding="unicode")) for child in children[start:end])
        suffix = children[end:]
        trailing = ""
        if not suffix:
            # nothing follows the content, so a newline at its end is Visio's
            # terminator rather than text; a trailing run keeps its own tail
            stripped = content.rstrip("\n")
            content, trailing = stripped, content[len(stripped) :]
        return children[:start], content, suffix, trailing

    @property
    def text(self) -> str:
        return self._text_runs()[1]

    @text.setter
    def text(self, value: str) -> None:
        prefix, _, suffix, trailing = self._text_runs()
        value += trailing
        tag = f"{namespace}Text"
        text_element = self.xml.find(tag)
        if not isinstance(text_element, Element):  # create Text element if not found
            text_element = Element(tag)
            self.xml.append(text_element)
        attrib = dict(text_element.attrib)  # e.g. xml:space="preserve"
        text_element.clear()
        text_element.attrib.update(attrib)
        for run in prefix:
            run.tail = None
            text_element.append(run)
        if prefix:
            prefix[-1].tail = value
        else:
            text_element.text = value
        for run in suffix:
            text_element.append(run)

    @deprecation.deprecated(
        deprecated_in="0.5.0",
        removed_in="1.0.0",
        current_version=vsdx.__version__,
        details="Use Shape.child_shapes property to access shapes within a shape",
    )
    def sub_shapes(self) -> list[Shape]:
        return self.child_shapes

    @property
    def child_shapes(self) -> list[Shape]:
        """Get child/sub shapes contained by a Shape

        :returns: list of Shape objects
        :rtype: List[Shape]
        """
        shapes = list()
        # for each shapes tag, look for Shape objects
        # self can be either a Shapes or a Shape
        # a Shapes has a list of Shape
        # a Shape can have 0 or 1 Shapes (1 if type is Group)

        parent_element = self.xml.find(f"{namespace}Shapes") if self.shape_type == "Group" else self.xml

        shapes: list[Shape] = []
        if isinstance(parent_element, Element):
            shapes = [Shape(xml=shape, parent=self, page=self.page) for shape in parent_element.findall(f"{namespace}Shape")]

        return shapes

    @property
    def all_shapes(self) -> list[Shape]:
        # return all shapes within another shape, recursively
        return self._all_shapes()

    def _all_shapes(self, shapes: list[Shape] | None = None) -> list[Shape]:
        # recursively search for shapes and return all found
        if not shapes:
            shapes = list()
        for shape in self.child_shapes:  # type: Shape
            shapes.append(shape)
            if shape.shape_type == "Group":
                found = shape.all_shapes
                if found:
                    shapes.extend(found)
        return shapes

    def get_max_id(self) -> int:
        max_id = int(self.ID) if self.ID is not None else 0
        if self.shape_type == "Group":
            for shape in self.child_shapes:
                new_max = shape.get_max_id()
                if new_max > max_id:
                    max_id = new_max
        return max_id

    def find_shape_by_id(self, shape_id: str) -> Shape | None:  # returns Shape or None
        """
        Recursively search for a shape, based on a known shape_id, and return a single Shape

        :param shape_id:
        :return: vsdx.Shape
        """
        # recursively search for shapes by text and return first match
        for shape in self.all_shapes:  # type: Shape
            if shape_id == shape.ID:
                return shape

    def find_shapes_by_id(self, shape_id: str) -> list[Shape]:
        # recursively search for shapes by ID and return all matches
        return [s for s in self.all_shapes if shape_id == s.ID]

    def find_shape_by_attr(self, attr: str, attr_value: str) -> Shape | None:  # returns Shape or None
        """
        Search for a shape, based on attribute name and value, and return a single Shape

        :param attr:
        :param attr_value:
        :return: vsdx.Shape
        """
        #  xml.attrib.get('NameU') or xml.get('Name')
        # recursively search for shapes by text and return first match
        for shape in self.all_shapes:  # type: Shape
            if str(shape.xml.attrib.get(attr)) == attr_value:
                return shape

    def find_shapes_by_master(self, master_page_ID: str, master_shape_ID: str) -> list[Shape]:
        # recursively search for shapes by master ID and return all matches
        return [s for s in self.all_shapes if s.master_shape_ID == master_shape_ID and s.master_page_ID == master_page_ID]

    def find_shape_by_text(self, text: str) -> Shape | None:  # returns Shape or None
        # recursively search for shapes by text and return first match
        for shape in self.all_shapes:  # type: Shape
            if text in shape.text:
                return shape

    def find_shapes_by_text(self, text: str) -> list[Shape]:
        # recursively search for shapes by text and return all matches
        return [s for s in self.all_shapes if text in s.text]

    def find_shapes_by_regex(self, regex: str) -> list[Shape]:
        # recursively search for shapes by regex and return all matches
        return [shape for shape in self.all_shapes if re.search(regex, shape.text)]

    def find_shape_by_property_label(self, property_label: str) -> Shape | None:  # returns Shape or None
        # recursively search for shapes by property name and return first match
        for shape in self.all_shapes:  # type: Shape
            if property_label in shape.data_properties:
                return shape

    def find_shapes_by_property_label(self, property_label: str, shapes: list[Shape] | None = None) -> list[Shape]:
        # recursively search for shapes by property label and return all matches
        return [s for s in self.all_shapes if property_label in s.data_properties]

    def find_shape_by_property_label_value(
        self, property_label: str, property_value: str
    ) -> Shape | None:  # returns Shape or None
        # recursively search for shapes by property label and value, and return first match
        for shape in self.all_shapes:  # type: Shape
            if property_label in shape.data_properties and str(shape.data_properties[property_label].value) == property_value:
                return shape

    def find_shapes_by_property_label_value(
        self, property_label: str, property_value: str, shapes: list[Shape] | None = None
    ) -> list[Shape]:
        # recursively search for shapes by property label and return all matches
        return [
            s
            for s in self.all_shapes
            if property_label in s.data_properties and str(s.data_properties[property_label].value) == property_value
        ]

    def apply_text_filter(self, context: dict[str, object]) -> None:
        # check text against all context keys
        text = self.text
        for key in context:
            r_key = "{{" + key + "}}"
            text = text.replace(r_key, str(context[key]))
        self.text = text

        for s in self.child_shapes:
            s.apply_text_filter(context)

    def find_replace(self, old: str, new: str) -> None:
        # find and replace text in this shape and sub shapes
        text = self.text
        self.text = text.replace(old, new)

        for s in self.child_shapes:
            s.find_replace(old, new)

    def remove(self) -> None:
        """Remove this shape from its page or group.

        Deprecated in favour of :meth:`Page.delete_shape`, which this now calls:
        it is the single path that also deletes the connectors glued to the
        shape and their ``Connect`` records. Detaching the element alone left
        orphan connectors and dangling records behind, and Visio repairs such a
        package on open. It also raised ``ValueError`` for a shape inside a
        group, whose XML is held by the group's ``Shapes`` container rather than
        by the group element the parent Shape wraps.
        """
        # Not `@deprecation.deprecated`: that decorator is version-gated and
        # would stay silent until __version__ reaches the release this landed
        # in, so nothing would warn during the cycle the replacement is in.
        warnings.warn(
            "Shape.remove() is deprecated and will be removed in 1.0.0. Use Page.delete_shape(shape), "
            "which also removes the connectors glued to the shape and their Connect records.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.page.delete_shape(self)

    def append_shape(self, append_shape: Shape) -> None:
        # insert shape into shapes tag, and return updated shapes tag
        id_map = self.page.vis.increment_shape_ids(append_shape.xml, self.page)
        self.page.vis.update_ids(append_shape.xml, id_map)
        self.xml.append(append_shape.xml)

    @property
    def connects(self) -> list[Connect]:
        """Connect items linking this shape to others.

        The annotation quotes ``Connect`` so ``typing.get_type_hints`` stays
        runtime-resolvable while avoiding an import cycle with
        ``vsdx.connectors`` (resolved lazily by the type checker).
        """
        connects = list()
        for c in self.page.connects:
            if self.ID in [c.shape_id, c.connector_shape_id]:
                connects.append(c)
        return connects

    @property
    def connected_shapes(self) -> list[Shape]:
        """Shapes at the far end of this shape's connector records.

        Connect records can reference a shape that is not on this page (for
        example a connector record left behind by a deleted shape), so lookups
        that resolve to nothing are skipped rather than held as None.
        """
        shapes: list[Shape] = []
        for c in self.connects:
            if c.connector_shape_id != self.ID:
                found = self.page.find_shape_by_id(c.connector_shape_id or "")
                if found is not None:
                    shapes.append(found)
            if c.shape_id != self.ID:
                found = self.page.find_shape_by_id(c.shape_id or "")
                if found is not None:
                    shapes.append(found)
        return shapes
