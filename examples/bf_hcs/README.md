# bioformats2raw HCS example

This is an example to explore how the bioformats2raw HCS convention can be expressed as an RFC-8 extension.

## Design of the bioformats2raw extension

### bioformats2raw in 0.6rc0

In the current OME-NGFF spec (0.6rc0), [bioformats2raw](https://ngff.openmicroscopy.org/specifications/dev/index.html#bioformats2raw-layout-metadata-transitional) is defined as [“transitional” metadata](https://ngff.openmicroscopy.org/specifications/dev/index.html#bioformats2raw-layout-metadata-transitional). That is, it was metadata introduced with the intention of removing it as the OME-NGFF specification matured.

There were two main metadata attributes introduced to support bioformats2raw:
- **`bioformats2raw.layout`**: this attribute defines the version of the layout being used in the dataset. It is stored in the top-level `zarr.json`.
- **`series`**: this attribute defines the order of the images and has to match the OME-XML (if provided). It’s not totally clear to me how this is used (see Open Questions below.). It is an ordered list of the paths to each image in the dataset. The paths are stored as strings. There are limited details in the spec on how the path should be formatted. It is stored in the `OME` group's `zarr.json`, **not** at the top level.

Both are stored under the `ome` key, but in different documents. The top-level `zarr.json`:
```json
{
  "zarr_format": 3,
  "node_type": "group",
  "attributes": {
    "ome": {
      "version": "0.6rc0",
      "bioformats2raw.layout": 3
    }
  }
}
```

There is also an OME group defined to link OME-XML metadata to the OME-Zarr images. [OME-XML](https://ome-model.readthedocs.io/en/stable/ome-xml/index.html) is a format for storing the OME Data Model. The OME Data Model expresses acquisition and experimental metadata. The OME group is a zarr group named `OME` that contains an OME-XML-formatted metadata file named `METADATA.ome.xml` whose path should be `OME/METADATA.ome.xml` from the top-level `zarr.json`. The `series` attribute lives in that group's own `zarr.json`, alongside the OME-XML file it is ordered against:

```json
{
  "zarr_format": 3,
  "node_type": "group",
  "attributes": {
    "ome": {
      "version": "0.6rc0",
      "series": ["0", "1"]
    }
  }
}
```


### omero metadata in 0.6rc0

There is optional transitional [metadata to store OMERO rendering settings](https://ngff.openmicroscopy.org/specifications/dev/index.html#omero-metadata-transitional) in 0.6rc0. [OMERO](https://www.openmicroscopy.org/omero/) is an application for managing and visualizing images. `bioformats2raw` automatically adds 

From the [bioformats2raw README](https://github.com/glencoesoftware/bioformats2raw):
> Versions 0.5.0 and later write OMERO rendering metadata by default. This includes calculating the minimum and maximum pixel values for the entire image. We recommend keeping this metadata for maximum compatibility with downstream applications, but it can be omitted by using the --no-minmax option.

### Expressing bioformats2raw as an RFC-8 extension

I propose that we can express the bioformats2raw metadata as RFC-8 extensions. To do so, we can use two types of extensions:
- **attributes**: we add attribute extensions for the bioformats2raw and omero metadata.
- **node**: we add a node extension for the OME node.

| Item | Where in bf2raw output | RFC-8 / extension representation | Rationale |
| --- | --- | --- | --- |
| `bioformats2raw.layout: 3` | root `zarr.json` | root collection `attributes["bf2raw:layout"]: 3` | This specifies the layout format being used. It follows the same convention as in v0.6rc0, but expressed as an attribute extension. |
| `series` array | `/OME/zarr.json` | `ome:series` on the `ome:omeGroup` node, i.e. `OME/zarr.json` | This is the same mechanism used in 0.6rc0 to map image arrays to OME-XML entries, expressed as an RFC-8 attribute extension. It stays in the OME group's `zarr.json`, which is both where 0.6rc0 puts it and beside the OME-XML file it is ordered against. Note the paths are relative to the containing document — see open question 3. |
| `OME` group | `/OME/zarr.json` | An `ome:omeGroup` node, listed in the plate collection's `nodes` | Creating an OME-XML node type allows readers to know where to find the OME-XML and how to open it. 0.6rc0 already utilized a Zarr group to define an OME node. |
| `omero` metadata | image `zarr.json`, e.g. `A/1/0/zarr.json` | `omero:omero` on the `multiscale` node | The OMERO rendering metadata is written by the bioformats2raw converter. |

We additionally use the HCS metadata in RFC-8 as is described in the table below. Note the [RFC-8 HCS metadata section](https://ngff.openmicroscopy.org/rfc/8/index.html#high-content-screening-hcs-metadata) departs from the MAY, SHOULD, MUST language and uses "Required Yes/No". That is reflected in the table below.

| RFC-8 HCS field | Required | Stored in | Notes |
| --- | --- | --- | --- |
| `plate` | Y | plate collection, root `zarr.json` | 0.6rc0 `plate` |
| `plate.rows[].id` | Y | plate collection, root `zarr.json` | Needs to be created. Could be the row name. |
| `plate.rows[].name` | N | plate collection, root `zarr.json` | Same as 0.6rc0 `plate.rows[].name` |
| `plate.columns[].id` | Y | plate collection, root `zarr.json` | Needs to be created. Could be the column name, e.g. `col1` |
| `plate.columns[].name` | N | plate collection, root `zarr.json` | Same as 0.6rc0 `plate.columns[].name` |
| `plate.acquisitions[]` | N | plate collection, root `zarr.json` | Already in 0.6rc0 |
| `plate.acquisitions[].id` | Y | plate collection, root `zarr.json` | 0.6rc0 acquisition has an `id`, but it is an integer. Must be converted to a string. |
| `plate.acquisitions[].name` | N | plate collection, root `zarr.json` | Same as 0.6rc0 `plate.acquisitions[].name` |
| `well` | Y | well collection, e.g., `A/1/zarr.json` | Fields are all different than in  0.6rc0|
| `well.row` | Y | well collection, e.g., `A/1/zarr.json` | Reference to a `Row` in `plate.rows[].id` |
| `well.column` | Y | well collection, e.g., `A/1/zarr.json` | Reference to a `Column` in `plate.columns[].id` |
| `acquisition` | N | each `multiscale` node in a well | Reference to an `Acquisition` in `plate.acquisitions[].id`. In 0.6rc0 the equivalent is the integer in `well.images[].acquisition`. |


#### Fields missing in RFC-8

There are a few fields specified in 0.6rc0 that are not explicitly defined in RFC-8. I am not sure if these are intentionally removed or if they should be implicitly inherited from 0.6rc0. I have added them using the `missingObjectName:` attribute extension namespace. I have listed them below.

| v0.6rc0 field | Level | Key |
| --- | --- | --- |
| [`plate.field_count`](../../../docs/ngff_06rc0.md:1630) | SHOULD | `missingPlate:field_count` |
| [`plate.acquisitions[].maximumfieldcount`](https://ngff.openmicroscopy.org/specifications/dev/index.html#plate-metadata) | SHOULD | `missingPlateAcquisitions:maximumfieldcount` |
| [`plate.acquisitions[].description`](https://ngff.openmicroscopy.org/specifications/dev/index.html#plate-metadata) | MAY | `missingPlateAcquisitions:description` |
| [`plate.acquisitions[].starttime`](https://ngff.openmicroscopy.org/specifications/dev/index.html#plate-metadata) | MAY | `missingPlateAcquisitions:starttime` |
| [`plate.acquisitions[].endtime`](https://ngff.openmicroscopy.org/specifications/dev/index.html#plate-metadata) | MAY | `missingPlateAcquisitions:endtime` |
| [`multiscales.type`](https://ngff.openmicroscopy.org/specifications/dev/index.html#multiscales-metadata) | SHOULD | `missingMultiscales:type` |
| [`multiscales.metadata`](https://ngff.openmicroscopy.org/specifications/dev/index.html#multiscales-metadata) | SHOULD | `missingMultiscales:metadata` |
| [`image-label.properties[]`](https://ngff.openmicroscopy.org/specifications/dev/index.html#labels-metadata) arbitrary keys | MAY | `missingImageLabel:properties` |

## Open questions
1. What is the `bioformats2raw.layout` metadata for and [why must it have the value 3](https://ngff.openmicroscopy.org/specifications/dev/index.html#details)? 
2. What is the `series` metadata for? Is there some sort iterator downstream?
3. Since the `series` metadata is in the OME group and in RFC-8 relative paths are from the zarr.json document, do we want to write them as “../A/1”? Do we want to make them Path objects instead of strings?
4. Do we make the OME group an RFC-8 Node? Do we add a core OME RFC-8 `Node` type? If not, does this get added as an extension under the `ome` or `bf2raw` namespace (or other)?
5. What is the `field_count` attribute? Is it the number of fields of view in each well? Or is it the total number of fields of view in the plate?
6. Do we want to put the OME XML ID on each image to make it easier to look up? Currently one has to iterate through the `series` list to find the path and then use that index. This would be expensive for large collections. Likely out of scope for RFC-8 as it is a bioformats2raw-specific issue and this matches the 0.6rc0 implementation.
7. Do we want to add an attribute that gives the path to the OME-XML file? Or do we stick with the assumption that there will only ever be one OME group and it will be named “OME”? Alternatively, we can add an attribute to the OMEGroup node that specifies the filename of the corresponding OME-XML file.
8. RFC-8 definition of the Well attribute is unclear. “row”/“column” are specified as type “string”, but the notes say `Reference` 



## Run the example

### Install bioformats2raw

1. Get bioformats2raw v0.12.1 from https://github.com/glencoesoftware/bioformats2raw/releases/tag/v0.12.1.
2. Unzip into `rfc8-playground/examples/bf_hcs`
3. bioformats2raw requires a Java runtime. I used Pixi to locally install and use `openjdk` (see pyproject.toml). If you prefer a different Java runtime, install that one instead.
### Get the sample data

We are using the “Single file OME-tiff” dataset from the [OME-tiff Plate sample data](https://ome-model.readthedocs.io/en/stable/ome-tiff/data.html#plate) (licensed CC-BY-NC-SA 3.0). Download the data (`NIRHTa+001.ome.tiff`) and move it into the `examples/bf_hcs` directory. See the note below from the ome-model docs about a similar file that is invalid. Make sure you have the right one!

> Note:
> An OME-TIFF file representative of the same plate had been previously generated and made available under NIRHTa-001.ome.tiff. Although the file is syntactically valid, the plate layout is incorrect due to a conversion issue. This file should be considered as deprecated and superseded by the two representative plate examples described above.

### Convert the sample data to ome-zarr v0.5 using bioformats2raw

1. Change directory to the example directory
	```bash
    cd examples/bf2raw_hcs
	```
2. Run the conversion using pixi and bioformats2raw. Note the `—ngff-version` flag for setting 
   ```bash
   pixi run ./bioformats2raw-0.12.1/bin/bioformats2raw  NIRHTa\+001.ome.tiff NIRHTa\+001.ome.zarr --ngff-version 0.5
   ```

