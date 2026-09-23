"""Convert a bioformats2raw HCS plate to RFC-8 and validate it.

This copies the metadata from the dataset into a new folder (_rfc8_conversion by default)
and converts it to RFC-8 extensions and collections. The metadata/folder hierarchy
is preserved when copying. After the conversion, the collections metadata
is validated by ngio-collections.

See the README.md file for how to get the example dataset.

Convert the reference plate and check it:

    uv run examples/bf_hcs/hcs_rfc8_conversion.py

Re-run over an existing result:

    uv run examples/bf_hcs/hcs_rfc8_conversion.py --force

Check a different fileset:

    uv run examples/bf_hcs/hcs_rfc8_conversion.py --source path/to/plate.ome.zarr \
        --dest /tmp/plate-check --force
"""

import argparse
import filecmp
import json
import pathlib
import shutil
import sys
import warnings
from typing import Any

import ngio_collections as ngc

_SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rfc8_playground.core_metadata import (
    RFC8Collection,
    RFC8Multiscale,
    RFC8Node,
    RFC8Singlescale,
    read_document,
)
from rfc8_playground.hcs import (
    OME_GROUP_NAME,
    XML_FILENAME,
    HCSDataset,
    OmeGroup,
)

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE / "NIRHTa+001.ome.zarr"
DEFAULT_DEST = HERE / "_rfc8_conversion" / "NIRHTa+001.ome.zarr"

#: Written into the mirror so --force can tell a mirror from real data.
MARKER = ".rfc8-check"


class Report:
    """Collects check results so every check runs before anything is reported."""

    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[str] = []
        self.skipped: list[str] = []

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        if ok:
            self.passed.append(label)
        else:
            self.failed.append(f"{label}{f': {detail}' if detail else ''}")
        return ok

    def skip(self, label: str, reason: str) -> None:
        """Record a check that could not run, which is neither a pass nor a fail."""
        self.skipped.append(f"{label}: {reason}")

    def print(self) -> bool:
        for label in self.passed:
            print(f"  ok    {label}")
        for label in self.skipped:
            print(f"  skip  {label}")
        for label in self.failed:
            print(f"  FAIL  {label}")
        print()
        if self.failed:
            print(
                f"{len(self.failed)} of {len(self.passed) + len(self.failed)} checks failed"
            )
            return False
        suffix = f", {len(self.skipped)} skipped" if self.skipped else ""
        print(f"all {len(self.passed)} checks passed{suffix}")
        return True


def document_path(dest: pathlib.Path, relpath: str) -> pathlib.Path:
    """The zarr.json holding the document at a plate-relative path."""
    return (dest / relpath / "zarr.json") if relpath else dest / "zarr.json"


def mirror_metadata(source: pathlib.Path, dest: pathlib.Path, *, force: bool) -> int:
    """Copy every zarr.json and the OME-XML into a fresh tree at dest."""
    if dest.exists():
        if not force:
            raise SystemExit(
                f"{dest} already exists; pass --force to replace it, or --dest elsewhere"
            )
        if not (dest / MARKER).is_file():
            raise SystemExit(
                f"refusing to delete {dest}: it has no {MARKER} marker, so it was "
                "not created by this script"
            )
        shutil.rmtree(dest)

    count = 0
    for src_file in sorted(source.rglob("zarr.json")):
        dst_file = dest / src_file.relative_to(source)
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)
        count += 1

    xml = source / OME_GROUP_NAME / XML_FILENAME
    if xml.is_file():
        shutil.copy2(xml, dest / OME_GROUP_NAME / XML_FILENAME)

    (dest / MARKER).write_text(
        f"metadata-only mirror of {source}, written by {pathlib.Path(__file__).name}\n"
    )
    return count


def check_arrays_untouched(
    source: pathlib.Path,
    dest: pathlib.Path,
    documents: dict[str, RFC8Node],
    report: Report,
) -> None:
    """Every zarr.json the conversion does not claim must be byte-identical."""
    claimed = {document_path(dest, relpath) for relpath in documents}
    checked = differing = 0
    for dst_file in sorted(dest.rglob("zarr.json")):
        if dst_file in claimed:
            continue
        checked += 1
        src_file = source / dst_file.relative_to(dest)
        if not filecmp.cmp(src_file, dst_file, shallow=False):
            differing += 1

    report.check(
        differing == 0 and checked > 0,
        f"{checked} untouched zarr.json files are byte-identical to the source",
        f"{differing} differ" if differing else "none were found to check",
    )


def check_round_trip(
    dest: pathlib.Path, documents: dict[str, RFC8Node], report: Report
) -> None:
    """Every written document must load back through read_document."""
    failures = []
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # a dropped field is a failure, not a note
        for relpath in documents:
            try:
                read_document(document_path(dest, relpath))
            except Exception as exc:  # noqa: BLE001 - reported, not handled
                failures.append(f"{relpath or '<root>'}: {exc}")

    report.check(
        not failures,
        f"all {len(documents)} documents round-trip through read_document",
        "; ".join(failures[:3]),
    )


def check_legacy_keys_gone(
    dest: pathlib.Path, documents: dict[str, RFC8Node], report: Report
) -> None:
    """No v0.5 key may survive in a document the conversion rewrote."""
    legacy = ("multiscales", "well", "omero", "bioformats2raw.layout", "series")
    # ome:omexmlID and ome:omexml were drafted and dropped (design 5.1).
    dropped = ("ome:omexmlID", "ome:omexml")
    found = []
    for relpath in documents:
        ome = json.loads(document_path(dest, relpath).read_text())["attributes"]["ome"]
        found += [f"{relpath or '<root>'}.{key}" for key in legacy if key in ome]
        attributes = ome.get("attributes") or {}
        found += [
            f"{relpath or '<root>'}.attributes.{key}"
            for key in dropped
            if key in attributes
        ]

    report.check(
        not found,
        "no legacy 0.5 keys remain in rewritten documents",
        ", ".join(found[:5]),
    )


def check_ids(
    dest: pathlib.Path, documents: dict[str, RFC8Node], report: Report
) -> None:
    """IDs must be unique within each JSON document, and names within a collection."""
    duplicate_ids, duplicate_names = [], []

    def walk(node: RFC8Node, ids: list[str]) -> None:
        if node.id is not None:
            ids.append(node.id)
        # Coordinate system ids share the node id namespace.
        for system in (node.attributes or {}).get("coordinateSystems", []):
            ids.append(system["id"])

        children = getattr(node, "nodes", None) or []
        names = [child.name for child in children]
        if len(names) != len(set(names)):
            duplicate_names.append(f"{relpath or '<root>'} in {node.name}: {names}")
        for child in children:
            walk(child, ids)

    for relpath in documents:
        ids: list[str] = []
        walk(read_document(document_path(dest, relpath)), ids)
        if len(ids) != len(set(ids)):
            duplicate_ids.append(f"{relpath or '<root>'}: {ids}")

    report.check(
        not duplicate_ids,
        "ids are unique within every document",
        "; ".join(duplicate_ids[:3]),
    )
    report.check(
        not duplicate_names,
        "node names are unique within every collection",
        "; ".join(duplicate_names[:3]),
    )


def check_references(
    dest: pathlib.Path,
    model: HCSDataset,
    documents: dict[str, RFC8Node],
    report: Report,
) -> None:
    """Well and acquisition references must resolve against the plate document."""
    plate = documents[""].attributes["plate"]
    row_ids = {row["id"] for row in plate["rows"]}
    column_ids = {column["id"] for column in plate["columns"]}
    acquisition_ids = {
        acquisition["id"] for acquisition in plate.get("acquisitions", [])
    }

    unresolved, pathless = [], []

    def resolves_to_plate(relpath: str, reference: dict, label: str) -> None:
        if "path" not in reference:
            pathless.append(label)
            return
        target = (dest / relpath / reference["path"]["path"] / "zarr.json").resolve()
        if target != (dest / "zarr.json").resolve():
            unresolved.append(f"{label} path resolves to {target}")

    checked_acquisitions = 0
    for well in model.layout.wells:
        node = documents[well.path]
        for key, valid in (("row", row_ids), ("column", column_ids)):
            reference = node.attributes["well"][key]
            label = f"{well.path}.{key}"
            if reference["id"] not in valid:
                unresolved.append(f"{label}={reference['id']}")
            resolves_to_plate(well.path, reference, label)

        for image_node in node.nodes:
            reference = (image_node.attributes or {}).get("acquisition")
            if reference is None:
                continue
            checked_acquisitions += 1
            label = f"{well.path}/{image_node.name}.acquisition"
            if reference["id"] not in acquisition_ids:
                unresolved.append(f"{label}={reference['id']}")
            resolves_to_plate(well.path, reference, label)

    report.check(
        not unresolved,
        "well row/column and acquisition references resolve to the plate document",
        "; ".join(unresolved[:3]),
    )
    report.check(
        not pathless, "external references carry a path", "; ".join(pathless[:3])
    )
    report.check(
        checked_acquisitions == sum(1 for i in model.images if i.acquisition_id),
        f"every image with an acquisition carries a reference "
        f"({checked_acquisitions} of {len(model.images)} images)",
    )


def check_series_linkage(
    model: HCSDataset, documents: dict[str, RFC8Node], report: Report
) -> None:
    """The Bio-Formats series order must survive as ``ome:series``.

    It is the only thing tying an image group to an ``<Image>`` element of the
    OME-XML, and the design deliberately keeps that correspondence positional
    rather than writing a per-node id.
    """
    if model.ome_group is None:
        report.check(
            all(image.series is None for image in model.images),
            "a fileset with no OME group leaves every image without a series",
        )
        report.check(
            OME_GROUP_NAME not in documents,
            "a fileset with no OME group gets no ome:omeGroup document",
        )
        return

    series = documents[model.ome_group.path].attributes["ome:series"]
    paths = [entry.removeprefix("../") for entry in series]

    report.check(
        all(entry.startswith("../") for entry in series),
        "ome:series entries are relative to the OME group document",
        f"{sum(1 for e in series if not e.startswith('../'))} are not",
    )
    report.check(
        paths == model.ome_group.series.paths,
        f"ome:series preserves the declared order of {len(paths)} entries",
    )
    report.check(
        len(set(paths)) == len(paths),
        "ome:series entries are unique",
        f"{len(paths) - len(set(paths))} repeat",
    )

    image_paths = {image.path for image in model.images}
    unnamed = sorted(image_paths - set(paths))
    report.check(
        not unnamed,
        f"all {len(image_paths)} images are named by ome:series",
        f"{len(unnamed)} are not, e.g. {unnamed[:2]}",
    )

    mismatched = [
        image.path
        for image in model.images
        if image.series is not None and paths[image.series] != image.path
    ]
    report.check(
        not mismatched,
        "each image's series number indexes its own ome:series entry",
        f"{len(mismatched)} do not, e.g. {mismatched[:2]}",
    )

    # The design keeps the correspondence positional; no node may carry an id.
    with_ids = [
        relpath
        for relpath, node in documents.items()
        if "ome:omexmlID" in (node.attributes or {})
    ]
    report.check(
        not with_ids,
        "no node carries an ome:omexmlID, which the design dropped",
        f"{len(with_ids)} do, e.g. {with_ids[:2]}",
    )


def check_structure(
    model: HCSDataset, documents: dict[str, RFC8Node], report: Report
) -> None:
    """Node types and counts must match the design's layout."""
    root = documents[""]
    well_paths = [well.path for well in model.layout.wells]
    image_paths = [image.path for image in model.images]

    report.check(isinstance(root, RFC8Collection), "the root node is a collection")
    report.check(root.version is not None, "the root node carries a version")
    report.check(
        all(node.version is None for path, node in documents.items() if path),
        "no non-root document carries a version",
    )
    if model.ome_group is not None:
        report.check(
            isinstance(documents.get(OME_GROUP_NAME), OmeGroup),
            f"{OME_GROUP_NAME} is an ome:omeGroup node",
        )
    report.check(
        all(
            isinstance(level, RFC8Singlescale)
            for path in image_paths
            for level in documents[path].nodes
        ),
        "every image document holds singlescale nodes",
    )

    stub_types = [node.type for node in root.nodes]
    if model.ome_group is None:
        report.check(
            set(stub_types) == {"collection"},
            "the plate lists only well collections",
            f"got {sorted(set(stub_types))}",
        )
        report.check(
            len(root.nodes) == len(well_paths),
            f"the plate lists all {len(well_paths)} wells",
            f"got {len(root.nodes)} nodes",
        )
    else:
        report.check(
            stub_types[0] == "ome:omeGroup" and set(stub_types[1:]) == {"collection"},
            "the plate lists the OME group first, then well collections",
            f"got {sorted(set(stub_types))}",
        )
        report.check(
            len(root.nodes) == len(well_paths) + 1,
            f"the plate lists all {len(well_paths)} wells plus the OME group",
            f"got {len(root.nodes)} nodes",
        )
    report.check(
        all(
            isinstance(node, RFC8Multiscale) for node in documents[well_paths[0]].nodes
        ),
        "well collections hold multiscale nodes",
    )


def check_missing_keys(
    documents: dict[str, RFC8Node], report: Report, *, include_missing: bool
) -> None:
    """Layer D keys must be present when asked for, and absent when not."""
    prefixes = ("missingPlate:", "missingPlateAcquisitions:", "missingMultiscales:")

    def keys_of(node: RFC8Node) -> list[str]:
        found = [k for k in (node.attributes or {}) if k.startswith(prefixes)]
        for acquisition in (
            (node.attributes or {}).get("plate", {}).get("acquisitions", [])
        ):
            found += [k for k in acquisition if k.startswith(prefixes)]
        return found

    present = sum(len(keys_of(node)) for node in documents.values())
    if include_missing:
        report.check(present > 0, f"{present} missing* keys are written")
    else:
        report.check(present == 0, "no missing* keys are written", f"{present} found")


# ----------------------------------------------------------------------
# cross-validation against ngio-collections
# ----------------------------------------------------------------------


class NgioOmeGroup(ngc.Node):
    """ngio's handle for the ``ome:omeGroup`` node extension.

    The mirror image of registering ``OmeGroup`` in ``NODE_CLASSES``: a
    second implementation being taught the same node type. It adds no
    fields, because the extension's data lives in the open ``attributes``
    dict -- which is what lets an implementation that never registers the
    type read the documents anyway.
    """


def ngio_singlescale_input_is_self(node: "ngc.Node") -> None:
    """RFC-8: a singlescale's transformation ``input`` names the node itself.

    Neither ngio's built-in validators nor the checks above assert this, so it
    is contributed here in ngio's own validator style: a plain callable that
    raises on a problem and returns otherwise.
    """
    if node.type != "singlescale":
        return
    for transform in node.attributes.get("coordinateTransformations") or []:
        inner = transform.get("transformations", [transform])
        for part in inner:
            input_id = (part.get("input") or {}).get("id")
            if input_id is not None and input_id != node.id:
                raise ngc.ValidationError(
                    f"singlescale transformation input {input_id!r} does not "
                    f"name its own node id {node.id!r}"
                )


def ngio_multiscale_has_coordinate_systems(node: "ngc.Node") -> None:
    """RFC-8: a multiscale's attributes MUST contain ``coordinateSystems``."""
    if node.type != "multiscale":
        return
    if not node.attributes.get("coordinateSystems"):
        raise ngc.ValidationError("a multiscale node must define coordinateSystems")


def check_ngio(
    dest: pathlib.Path,
    model: HCSDataset,
    documents: dict[str, RFC8Node],
    report: Report,
) -> None:
    """Load the converted fileset with ngio-collections and cross-check it."""
    if ngc is None:
        report.skip(
            "ngio-collections cross-validation",
            "ngio_collections is not importable",
        )
        return

    ngc.register_node_type("ome:omeGroup", NgioOmeGroup)

    # on_error="skip" leaves an unresolvable stub in place rather than raising.
    # That would mask a broken path, so the structure check below asserts
    # exactly which stubs are allowed to stay unresolved.
    root = ngc.open_inlined(str(dest), on_error="skip")
    nodes = list(root.walk())

    check_ngio_structure(model, documents, root, nodes, report)
    check_ngio_attributes(model, root, nodes, report)
    check_ngio_validators(root, report)
    check_ngio_extension(model, root, nodes, report)


def check_ngio_structure(
    model: HCSDataset,
    documents: dict[str, RFC8Node],
    root: "ngc.Node",
    nodes: list["ngc.Node"],
    report: Report,
) -> None:
    """ngio must rebuild the same tree, by following the paths we wrote."""
    counts: dict[str, int] = {}
    for node in nodes:
        counts[node.type] = counts.get(node.type, 0) + 1

    levels = sum(len(documents[image.path].nodes or []) for image in model.images)
    expected = {
        "collection": 1 + len(model.layout.wells),
        "multiscale": len(model.images),
        "singlescale": levels,
    }
    if model.ome_group is not None:
        expected["ome:omeGroup"] = 1

    report.check(
        counts == expected,
        f"ngio resolves the plate into the same {sum(expected.values())} nodes",
        f"got {counts}, expected {expected}",
    )
    report.check(
        isinstance(root, ngc.CollectionNode),
        "ngio types the root node as a collection",
        f"got {type(root).__name__}",
    )

    # A stub stays unresolved when its target is not an OME document or its
    # type disagrees with the target's. Singlescales are expected to stay:
    # their path points at the Zarr array, which carries no ome key. Anything
    # else unresolved is a path this conversion got wrong.
    unresolved = {node.type for node in nodes if node.is_reference}
    report.check(
        unresolved <= {"singlescale"},
        "only singlescale nodes are left unresolved by ngio",
        f"also unresolved: {sorted(unresolved - {'singlescale'})}",
    )


def check_ngio_attributes(
    model: HCSDataset, root: "ngc.Node", nodes: list["ngc.Node"], report: Report
) -> None:
    """The attributes we wrote must parse against ngio's pydantic models.

    This is the check the suite could not make on its own: ``core_metadata``
    builds attributes as plain dicts and never validates them. ngio models
    them, so ``plate``, ``well`` and ``acquisition`` are parsed against an
    independent reading of RFC-8 -- including the ``[a-zA-Z0-9-_.]+`` id
    pattern, which nothing else here enforces.
    """
    failures: list[str] = []

    def parse(node: "ngc.Node", attribute: type, label: str) -> Any:
        try:
            return node[attribute]
        except Exception as exc:  # noqa: BLE001 - reported, not handled
            failures.append(f"{label}: {exc}")
            return None

    plate = parse(root, ngc.PlateAttribute, "plate")
    if plate is not None:
        report.check(
            {row.id for row in plate.rows} == {str(r.id) for r in model.layout.rows}
            and {col.id for col in plate.columns}
            == {str(c.id) for c in model.layout.columns}
            and {acq.id for acq in plate.acquisitions}
            == {str(a.id) for a in model.acquisitions},
            "ngio parses plate rows, columns and acquisitions with matching ids",
        )

    wells = {str(well.id): well for well in model.layout.wells}
    mismatched, seen = [], 0
    for node in nodes:
        if not node.has(ngc.WellAttribute):
            continue
        seen += 1
        attrs = parse(node, ngc.WellAttribute, f"well {node.name}")
        well = wells.get(node.id or "")
        if attrs is None or well is None:
            continue
        if attrs.row.id != str(well.row_id) or attrs.column.id != str(well.column_id):
            mismatched.append(node.name)

    report.check(
        seen == len(model.layout.wells) and not mismatched,
        f"ngio parses all {len(model.layout.wells)} well attributes with "
        "matching row and column references",
        f"{seen} seen, {len(mismatched)} mismatched e.g. {mismatched[:2]}",
    )

    # Acquisition references ride on the well's multiscale stubs and survive
    # inlining, because a stub's own attributes win over the target's.
    expected_acquisitions = sum(1 for image in model.images if image.acquisition_id)
    with_acquisition = [node for node in nodes if node.has(ngc.AcquisitionAttribute)]
    for node in with_acquisition:
        parse(node, ngc.AcquisitionAttribute, f"acquisition on {node.name}")
    report.check(
        len(with_acquisition) == expected_acquisitions,
        f"ngio sees the acquisition reference on all {expected_acquisitions} "
        "images that carry one",
        f"got {len(with_acquisition)}",
    )

    for node in nodes:
        if node.type == "multiscale":
            parse(node, ngc.CoordinateSystemsAttribute, f"cs on {node.name}")
        elif node.type == "singlescale":
            parse(node, ngc.CoordinateTransformationsAttribute, f"ct on {node.name}")

    report.check(
        not failures,
        "every attribute parses against ngio's RFC-8 models",
        "; ".join(failures[:3]),
    )


def check_ngio_validators(root: "ngc.Node", report: Report) -> None:
    """ngio's built-in validators, plus two contributed here, must all pass.

    ``scale_matches_axes`` is the one that earns its keep: it follows the
    transformation's output reference to the coordinate system on the parent
    multiscale and compares the axis count to the scale factor count, checking
    the conversion in ``_convert_transform`` against metadata that was minted
    in an entirely different part of the pipeline.
    """
    validators = (
        ngc.well_under_plate,
        ngc.scale_matches_axes,
        ngio_singlescale_input_is_self,
        ngio_multiscale_has_coordinate_systems,
    )
    errors = ngc.validate(root, validators)
    report.check(
        not errors,
        f"all {len(validators)} ngio validators pass over the whole plate",
        "; ".join(f"{e.validator}: {e}" for e in errors[:3]),
    )


def check_ngio_extension(
    model: HCSDataset, root: "ngc.Node", nodes: list["ngc.Node"], report: Report
) -> None:
    """The node and attribute extensions must survive a foreign implementation."""
    if model.ome_group is None:
        report.check(
            not [node for node in nodes if isinstance(node, NgioOmeGroup)],
            "a fileset with no OME group gives ngio no ome:omeGroup node",
        )
        return

    groups = [node for node in nodes if isinstance(node, NgioOmeGroup)]
    if not report.check(
        len(groups) == 1,
        "ngio wraps the OME group in the registered ome:omeGroup handle",
        f"got {len(groups)}",
    ):
        return

    group = groups[0]
    series = group.attributes.get("ome:series") or []
    report.check(
        list(series) == [f"../{p}" for p in model.ome_group.series.paths],
        f"ngio round-trips all {len(series)} ome:series entries untouched",
    )

    # ome:series entries are plain strings, not Path objects, so ngio does not
    # resolve them itself (README open question 3). Resolving them through its
    # path model is what shows the strings would work as Paths.
    image_documents = {node.document_url for node in nodes if node.type == "multiscale"}
    unresolved = [
        entry
        for entry in series
        if f"{ngc.ZarrPath(path=entry).resolve(group.document_url)}/zarr.json"
        not in image_documents
    ]
    report.check(
        not unresolved,
        "every ome:series entry resolves to a multiscale document under ngio's "
        "path model",
        f"{len(unresolved)} do not, e.g. {unresolved[:2]}",
    )

    report.check(
        root.attributes.get("bf2raw:layout") == model.bf2raw_layout,
        f"ngio reads bf2raw:layout back as {model.bf2raw_layout!r}",
        f"got {root.attributes.get('bf2raw:layout')!r}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source",
        type=pathlib.Path,
        default=DEFAULT_SOURCE,
        help=f"the 0.5 fileset to convert (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--dest",
        type=pathlib.Path,
        default=DEFAULT_DEST,
        help=f"where to write the mirror (default: {DEFAULT_DEST})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing mirror written by this script",
    )
    args = parser.parse_args()

    source = args.source.resolve()
    dest = args.dest.resolve()
    if not (source / "zarr.json").is_file():
        raise SystemExit(f"no zarr.json at {source}")

    print(f"source  {source}")
    print(f"mirror  {dest}")

    copied = mirror_metadata(source, dest, force=args.force)
    print(f"copied  {copied} zarr.json documents plus the OME-XML\n")

    include_missing = True
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = HCSDataset.from_bf2raw_0_5(dest)
        documents = model.rfc8_documents(include_missing=include_missing)
        model.convert_to_rfc8(include_missing=include_missing)

    print(f"model   {model!r}")
    print(
        f"        {len(model.acquisitions)} acquisitions, "
        f"field count {model.field_count}, {len(documents)} documents"
    )
    if caught:
        print(f"        {len(caught)} warning(s) during conversion:")
        for warning in caught[:5]:
            print(f"          {warning.category.__name__}: {warning.message}")
    print()

    report = Report()
    check_structure(model, documents, report)
    check_round_trip(dest, documents, report)
    check_arrays_untouched(source, dest, documents, report)
    check_legacy_keys_gone(dest, documents, report)
    check_ids(dest, documents, report)
    check_references(dest, model, documents, report)
    check_series_linkage(model, documents, report)
    check_missing_keys(documents, report, include_missing=include_missing)
    check_ngio(dest, model, documents, report)

    return 0 if report.print() else 1


if __name__ == "__main__":
    sys.exit(main())
