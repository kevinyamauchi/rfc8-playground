# bioformats2raw HCS example

This is an example to explore how a bioformats-converted HCS dataset can be expressed as a 

## Setup

### Install bioformats2raw

1. Get bioformats2raw v0.12.1 from https://github.com/glencoesoftware/bioformats2raw/releases/tag/v0.12.1.
2. Unzip into `rfc8-playground/examples/bf2raw_hcs`
3. bioformats2raw requires a Java runtime. I used Pixi to locally install and use `openjdk` (see pyproject.toml). If you prefer a different Java runtime, install that one instead.
### Get the sample data

We are using the “Single file OME-tiff” dataset from the [OME-tiff Plate sample data](https://ome-model.readthedocs.io/en/stable/ome-tiff/data.html#plate) (licensed CC-BY-NC-SA 3.0). Download the data (`NIRHTa+001.ome.tiff`) and move it into the `examples/bf2raw_hcs` directory. See the note below from the ome-model docs about a similar file that is invalid. Make sure you have the right one!

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
### 0.6rc0 metadata missing from RFC-8

There are a few fields specified in 0.6rc0 that are not explicitly defined in RFC-8. I am not sure if these are intentionally removed or if they should be implicitly inherited from 0.6rc0. I have added them using the `missingObjectName:` attribute extension namespace. I have listed them below.

| v0.6rc0 field | Level | Key |
| --- | --- | --- |
| [`plate.field_count`](../../../docs/ngff_06rc0.md:1630) | SHOULD | `missingPlate:field_count` |
| [`plate.acquisitions[].maximumfieldcount`](../../../docs/ngff_06rc0.md:1611) | SHOULD | `missingPlateAcquisitions:maximumfieldcount` |
| [`plate.acquisitions[].description`](../../../docs/ngff_06rc0.md:1613) | MAY | `missingPlateAcquisitions:description` |
| [`plate.acquisitions[].starttime`](../../../docs/ngff_06rc0.md:1615) | MAY | `missingPlateAcquisitions:starttime` |
| [`plate.acquisitions[].endtime`](../../../docs/ngff_06rc0.md:1615) | MAY | `missingPlateAcquisitions:endtime` |
| [`multiscales.type`](../../../docs/ngff_06rc0.md:1398) | SHOULD | `missingMultiscales:type` |
| [`multiscales.metadata`](../../../docs/ngff_06rc0.md:1402) | SHOULD | `missingMultiscales:metadata` |
| [`image-label.properties[]`](../../../docs/ngff_06rc0.md:1527) arbitrary keys | MAY | `missingImageLabel:properties` |

## Open questions
1. What is the `bioformats2raw.layout` metadata for and [why must it have the value 3](https://ngff.openmicroscopy.org/specifications/dev/index.html#details)? 
2. What is the `series` metadata for? Is there some sort iterator downstream?
3. Since the `series` metadata is in the OME group and in RFC-8 relative paths are from the zarr.json document, do we want to write them as “../A/1”? Do we want to make them Path objects instead of strings?
4. Do we make the OME group an RFC-8 Node? Do we add a core OME RFC-8 `Node` type? If not, does this get added as an extension under the `ome` or `bf2raw` namespace (or other)?
5. What is the `field_count` attribute? Is it the number of fields of view in each well? Or is it the total number of fields of view in the plate? 
