"""Metadata models for NGFF v0.6rc0 with RFC-8.

There is no validation. This is not a complete implementation
of RFC-8.
"""

import json
import os
import warnings
from dataclasses import dataclass, fields
from typing import Any


@dataclass(kw_only=True)
class Path:
    """A reference to a node stored elsewhere.

    Attributes
    ----------
    type : str
        How the path should be interpreted.
        The RFC defines ``"zarr"`` and ``"json"``. Extensions may add
        prefixed types, e.g. ``"myorg:s3"``.
    path : str
        The path itself. May be relative (``./image.ome.zarr``), an
        absolute file URL, or an HTTP(S) URL.
    """

    type: str
    path: str


@dataclass(kw_only=True)
class Node:
    """The base Node type.

    This class is also used as the fallback for node types this module does
    not model. The fields specific to those types are dropped on load.

    Attributes
    ----------
    version : str or None
        The version of the specification.
        Only a Node used as the root object of the ``ome`` key has a version.
        Non-root Nodes SHOULD NOT have one, which is not enforced here.
    type : str
        The type of the node.
        Value MUST be a string identifying the node type.
    name : str
        The human-readable name of the node.
        Value MUST be a non-empty string intended for human-readable display.
        Names MUST be unique within the enclosing collection.
    id : str or None
        The id of the node.
        Value MUST be a string that matches [a-zA-Z0-9-_.]+.
        IDs MUST be unique within the JSON document.
    attributes : dict or None
        The metadata for the node.
        A primary use case for the attributes field is the specialization
        of collections and nodes through additional metadata.
    """

    version: str | None = None
    type: str
    name: str
    id: str | None = None
    attributes: dict[str, Any] | None = None


@dataclass(kw_only=True)
class Singlescale(Node):
    """One resolution level of an OME-Zarr multiscale image.

    Attributes
    ----------
    type : str
        The type of the node.
        Value MUST be a string identifying the node type.
    name : str
        The human-readable name of the node.
        Value MUST be a non-empty string intended for human-readable display.
        Names MUST be unique within the enclosing collection.
    id : str or None
        The id of the node.
        Value MUST be a string that matches [a-zA-Z0-9-_.]+.
        IDs MUST be unique within the JSON document.
    attributes : dict or None
        The metadata for the node.
        A primary use case for the attributes field is the specialization
        of collections and nodes through additional metadata.
    path : Path or None
        Where the array for this resolution level is stored.
    """

    type: str = "singlescale"
    path: Path | None = None


@dataclass(kw_only=True)
class Multiscale(Node):
    """An OME-Zarr multiscale image.

    The RFC requires exactly one of ``nodes`` or ``path``, but does not
    require it here. See the module docstring.

    Attributes
    ----------
    type : str
        The type of the node.
        Value MUST be a string identifying the node type.
    name : str
        The human-readable name of the node.
        Value MUST be a non-empty string intended for human-readable display.
        Names MUST be unique within the enclosing collection.
    id : str or None
        The id of the node.
        Value MUST be a string that matches [a-zA-Z0-9-_.]+.
        IDs MUST be unique within the JSON document.
    attributes : dict or None
        The metadata for the node.
        A primary use case for the attributes field is the specialization
        of collections and nodes through additional metadata.
    nodes : list of Singlescale or None
        The inlined resolution levels of the image.
    path : Path or None
        Where the multiscale metadata is stored, when it is not inlined.
    """

    type: str = "multiscale"
    nodes: list[Singlescale] | None = None
    path: Path | None = None


@dataclass(kw_only=True)
class Collection(Node):
    """A grouping of one or more nodes.

    Collections may be nested.

    The RFC requires exactly one of ``nodes`` or ``path``, but does not
    require it here. See the module docstring.

    Attributes
    ----------
    type : str
        The type of the node.
        Value MUST be a string identifying the node type.
    name : str
        The human-readable name of the node.
        Value MUST be a non-empty string intended for human-readable display.
        Names MUST be unique within the enclosing collection.
    id : str or None
        The id of the node.
        Value MUST be a string that matches [a-zA-Z0-9-_.]+.
        IDs MUST be unique within the JSON document.
    attributes : dict or None
        The metadata for the node.
        A primary use case for the attributes field is the specialization
        of collections and nodes through additional metadata.
    nodes : list of Node or None
        The inlined nodes belonging to this collection.
    path : Path or None
        Where the collection metadata is stored, when it is not inlined.
    """

    type: str = "collection"
    nodes: list[Node] | None = None
    path: Path | None = None


NODE_CLASSES: dict[str, type[Node]] = {
    "collection": Collection,
    "multiscale": Multiscale,
    "singlescale": Singlescale,
}


def load_node(data: dict[str, Any]) -> Node:
    """Build a node from its JSON representation.

    Fields that the node class does not model are dropped with a warning.
    Node types that are not in ``NODE_CLASSES`` are loaded as the base
    ``Node``.

    Parameters
    ----------
    data : dict
        The JSON representation of the node.

    Returns
    -------
    Node
        The node dataclass.
    """
    try:
        node_type = data["type"]
    except KeyError:
        raise ValueError("node metadata is missing the required 'type' field") from None

    node_class = NODE_CLASSES.get(node_type, Node)

    field_names = {f.name for f in fields(node_class)}
    kwargs = {key: value for key, value in data.items() if key in field_names}

    dropped = sorted(key for key in data if key not in field_names)
    if dropped:
        warnings.warn(
            f"dropping unknown fields on {node_type!r} node "
            f"{data.get('name')!r}: {dropped}",
            stacklevel=2,
        )

    path = kwargs.get("path")
    if isinstance(path, dict):
        kwargs["path"] = Path(**path)

    child_nodes = kwargs.get("nodes")
    if isinstance(child_nodes, list):
        kwargs["nodes"] = [load_node(child) for child in child_nodes]

    return node_class(**kwargs)


def dump_node(node: Node) -> dict[str, Any]:
    """Convert a node to its JSON representation.

    Fields that are ``None`` are omitted.

    Parameters
    ----------
    node : Node
        The node to serialize.

    Returns
    -------
    dict[str, Any]
        The JSON representation of the node.
    """
    data: dict[str, Any] = {}
    for node_field in fields(node):
        value = getattr(node, node_field.name)
        if value is None:
            continue

        if isinstance(value, Path):
            value = {f.name: getattr(value, f.name) for f in fields(value)}
        elif node_field.name == "nodes":
            value = [dump_node(child) for child in value]

        data[node_field.name] = value

    return data


def load_ome(container: dict[str, Any]) -> Node:
    """Build the root node from the object that holds the ``ome`` key.

    For a standalone JSON document that object is the root of the file.
    For an OME-Zarr group or array it is the ``attributes`` object of the
    ``zarr.json``, so the Zarr metadata around it is never seen here.

    Metadata stored alongside the ``ome`` key is dropped with a warning.

    Parameters
    ----------
    container : dict
        The object holding the ``ome`` key.

    Returns
    -------
    Node
        The root node.
    """
    try:
        ome = container["ome"]
    except KeyError:
        raise ValueError("metadata is missing the required 'ome' key")

    return load_node(ome)


def dump_ome(node: Node) -> dict[str, Any]:
    """Convert a root node to the object that holds the ``ome`` key.

    Parameters
    ----------
    node : Node
        The root node to serialize.

    Returns
    -------
    dict[str, Any]
        An object with a single ``ome`` key.
    """
    return {"ome": dump_node(node)}


def _ome_container(data: dict[str, Any]) -> dict[str, Any]:
    """Find the object holding the ``ome`` key in a parsed JSON file."""
    attributes = data.get("attributes")
    if isinstance(attributes, dict) and "ome" in attributes:
        return attributes
    return data


def read_document(path: str | os.PathLike[str]) -> Node:
    """Read the root node from a JSON file.

    Both storage layouts are accepted: a standalone JSON file, where the
    ``ome`` key is at the root, and a ``zarr.json``, where it is under
    ``attributes``.

    Parameters
    ----------
    path : str or os.PathLike
        The file to read.

    Returns
    -------
    Node
        The root node.
    """
    with open(path) as f:
        data = json.load(f)

    return load_ome(_ome_container(data))


def write_document(
    node: Node,
    path: str | os.PathLike[str],
    container: str = "json",
) -> None:
    """Write a root node to a JSON file.

    With ``container="json"`` the file is written as a standalone JSON
    document, creating or overwriting it.

    With ``container="zarr"`` the file must be an existing ``zarr.json``,
    whose ``attributes.ome`` key is replaced. The rest of the file, including
    the Zarr metadata and any other attributes, is left as it was. Zarr
    containers are not created here because doing so would mean inventing
    Zarr metadata, such as the shape and data type of an array.

    Parameters
    ----------
    node : Node
        The root node to write.
    path : str or os.PathLike
        The file to write. With ``container="zarr"`` this is the path to the
        ``zarr.json`` itself, not to the group or array holding it.
    container : str
        Either ``"json"`` or ``"zarr"``.

    Raises
    ------
    FileNotFoundError
        If ``container="zarr"`` and the file does not exist.
    """
    if container == "json":
        data = dump_ome(node)
    elif container == "zarr":
        with open(path) as f:
            data = json.load(f)

        data.setdefault("attributes", {})["ome"] = dump_node(node)
    else:
        raise ValueError(f"container must be 'json' or 'zarr', got {container!r}")

    with open(path, "w") as f:
        json.dump(data, f, indent=2)
