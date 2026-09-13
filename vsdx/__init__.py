"""vsdxkit - create, edit and analyse Microsoft Visio .vsdx files.

The distribution installs as ``vsdxkit``; the import namespace stays ``vsdx``
so code written against the library this one descends from keeps working.
"""

import xml.dom.minidom as minidom  # minidom used for prettyprint
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element

namespace = "{http://schemas.microsoft.com/office/visio/2012/main}"  # visio file name space
ext_prop_namespace = "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}"
vt_namespace = "{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}"
r_namespace = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
document_rels_namespace = "{http://schemas.openxmlformats.org/package/2006/relationships}"
cont_types_namespace = "{http://schemas.openxmlformats.org/package/2006/content-types}"

# Ref: https://docs.microsoft.com/en-us/office/client-developer/visio/visio-file-format-reference


def pretty_print_element(xml: Element | ET.ElementTree) -> str:
    if isinstance(xml, ET.ElementTree):
        root = xml.getroot()
        return minidom.parseString(ET.tostring(root) if root is not None else b"").toprettyxml()
    return minidom.parseString(ET.tostring(xml)).toprettyxml()


# The one place the version lives. pyproject.toml reads it through
# tool.setuptools.dynamic, so a static [project].version would go stale in
# uv.lock on every bump and fail the `uv sync --locked` gate. release-please
# rewrites the line below; the annotation is how it finds it.
__version__ = "0.8.0"  # x-release-please-version

# Issue #250/#254 review: `Shape.connects` quotes `Connect` in its annotation,
# and `typing.get_type_hints` evaluates quoted names against the function's
# module __dict__ (module __getattr__ is not consulted). Inject the real class
# here, once both modules are fully initialised, so runtime introspection works.
from . import shapes as _shapes_module  # noqa: E402
from .connectors import Connect  # noqa: E402
from .containers import Container  # noqa: E402
from .formulae import calc_value  # noqa: E402
from .geometry import Geometry, GeometryCell, GeometryRow  # noqa: E402
from .logging_support import attach_debug_stream_handler, get_logger  # noqa: E402
from .media import Media  # noqa: E402
from .pages import Page, PagePosition  # noqa: E402
from .shapes import Cell, DataProperty, Shape  # noqa: E402
from .vsdxfile import PackageLimitError, PackageLimits, VisioFile, VisioFileNotOpen  # noqa: E402

_shapes_module.Connect = Connect

__all__ = [
    "Cell",
    "Connect",
    "Container",
    "DataProperty",
    "Geometry",
    "GeometryCell",
    "GeometryRow",
    "Media",
    "PackageLimitError",
    "PackageLimits",
    "Page",
    "PagePosition",
    "Shape",
    "VisioFile",
    "VisioFileNotOpen",
    "attach_debug_stream_handler",
    "calc_value",
    "get_logger",
]
