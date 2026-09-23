"""A model of an HCS dataset and utilities to convert between OME-Zarr versions.

Currently this is designed to load from 0.5 HCS datasets and convert to the
metadata to the bioformats2raw RFC-8 extension.
"""

import json
import os
import pathlib
import uuid
import warnings
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import zarr
from ome_zarr_models.v05.hcs import HCS
from ome_zarr_models.v05.image import ImageAttrs as ImageAttrsV05
from ome_zarr_models.v05.well import WellAttrs
from ome_zarr_models.v06.image import ImageAttrs as ImageAttrsV06

from rfc8_playground.core_metadata import (
    NODE_CLASSES,
    RFC8Collection,
    RFC8Multiscale,
    RFC8Node,
    RFC8Path,
    RFC8Singlescale,
    write_document,
)

# I'm not sure how we should version this spec
VERSION = "0.9dev2"

#: The name of the group holding OME metadata, and of the XML document in it.
OME_GROUP_NAME = "OME"
XML_FILENAME = "METADATA.ome.xml"

#: The name given to the coordinate system minted for every image. It becomes
#: the RFC-8 ``name``; the ``id`` is a UUID derived from the image.
COORDINATE_SYSTEM_NAME = "physical"


@dataclass(kw_only=True)
class OmeGroup(RFC8Node):
    """The Zarr group holding OME metadata.

    This is an RFC-8 Node extension.

    Attributes
    ----------
    type : str
        The type of the node. Value MUST be "ome:omeGroup".
    name : str
        The human-readable name of the node.
    id : str | None
        The id of the node.
    attributes : dict or None
        The metadata for the node. Normally carries ``ome:series``.
    path : RFC8Path | None
        The path to the node from Collection containing the OmeGroup.
    """

    type: str = "ome:omeGroup"
    path: RFC8Path | None = None


# Registered as an import side effect so that read_document() builds an
# OmeGroup rather than falling back to the base Node.
# todo: add a registration function
NODE_CLASSES["ome:omeGroup"] = OmeGroup


@dataclass
class OmeSeries:
    """The Bio-Formats series order declared by the ``OME`` group.

    This is the only thing in a bioformats2raw fileset that ties an image
    group to an ``<Image>`` element of the OME-XML beside it. The
    correspondence is positional -- the nth path is the nth element -- and
    nothing in the fileset states it. That fragility is inherited from the
    source format rather than introduced by the conversion.

    Attributes
    ----------
    paths : list of str
        Plate-relative image paths, in Bio-Formats series order.
    """

    paths: list[str] = field(default_factory=list)

    @property
    def order(self) -> dict[str, int]:
        """Map each image path to its position in the series.

        Returns
        -------
        dict
            Plate-relative image path to series number. Empty if the group
            declares no series.
        """
        order: dict[str, int] = {}
        for index, path in enumerate(self.paths):
            order[path] = index
        return order


@dataclass
class GridCoordinate:
    """One row or one column of the plate grid.

    Attributes
    ----------
    id : UUID
        The identifier. Becomes the RFC-8 ``id``, which wells reference.
    name : str
        The label, e.g. ``"A"`` or ``"12"``. Also the directory segment.
    """

    id: UUID
    name: str


@dataclass
class Acquisition:
    """One acquisition round performed on the plate.

    Attributes
    ----------
    id : UUID
        The identifier. Becomes the RFC-8 ``id``, which images reference.
    name : str or None
        The human-readable name, if the source had one.
    source_id : int or None
        The v0.5 integer id. Kept so that the integer on a well image can be
        resolved to this acquisition, and not written out: RFC-8 requires a
        string id, and this model mints its own.
    extra : dict
        Source fields RFC-8 has no home for: ``maximumfieldcount``,
        ``description``, ``starttime`` and ``endtime``. Written under
        ``missingPlateAcquisitions:`` when ``include_missing`` is set.
    """

    id: UUID
    name: str | None = None
    source_id: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Well:
    """One well of the plate.

    Attributes
    ----------
    id : UUID
        The identifier. Becomes the RFC-8 ``id`` of the well collection.
    row_id : UUID
        The id of the row this well is in.
    column_id : UUID
        The id of the column this well is in.
    path : str
        The plate-relative path to the well group, e.g. ``"A/1"``.
    """

    id: UUID
    row_id: UUID
    column_id: UUID
    path: str


@dataclass
class HCSGridLayout:
    """The rows, columns and wells of a plate.

    The grid may be sparse.

    Attributes
    ----------
    rows : list[GridCoordinate]
        The rows, in plate order.
    columns : list[GridCoordinate]
        The columns, in plate order.
    wells : list[Well]
        The wells in the grid, in the order the source plate listed them.
        Unlike ``rows`` and ``columns``, whose positions are referenced by
        ``rowIndex`` and ``columnIndex``, nothing in the specification
        constrains this order: a well object carries its own position. It is
        row-major in bioformats2raw output, and is preserved rather than
        relied on.
    """

    rows: list[GridCoordinate] = field(default_factory=list)
    columns: list[GridCoordinate] = field(default_factory=list)
    wells: list[Well] = field(default_factory=list)

    def get_row(self, row_id: UUID) -> GridCoordinate:
        """Get the row with the specified id.

        Parameters
        ----------
        row_id : UUID
            The id of the row to look up.

        Returns
        -------
        GridCoordinate
            The row with this id.

        Raises
        ------
        KeyError
            If no row in the layout has this id.
        """
        for row in self.rows:
            if row.id == row_id:
                return row
        raise KeyError(f"no row with id {row_id}")

    def get_column(self, column_id: UUID) -> GridCoordinate:
        """Get the column with the specified id.

        Parameters
        ----------
        column_id : UUID
            The id of the column to look up.

        Returns
        -------
        GridCoordinate
            The column with this id.

        Raises
        ------
        KeyError
            If no column in the layout has this id.
        """
        for column in self.columns:
            if column.id == column_id:
                return column
        raise KeyError(f"no column with id {column_id}")

    def well(self, well_id: UUID) -> Well:
        """Get the well with the specified id.

        Parameters
        ----------
        well_id : UUID
            The id of the well to look up.

        Returns
        -------
        Well
            The well with this id.

        Raises
        ------
        KeyError
            If no well in the layout has this id.
        """
        for well in self.wells:
            if well.id == well_id:
                return well
        raise KeyError(f"no well with id {well_id}")

    def well_at(self, row_id: UUID, column_id: UUID) -> Well | None:
        """Get the well at a grid position.

        The grid may be sparse, so a row/column pair that holds no well is a
        normal state of the layout rather than a malformed one.

        Parameters
        ----------
        row_id : UUID
            The id of the row the well sits in.
        column_id : UUID
            The id of the column the well sits in.

        Returns
        -------
        Well
            The well at this position.

        Raises
        ------
        KeyError
            If the position holds no well.
        """
        for well in self.wells:
            if well.row_id == row_id and well.column_id == column_id:
                return well
        raise KeyError(f"no well with row {row_id} and column {column_id}")

    def well_name(self, well: Well) -> str:
        """Make the label for a well from its row and column.

        The label is the concatenation of the two names, e.g. row ``"A"`` and
        column ``"1"`` give ``"A1"``. It becomes the RFC-8 ``name`` of the
        well collection, which the source has no equivalent of.

        Parameters
        ----------
        well : Well
            The well to label.

        Returns
        -------
        str
            The label.

        Raises
        ------
        KeyError
            If the well names a row or column the layout does not hold.
        """
        return f"{self.get_row(well.row_id).name}{self.get_column(well.column_id).name}"


@dataclass
class HCSImage:
    """One field of view.

    Attributes
    ----------
    id : UUID
        The identifier. Becomes the RFC-8 ``id`` of the multiscale node.
    name : str
        The human-readable name, taken from the source multiscale.
    path : str
        The path to the image group relative to the Plate collection.
    series : int or None
        The position of this image in Bio-Formats series order, which is what
        makes the correspondence to an OME-XML ``<Image>`` element positional.
    acquisition_id : UUID or None
        The id of the acquisition this image belongs to, if any.
    attrs : ImageAttrsV06
        The image metadata in v0.6 format. Anything the v0.6 model does not
        define is carried in ``model_extra``. This includes the ``omero``
        metadata.
    """

    id: UUID
    name: str
    path: str
    attrs: ImageAttrsV06
    series: int | None = None
    acquisition_id: UUID | None = None

    @property
    def multiscale(self) -> Any:
        """The first multiscale of this image.

        bioformats2raw writes exactly one multiscale per image, so the rest of
        this module treats the first as the only one.

        Returns
        -------
        RFC8Multiscale
            The v0.6 multiscale metadata, as an ``ome_zarr_models`` model.
        """
        return self.attrs.multiscales[0]

    @property
    def omero(self) -> dict[str, Any] | None:
        """The rendering settings carried by this image.

        ``omero`` is not modelled by the v0.5 or v0.6 image models, so it
        arrives as an unmodelled extra and is passed through untouched. It is
        rehomed under ``omero:omero`` on conversion rather than dropped.

        Returns
        -------
        dict or None
            The ``omero`` object, or None if the image has none.
        """
        if self.attrs.model_extra is None:
            return None
        else:
            return self.attrs.model_extra.get("omero", None)


@dataclass
class OmeGroupMetadata:
    """The contents of the ``OME`` group of a bioformats2raw fileset.

    These metadata are used to populate the OmeGroup node (RFC-8 Node extension).

    Attributes
    ----------
    id : UUID
        The identifier. Becomes the RFC-8 ``id`` of the ``ome:omeGroup`` node.
    path : str
        The plate-relative path to the group, normally ``"OME"``.
    xml_filename : str
        The name of the OME-XML document inside the group. RFC-8 cannot
        reference a non-Zarr, non-JSON file, so this stays a convention.
    series : OmeSeries
        The Bio-Formats series order the group declares.
    """

    id: UUID
    path: str = OME_GROUP_NAME
    xml_filename: str = XML_FILENAME
    series: OmeSeries = field(default_factory=OmeSeries)


@dataclass
class HCSDataset:
    """An HCS dataset, as a layout that metadata can be generated from.

    Attributes
    ----------
    id : UUID
        The identifier. Becomes the RFC-8 ``id`` of the plate collection.
    root : pathlib.Path
        The root of the fileset on disk.
    name : str
        The plate name.
    layout : HCSGridLayout
        The rows, columns and wells.
    images : list of HCSImage
        Every image in the plate, in the order the wells listed them. Series
        order is carried by each image's ``series``, not by this list.
    acquisitions : list of Acquisition
        The acquisitions declared by the plate, if any.
    image_to_well : dict
        Mapping of image id to the id of the well holding it.
    well_to_images : dict
        Mapping of well id to the ids of the images it holds.
    ome_group : OmeGroupMetadata or None
        The ``OME`` group, if the fileset has one.
    bf2raw_layout : int or None
        The value of ``bioformats2raw.layout``.
    """

    id: UUID
    root: pathlib.Path
    name: str
    layout: HCSGridLayout = field(default_factory=HCSGridLayout)
    images: list[HCSImage] = field(default_factory=list, repr=False)
    acquisitions: list[Acquisition] = field(default_factory=list)
    image_to_well: dict[UUID, UUID] = field(default_factory=dict, repr=False)
    well_to_images: dict[UUID, list[UUID]] = field(default_factory=dict, repr=False)
    ome_group: OmeGroupMetadata | None = None
    bf2raw_layout: int | None = None

    def __repr__(self) -> str:
        """Summarise the plate by name, well count and image count.

        Returns
        -------
        str
            The representation. The images and the two maps are left out
            because a plate holds thousands of each.
        """
        return (
            f"{type(self).__name__}(name={self.name!r}, "
            f"wells={len(self.layout.wells)}, images={len(self.images)})"
        )

    @classmethod
    def from_bf2raw_0_5(cls, path: str | os.PathLike[str]) -> "HCSDataset":
        """Build the model from a bioformats2raw-converted v0.5 fileset.

        Image metadata converted to v0.6 form by ome-zarr-py. This mostly
        changes the transform metadata.

        Parameters
        ----------
        path : str or os.PathLike
            The root of the fileset. The root is the group containing
            the plate metadata.

        Returns
        -------
        HCSDataset
            The model of the dataset.

        Raises
        ------
        ValidationError
            If the fileset is not valid OME-Zarr 0.5 HCS, or an image's
            metadata does not match the arrays it describes.
        ValueError
            If the plate's metadata does not describe the fileset it sits in:
            a well or image that is listed but not there, an image naming an
            acquisition the plate does not declare, or an image the OME
            group's series does not name. None of these is a fileset this
            converter can describe in RFC-8 without inventing or discarding
            something, so each stops the read rather than degrading it.

        Warns
        -----
        UserWarning
            If the OME group's series names an image the fileset does not
            hold. See ``_check_series``.
        """
        root_path = pathlib.Path(path)

        # with warnings.catch_warnings():
        #     # The plate metadata of a bioformats2raw fileset has no `version`
        #     # key, which the model defaults and warns about.
        #     warnings.simplefilter("ignore")

        # Load the metadata with ome-zarr-py and get the relevant attributes
        hcs = HCS.from_zarr(zarr.open_group(root_path, mode="r"))
        ome_attributes = hcs.ome_attributes
        plate_metadata = ome_attributes.plate
        extra_metadata = ome_attributes.model_extra or {}

        # Get the OME-XML group metadata
        # We need to do this because the ome-zarr-py HCS class doesn't
        # pick up this metadata
        ome_xml_group = _read_ome_group(root_path)
        series_order = None if ome_xml_group is None else ome_xml_group.series.order

        # Build the Acquisition model
        acquisitions = _build_acquisitions(plate_metadata.acquisitions)

        # Build a mapping so it is easy to get the acquisition from the source id.
        # This is only used in this constructor.
        by_source_id = {a.source_id: a for a in acquisitions}

        # Build the grid layout
        rows = [GridCoordinate(uuid.uuid4(), row.name) for row in plate_metadata.rows]
        columns = [
            GridCoordinate(uuid.uuid4(), column.name)
            for column in plate_metadata.columns
        ]

        wells: list[Well] = []
        images: list[HCSImage] = []
        image_to_well: dict[UUID, UUID] = {}

        # Loop through the wells and make the Image classes
        for entry in plate_metadata.wells:
            group = _member(hcs, entry.path)
            if group is None:
                raise ValueError(
                    f"the plate lists a well at {entry.path!r} that is not in "
                    "the fileset; a sparse plate omits the well from its "
                    "wells list rather than listing one that is not there"
                )

            well = Well(
                id=uuid.uuid4(),
                row_id=rows[entry.rowIndex].id,
                column_id=columns[entry.columnIndex].id,
                path=entry.path,
            )
            wells.append(well)

            well_attrs = WellAttrs.model_validate(group.attributes["ome"])
            for well_image in well_attrs.well.images:
                member = (group.members or {}).get(well_image.path)
                if member is None:
                    raise ValueError(
                        f"the well at {entry.path!r} lists an image at "
                        f"{well_image.path!r} that is not in the fileset"
                    )

                image_attrs = _upgrade_image_attrs(
                    ImageAttrsV05.model_validate(member.attributes["ome"])
                )
                acquisition = None
                if well_image.acquisition is not None:
                    # Make sure the acquisition in the image metadata is one the plate declares.
                    acquisition = by_source_id.get(well_image.acquisition)
                    if acquisition is None:
                        raise ValueError(
                            f"image {entry.path}/{well_image.path} names "
                            f"acquisition {well_image.acquisition}, which the "
                            "plate does not declare"
                        )

                image_path = f"{entry.path}/{well_image.path}"
                if series_order is None:
                    series_index = None
                elif image_path in series_order:
                    series_index = series_order[image_path]
                else:
                    raise ValueError(
                        f"image {image_path!r} is not named by the "
                        f"{OME_GROUP_NAME} group's series, so it has no place "
                        "in Bio-Formats series order"
                    )

                image = HCSImage(
                    id=uuid.uuid4(),
                    name=str(image_attrs.multiscales[0].name),
                    path=image_path,
                    attrs=image_attrs,
                    series=series_index,
                    acquisition_id=None if acquisition is None else acquisition.id,
                )
                images.append(image)
                image_to_well[image.id] = well.id

        if ome_xml_group is not None:
            # Check if there are any image listed in the OME-XML that are not in the data
            missing_images = set(ome_xml_group.series.order) - {
                image.path for image in images
            }
            if missing_images:
                warnings.warn(
                    f"the {OME_GROUP_NAME} group's series names {len(missing_images)} image(s) "
                    f"the fileset does not hold, e.g. {min(missing_images)!r}",
                    stacklevel=3,
                )

        # Make the well to images mapping
        well_to_images: dict[UUID, list[UUID]] = {well.id: [] for well in wells}
        for image in images:
            well_to_images[image_to_well[image.id]].append(image.id)

        return cls(
            id=uuid.uuid4(),
            root=root_path,
            name=plate_metadata.name or root_path.name,
            layout=HCSGridLayout(rows=rows, columns=columns, wells=wells),
            images=images,
            acquisitions=acquisitions,
            image_to_well=image_to_well,
            well_to_images=well_to_images,
            ome_group=ome_xml_group,
            bf2raw_layout=extra_metadata.get("bioformats2raw.layout"),
        )

    def image(self, image_id: UUID) -> HCSImage:
        """Get the image with the specified id.

        Parameters
        ----------
        image_id : UUID
            The id of the image to look up.

        Returns
        -------
        HCSImage
            The image with this id.

        Raises
        ------
        KeyError
            If no image in the dataset has this id.
        """
        for image in self.images:
            if image.id == image_id:
                return image
        raise KeyError(f"no image with id {image_id}")

    def images_in_well(self, well_id: UUID) -> list[HCSImage]:
        """Get the images held by a well.

        Parameters
        ----------
        well_id : UUID
            The id of the well.

        Returns
        -------
        list of Image
            The images, in the order the well listed them.

        Raises
        ------
        KeyError
            If the dataset holds no well with this id.
        """
        return [self.image(image_id) for image_id in self.well_to_images[well_id]]

    def acquisition(self, acquisition_id: UUID) -> Acquisition:
        """Get the acquisition with the specified id.

        Parameters
        ----------
        acquisition_id : UUID
            The id of the acquisition to look up.

        Returns
        -------
        Acquisition
            The acquisition with this id.

        Raises
        ------
        KeyError
            If the plate declares no acquisition with this id.
        """
        for acquisition in self.acquisitions:
            if acquisition.id == acquisition_id:
                return acquisition
        raise KeyError(f"no acquisition with id {acquisition_id}")

    @property
    def field_count(self) -> int:
        """The largest number of images held by any one well.

        Recomputed from the wells rather than stored, so it cannot go stale.
        It is written out as ``missingPlate:field_count``, the source's
        ``plate.field_count``, which RFC-8 has no home for.

        Returns
        -------
        int
            The count, or 0 if the plate holds no wells.
        """
        return max((len(v) for v in self.well_to_images.values()), default=0)

    def rfc8_documents(self, *, include_missing: bool = True) -> dict[str, RFC8Node]:
        """Build the RFC-8 node of every document in the fileset.

        The conversion spans one JSON document per group, so the result is a
        mapping from document location to that document's root node rather
        than a single tree.

        Parameters
        ----------
        include_missing : bool
            Whether to write the ``missing*`` keys, which track v0.6rc0 fields
            RFC-8 has no home for. Evaluation scaffolding: it is not meant to
            reach real filesets.

        Returns
        -------
        dict
            Plate-relative directory to the root Node of the ``zarr.json``
            there. ``""`` is the plate root. Ordered root, ``OME``, then wells
            and their images in plate order.
        """
        documents: dict[str, RFC8Node] = {"": self._plate_node(include_missing)}

        if self.ome_group is not None:
            documents[self.ome_group.path] = _ome_group_document(self.ome_group)

        for well in self.layout.wells:
            documents[well.path] = self._well_document(well)
            for image in self.images_in_well(well.id):
                documents[image.path] = _image_node(image, include_missing)

        return documents

    def convert_to_rfc8(self, *, include_missing: bool = True) -> None:
        """Rewrite the fileset's metadata as RFC-8, in place.

        Only the ``attributes.ome`` object of each ``zarr.json`` is replaced.
        Array data, and every other key of those documents, is left untouched.
        The layout is checked before anything is written, so a fileset missing
        a document is not left half converted.

        Parameters
        ----------
        include_missing : bool
            Whether to write the ``missing*`` keys. See ``rfc8_documents``.

        Raises
        ------
        FileNotFoundError
            If any document in the model has no ``zarr.json`` in the fileset.
        """
        targets = []
        for relpath, node in self.rfc8_documents(
            include_missing=include_missing
        ).items():
            zarr_json = self.root / relpath / "zarr.json"
            if not zarr_json.is_file():
                raise FileNotFoundError(
                    f"no zarr.json for the node at {relpath!r}: {zarr_json}"
                )
            targets.append((zarr_json, node))

        for zarr_json, node in targets:
            write_document(node, zarr_json, container="zarr")

    def _plate_node(self, include_missing: bool) -> RFC8Collection:
        """Build the plate collection.

        The plate name becomes the node's ``name``, ``plate.wells`` becomes
        the ``nodes`` array, and the rows and columns keep only their names
        alongside the ids wells reference them by.

        Parameters
        ----------
        include_missing : bool
            Whether to write ``missingPlate:field_count``, which tracks the
            source's ``plate.field_count``.

        Returns
        -------
        RFC8Collection
            The root node, listing the OME group first and then one stub per
            well.
        """
        plate: dict[str, Any] = {}
        if self.acquisitions:
            plate["acquisitions"] = [
                _acquisition_object(acquisition, include_missing)
                for acquisition in self.acquisitions
            ]
        plate["columns"] = [
            {"id": str(column.id), "name": column.name}
            for column in self.layout.columns
        ]
        plate["rows"] = [
            {"id": str(row.id), "name": row.name} for row in self.layout.rows
        ]
        attributes: dict[str, Any] = {"plate": plate}
        if self.bf2raw_layout is not None:
            attributes["bf2raw:layout"] = self.bf2raw_layout
        if include_missing:
            # Denormalised on purpose: the wells are separate documents, so a
            # consumer cannot count fields without fetching all of them.
            attributes["missingPlate:field_count"] = self.field_count

        # The OME group is listed first, then the wells.
        nodes: list[RFC8Node] = []
        if self.ome_group is not None:
            nodes.append(_ome_group_node_entry(self.ome_group))
        nodes += [self._well_node_entry(well) for well in self.layout.wells]

        return RFC8Collection(
            version=VERSION,
            id=str(self.id),
            name=self.name,
            attributes=attributes,
            nodes=nodes,
        )

    def _well_node_entry(self, well: Well) -> RFC8Collection:
        """Build the node the plate lists for one well.

        The node carries the path to the well's own document and nothing
        else; the document at that path holds the rest.

        Parameters
        ----------
        well : Well
            The well to build the node for.

        Returns
        -------
        RFC8Collection
            The node, for the plate's ``nodes`` array. Its path resolves
            against the plate document.
        """
        return RFC8Collection(
            id=str(well.id),
            name=self.layout.well_name(well),
            path=RFC8Path(type="zarr", path=f"./{well.path}"),
        )

    def _well_document(self, well: Well) -> RFC8Collection:
        """Build the node that is one well's own document.

        It carries the same id and name as the node the plate lists, plus the
        ``well`` attribute and one node per image in the well.

        Parameters
        ----------
        well : Well
            The well to build the document for.

        Returns
        -------
        RFC8Collection
            The node, for the well's ``zarr.json``.

        Notes
        -----
        The ``acquisition`` reference sits on the image nodes here rather than
        in the image documents, so there is only one copy of it to keep
        correct. Like the row and column references it points into the plate
        document, so it carries a path back to it.
        """
        depth = well.path.count("/") + 1
        nodes: list[RFC8Node] = []
        for image in self.images_in_well(well.id):
            attributes = None
            if image.acquisition_id is not None:
                attributes = {
                    "acquisition": _plate_metadata_reference(
                        str(image.acquisition_id), depth
                    )
                }
            nodes.append(
                RFC8Multiscale(
                    id=str(image.id),
                    name=image.name,
                    attributes=attributes,
                    path=RFC8Path(
                        type="zarr", path=f"./{image.path.rsplit('/', 1)[-1]}"
                    ),
                )
            )

        return RFC8Collection(
            id=str(well.id),
            name=self.layout.well_name(well),
            attributes={
                "well": {
                    "row": _plate_metadata_reference(str(well.row_id), depth),
                    "column": _plate_metadata_reference(str(well.column_id), depth),
                }
            },
            nodes=nodes,
        )


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _upgrade_image_attrs(attrs: ImageAttrsV05) -> ImageAttrsV06:
    """Convert v0.5 image attributes to v0.6, keeping unmodelled keys.

    The upgrade is what mints the coordinate system and the transformation
    endpoints, neither of which v0.5 can express. It also loses everything the
    v0.6 model does not define, because it builds the result from
    ``multiscales`` alone -- so the extras are merged back here. ``omero`` is
    the one that matters, and dropping it would be silent.

    Parameters
    ----------
    attrs : ImageAttrsV05
        The image attributes as read from the fileset.

    Returns
    -------
    ImageAttrsV06
        The same metadata in its v0.6 form, with every unmodelled key of the
        input carried over.
    """
    upgraded = attrs.to_version("0.6", default_cs_name=COORDINATE_SYSTEM_NAME)
    return ImageAttrsV06.model_validate(
        upgraded.model_dump() | dict(attrs.model_extra or {})
    )


def _member(hcs: HCS, path: str) -> Any:
    """Find the group at a plate-relative path in a read HCS tree.

    ``GroupSpec.members`` is one level deep, so a path of more than one
    segment has to be walked.

    Parameters
    ----------
    hcs : HCS
        The plate, as read by ``HCS.from_zarr``.
    path : str
        The plate-relative path, e.g. ``"A/1"``.

    Returns
    -------
    GroupSpec or None
        The group, or None if any segment of the path is absent. Whether that
        is an error is for the caller to decide; this only reports it.
    """
    group: Any = hcs
    for segment in path.split("/"):
        members = getattr(group, "members", None) or {}
        if segment not in members:
            return None
        group = members[segment]
    return group


def _read_ome_group(root: pathlib.Path) -> OmeGroupMetadata | None:
    """Read the ``OME`` group, which the HCS model does not traverse.

    ``HCS.from_zarr`` only follows the paths named by ``plate.wells``, so the
    group holding the series order has to be read directly.

    A fileset either has a working ``OME`` group or none at all. A group that
    exists but cannot do its job -- one declaring no series, or one declaring
    a series without the OME-XML that series orders -- is malformed, and is
    rejected rather than quietly treated as absent. Treating it as absent
    would discard a declared order and leave every image unnumbered.

    Parameters
    ----------
    root : pathlib.Path
        The root of the fileset.

    Returns
    -------
    OmeGroupMetadata or None
        The group, or None if the fileset has no ``OME`` group at all.

    Raises
    ------
    ValueError
        If the group exists but declares no series, or declares one without
        the OME-XML document beside it.
    """
    group = root / OME_GROUP_NAME
    if not group.is_dir():
        return None

    paths: list[str] = []
    zarr_json = group / "zarr.json"
    if zarr_json.is_file():
        with open(zarr_json) as f:
            ome = json.load(f).get("attributes", {}).get("ome", {})
        paths = list(ome.get("series") or [])

    if not paths:
        raise ValueError(
            f"the {OME_GROUP_NAME} group at {group} declares no series, so "
            "nothing ties its images to the OME-XML"
        )
    if not (group / XML_FILENAME).is_file():
        raise ValueError(
            f"the {OME_GROUP_NAME} group at {group} declares a series but has "
            f"no {XML_FILENAME}; the series orders a document that is not there"
        )

    return OmeGroupMetadata(id=uuid.uuid4(), series=OmeSeries(paths=paths))


def _build_acquisitions(acquisitions: list[Any] | None) -> list[Acquisition]:
    """Convert the plate's acquisitions, keeping their v0.5 integer ids.

    The integer id is the only handle a well image has on an acquisition, so
    it is kept on the model even though RFC-8 ids are minted fresh.

    Parameters
    ----------
    acquisitions : list or None
        The acquisitions as read from the plate, or None if it declares none.

    Returns
    -------
    list of Acquisition
        The acquisitions, in plate order. Empty if the plate declares none.
    """
    if not acquisitions:
        return []

    result = []
    for acquisition in acquisitions:
        extra = {
            key: value
            for key in ("maximumfieldcount", "description", "starttime", "endtime")
            if (value := getattr(acquisition, key, None)) is not None
        }
        result.append(
            Acquisition(
                id=uuid.uuid4(),
                name=acquisition.name,
                source_id=acquisition.id,
                extra=extra,
            )
        )
    return result


def _acquisition_object(
    acquisition: Acquisition, include_missing: bool
) -> dict[str, Any]:
    """Build the RFC-8 Acquisition object for one acquisition.

    RFC-8 defines only ``id`` and ``name``, so the source's integer id is
    replaced by the minted one and its four remaining fields have nowhere to
    go.

    Parameters
    ----------
    acquisition : Acquisition
        The acquisition to convert.
    include_missing : bool
        Whether to write the ``missingPlateAcquisitions:`` keys, which track
        ``maximumfieldcount``, ``description``, ``starttime`` and ``endtime``.

    Returns
    -------
    dict
        The object, for the plate's ``acquisitions`` array.
    """
    result: dict[str, Any] = {"id": str(acquisition.id)}
    if acquisition.name is not None:
        result["name"] = acquisition.name
    if include_missing:
        for key, value in acquisition.extra.items():
            result[f"missingPlateAcquisitions:{key}"] = value
    return result


def _image_node(image: HCSImage, include_missing: bool) -> RFC8Multiscale:
    """Build the multiscale node for one field of view.

    The v0.6 metadata is already shaped for this: it names a coordinate
    system and gives every transformation an input and an output. The
    conversion is mostly renaming -- the coordinate system's name becomes
    an id, a transformation's input moves from an array path to the id of
    the singlescale node, and its output from a name to that id.

    Parameters
    ----------
    image : HCSImage
        The image to build the node for.
    include_missing : bool
        Whether to write the ``missingMultiscales:`` keys, which track the
        source's ``multiscales.type`` and ``multiscales.metadata``.

    Returns
    -------
    RFC8Multiscale
        The node, holding one singlescale node per resolution level.

    Warns
    -----
    UserWarning
        If the multiscale carries its own ``coordinateTransformations``.
        Whether RFC-8 covers them is undecided, so they are dropped.

    Raises
    ------
    NotImplementedError
        If a level carries a transformation this module cannot convert.
        See ``_convert_transform``.
    """
    multiscale = image.multiscale

    if multiscale.coordinateTransformations is not None:
        warnings.warn(
            f"dropping multiscale-level coordinateTransformations on "
            f"{image.path!r}: whether RFC-8 covers them is undecided",
            stacklevel=3,
        )

    coordinate_system = multiscale.intrinsic_coordinate_system
    cs_id = _derived_id(image.id, f"cs:{coordinate_system.name}")
    level_ids = {
        dataset.path: _derived_id(image.id, f"level:{dataset.path}")
        for dataset in multiscale.datasets
    }

    levels = [
        RFC8Singlescale(
            id=str(level_ids[dataset.path]),
            name=dataset.path,
            path=RFC8Path(type="zarr", path=f"./{dataset.path}"),
            attributes={
                "coordinateTransformations": [
                    _convert_transform(
                        transform,
                        input_id=str(level_ids[dataset.path]),
                        output_id=str(cs_id),
                    )
                    for transform in dataset.coordinateTransformations
                ]
            },
        )
        for dataset in multiscale.datasets
    ]

    attributes: dict[str, Any] = {
        "coordinateSystems": [
            {
                "id": str(cs_id),
                "name": coordinate_system.name,
                "axes": [
                    axis.model_dump(exclude_none=True, mode="json")
                    for axis in coordinate_system.axes
                ],
            }
        ]
    }

    # Rendering settings are rehomed rather than tracked as missing, so
    # they are not gated on include_missing.
    if image.omero is not None:
        attributes["omero:omero"] = image.omero

    if include_missing:
        for key in ("type", "metadata"):
            value = getattr(multiscale, key, None)
            if value is not None:
                attributes[f"missingMultiscales:{key}"] = value

    return RFC8Multiscale(
        id=str(image.id),
        name=image.name,
        attributes=attributes,
        nodes=levels,
    )


def _ome_group_node_entry(ome_group: OmeGroupMetadata) -> OmeGroup:
    """Build the node the plate lists for the ``OME`` group.

    Listing the group explicitly is what replaces v0.6rc0's rule that a root
    child named ``OME`` is not a row: the group is declared with a type
    rather than recognised by name.

    Parameters
    ----------
    ome_group : OmeGroupMetadata
        The group to build the node for.

    Returns
    -------
    OmeGroup
        The node, for the plate's ``nodes`` array. Its path resolves against
        the plate document, and is the only thing locating the group that
        holds the OME-XML.
    """
    return OmeGroup(
        id=str(ome_group.id),
        name=ome_group.path,
        path=RFC8Path(type="zarr", path=f"./{ome_group.path}"),
    )


def _ome_group_document(ome_group: OmeGroupMetadata) -> OmeGroup:
    """Build the node that is the ``OME`` group's own document.

    It carries the same id and name as the node the plate lists, plus
    ``ome:series``.

    Parameters
    ----------
    ome_group : OmeGroupMetadata
        The group to build the document for.

    Returns
    -------
    OmeGroup
        The node, for ``OME/zarr.json``.

    Notes
    -----
    The ``series`` entries gain a ``../`` prefix on the way out. RFC-8
    resolves a relative path against the document holding it, so the source's
    plate-relative ``"A/1/0"`` would resolve to ``"OME/A/1/0"`` from inside
    this document.
    """
    return OmeGroup(
        id=str(ome_group.id),
        name=ome_group.path,
        attributes={"ome:series": [f"../{p}" for p in ome_group.series.paths]},
    )


def _plate_metadata_reference(id_: str, depth: int) -> dict[str, Any]:
    """Build a Reference to something declared in the plate document.

    Row, column and acquisition ids live in the plate's ``zarr.json``. From a
    well document they are external references, which RFC-8 requires to carry
    a path.

    Parameters
    ----------
    id_ : str
        The id being referenced.
    depth : int
        How many levels below the plate root the referencing document sits. A
        well at ``"A/1"`` is at depth 2.

    Returns
    -------
    dict
        The Reference, carrying a path back to the plate document.
    """
    path_to_plate_zarr_json = "/".join([".."] * depth) if depth else "."
    return {"id": id_, "path": {"type": "zarr", "path": path_to_plate_zarr_json}}


def _convert_transform(transform: Any, *, input_id: str, output_id: str) -> dict:
    """Convert a v0.6 dataset transformation to its RFC-8 form.

    RFC-8 requires a Singlescale to carry exactly one ``scale``, or a
    ``sequence`` of a ``scale`` followed by a ``translation``. The endpoints
    become references to node ids rather than to an array path and a
    coordinate system name. Every other field is carried over unchanged.

    Parameters
    ----------
    transform : Scale or Sequence
        The transformation, as an ``ome_zarr_models`` v0.6 model.
    input_id : str
        The id of the singlescale node this transformation belongs to, which
        becomes its input.
    output_id : str
        The id of the coordinate system it maps into, which becomes its
        output.

    Returns
    -------
    dict
        The transformation in RFC-8 form.

    Raises
    ------
    NotImplementedError
        If the transformation is neither a scale nor a sequence of a scale
        optionally followed by a translation.
    """
    data = transform.model_dump(exclude_none=True, mode="json")

    if data.get("type") == "sequence":
        types = [inner.get("type") for inner in data.get("transformations", [])]
        if types not in (["scale"], ["scale", "translation"]):
            raise NotImplementedError(
                f"expected a scale, optionally followed by a translation, got {types}"
            )
    elif data.get("type") != "scale":
        raise NotImplementedError(
            f"expected a scale or sequence transformation, got {data.get('type')!r}"
        )

    data["input"] = {"id": input_id}
    data["output"] = {"id": output_id}
    return data


def _derived_id(namespace: UUID, key: str) -> UUID:
    """Derive an id from another, so it is stable across conversions.

    Coordinate systems and resolution levels have no identity in the source,
    and their ids only have to be unique within the image's document. Deriving
    them from the image's id keeps a second conversion of the same model from
    minting different ones.

    Parameters
    ----------
    namespace : UUID
        The id to derive from, normally an image's.
    key : str
        What is being identified, e.g. ``"level:0"``. Must be unique within
        the namespace.

    Returns
    -------
    UUID
        The derived id, the same for the same arguments every time.
    """
    return uuid.uuid5(namespace, key)
