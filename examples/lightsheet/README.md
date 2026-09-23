# Timelapse lightsheet microscopy example

This is an example to explore how a timelapse lightsheet microscopy dataset with some preliminary processed results such as a segmentation and a tracking graph can be represented as RFC-8 collections and extensions.

## The dataset

The dataset is a timelapse lightsheet microscopy dataset of an organoid from the Hess et al. (DOI: [10.5281/zenodo.22078387](https://doi.org/10.5281/zenodo.22078388), licensed [CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.en). You can access the dataset via the Zenodo repository at [https://doi.org/10.5281/zenodo.22078387](https://doi.org/10.5281/zenodo.22078387).

The dataset (001-full) has several components that we will try to represent in the RFC-8 format:
- images: there are both raw (raw.ome.zarr) and deconvolved images (deconv.ome.zarr). The images are 5D (t, c, z, y x) and are stored as v0.5 OME-Zarr multiscale images. See the [zenodo repository](https://doi.org/10.5281/zenodo.22078387)) for more details on the interpretation of the labels.
- labels: there are three segmentations associated with the deconvolved image. An instance segmentation for the nuclei (deconv.ome.zarr/labels/nucleus), an instance segmentation for the cells (deconv.ome.zarr/labels/cell), and a semantic segmentation for the lumen/tissue (deconv.ome.zarr/labels/lumen). Like the images, these are stored as v0.5 OME-Zarr multiscale labels. See the [zenodo repository](https://doi.org/10.5281/zenodo.22078387)) for more details on the interpretation of the labels.
- max intensity projections: there are max intensity projections for the raw (raw_mip-z.ome.zarr) and deconvolved (deconv_mip-z.ome.zarr) images. These are projected along the z axis and are stored as OME-Zarr v0.5 multiscale images with a singleton z dimension.
- tracking graph: there is a graph that tracks the centroids of the nuclei over time (deconv.ome.zarr/tracks/nucleus.geff. The tracks are stored in the [Graph Exchange File Format (GEFF) v1.2](https://liveimagetrackingtools.org/geff/v1.2.0.1.1/specification/). See the [zenodo repository](https://doi.org/10.5281/zenodo.22078387)) for more details on the interpretation of track properties.
- timestamp table: there is a table that contains a timestamp for each image time index. This is to accommodate acquisitions that do not have equal time between frames (e.g., increasing the rate when something interesting is happening). The table is stored as a Parquet table in the [ngio generic table v1 format](https://biovisioncenter.github.io/ngio/stable/table_specs/table_types/generic_table/) (deconv.ome.zarr/tables/timestamps/table.parquet and deconv.ome.zarr/tables/timestamps/zarr.json).
- DCA metadata: there is Dynamic Cell Atlas (DCA) metadata stored with each image that describes the sample and acquisition. The DCA metadata are stored in the top-level zarr.json of each multiscal image under the `dca` attribute. See the [zenodo repository](https://doi.org/10.5281/zenodo.22078387)) for more details on the interpretation of the DCA metadata.

## The RFC-8 representation

### Overall structure

We can use the RFC-8 collection mechanism to group the different components of the dataset. We can use a top-level `Collection` with `Collection` subnodes to group the different subcomponents (e.g., all of the labels).

One possibility would be to have a top-level `Collection` with four subnodes that group by the type of data: `images`, `labels`, `tracks`, and `tables`. The `images` collection would contain the four images (raw, deconvolved, raw MIP, and deconvolved MIP). The `labels` collection would contain the three segmentations (nucleus, cell, and lumen). The `tracks` collection would contain the GEFF graph for the nucleus tracks. The `tables` collection would contain the ngio table for the timestamps.

```json
001-full/
└── zarr.json
    ├── zarr_format: 3
    ├── node_type: "group"
    └── attributes:
        └── ome:
            ├── version: "0.9dev2"
            ├── type: "collection"
            ├── id: "<uuid>"
            ├── name: "001-full"
            ├── attributes:
            │   └── scene: { coordinateSystems: (2)[…], coordinateTransformations: (9)[…] }
            └── nodes:
                ├── 0:
                │   ├── type: "collection"
                │   ├── id: "<uuid>"
                │   ├── name: "images"
                │   └── nodes: (4)[…]    # raw, deconvolved, raw MIP (z), deconvolved MIP (z)
                ├── 1:
                │   ├── type: "collection"
                │   ├── id: "<uuid>"
                │   ├── name: "labels"
                │   └── nodes: (3)[…]    # nucleus, cell, lumen
                ├── 2:
                │   ├── type: "collection"
                │   ├── id: "<uuid>"
                │   ├── name: "tracks"
                │   └── nodes:
                │       └── 0:
                │           ├── type: "geff:graph"
                │           ├── id: "<uuid>"
                │           ├── name: "nucleus"
                │           ├── path:
                │           │   ├── type: "zarr"
                │           │   └── path: "./deconv.ome.zarr/tracks/nucleus.geff"
                │           └── attributes: { coordinateSystems: (1)[…], "geff:relatedObjects": (1)[…] }
                └── 3:
                    ├── type: "collection"
                    ├── id: "<uuid>"
                    ├── name: "tables"
                    └── nodes: (1)[…]    # timestamps (ngio:table)
```

A second alternative would be to group the derived results from their source image. In this case we would have two subcollections: `raw` and `deconvolved`. The `raw` collection would contain the raw image and the raw MIP. The `deconvolved` collection would contain the deconvolved image, the deconvolved MIP, the three segmentations, the nucleus tracks, and the timestamps table.

```json
001-full/
└── zarr.json
    ├── zarr_format: 3
    ├── node_type: "group"
    └── attributes:
        └── ome:
            ├── version: "0.9dev2"
            ├── type: "collection"
            ├── id: "<uuid>"
            ├── name: "001-full"
            ├── attributes:
            │   └── scene: { coordinateSystems: (2)[…], coordinateTransformations: (9)[…] }
            └── nodes:
                ├── 0:
                │   ├── type: "collection"
                │   ├── id: "<uuid>"
                │   ├── name: "raw"
                │   └── nodes:
                │       ├── 0: { type: "multiscale", id: "<uuid>", name: "raw", … }                   # raw.ome.zarr
                │       └── 1: { type: "multiscale", id: "<uuid>", name: "raw MIP (z)", … }           # raw_mip-z.ome.zarr
                └── 1:
                    ├── type: "collection"
                    ├── id: "<uuid>"
                    ├── name: "deconv"
                    └── nodes:
                        ├── 0: { type: "multiscale", id: "<uuid>", name: "deconvolved", … }           # deconv.ome.zarr
                        ├── 1: { type: "multiscale", id: "<uuid>", name: "deconvolved MIP (z)", … }   # deconv_mip-z.ome.zarr
                        ├── 2: { type: "multiscale", id: "<uuid>", name: "nucleus", … }               # deconv.ome.zarr/labels/nucleus
                        ├── 3: { type: "multiscale", id: "<uuid>", name: "cell", … }                  # deconv.ome.zarr/labels/cell
                        ├── 4: { type: "multiscale", id: "<uuid>", name: "lumen", … }                 # deconv.ome.zarr/labels/lumen
                        ├── 5:
                        │   ├── type: "geff:graph"
                        │   ├── id: "<uuid>"
                        │   ├── name: "nucleus tracks"
                        │   ├── path:
                        │   │   ├── type: "zarr"
                        │   │   └── path: "./deconv.ome.zarr/tracks/nucleus.geff"
                        │   └── attributes: { coordinateSystems: (1)[…], "geff:relatedObjects": (1)[…] }
                        └── 6: { type: "ngio:table", id: "<uuid>", name: "timestamps", … }            # deconv.ome.zarr/tables/timestamps
```

### Images

The `images` `Collection` will contain one `Multiscale` image node for each of the four images (raw, deconvolved, raw MIP, and deconvolved MIP).

### Labels

The `labels` `Collection` will contain one `Multiscale` label node for each of the three segmentations. All of the labels were derived from the deconvolved image, so we can use the `source` attribute to reference the `deconv.ome.zarr` image node. 

### GEFF extension

We can store all tracks in the `tracks` `Collection`. We can use the RFC-8 extension mechanism to define a GEFF node extension. As GEFF uses the zarr file, we can use the Zarr Path type to point to the GEFF file.

### ngio Tables extension

We can store all tables in the `tables` `Collection`. We can use the RFC-8 extension mechanism to define a ngio Tables node extension. As ngio tables use a Parquet file, we will have to create a Path extension for Parquet files. Also, the `ngio` table stores some metadata in the zarr.json, we will have to create an ngio attributes extension using the `ngio` namespace.


### DCA metadata extension

We can use the RFC-8 attribute extension mechanism to define a DCA metadata extension. As is done in the original dataset, we can store the DCA metadata in the top-level zarr.json of each multiscale image under the `dca:metadata` attribute.


## Open questions
- How do we annotate one image as derived from another image? For example, the deconvolved image is derived from the raw image. Should the `source` attribute be used for all `Multiscale` and not just labels?
- How to we represent the non-uniform timepoints? This isn't necessarily an RFC-8 question alone. We can use likely derive a transform (e.g., 1D displacement field) from the table.
- Can we use the GEFF `related_objects` field to point to the source labels? Do we need to unify the way paths/references are specified across RFC-8 and GEFF?