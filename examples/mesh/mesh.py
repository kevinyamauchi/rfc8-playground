"""This script demonstrates a collections dataset with an image, label, and mesh."""

import napari
import numpy as np
from skimage.draw import ellipsoid
from skimage.measure import label, marching_cubes

# Generate a level set about zero of two identical ellipsoids in 3D
ellip_base = ellipsoid(6, 10, 16, levelset=True)
ellip_double = np.concatenate((ellip_base[:-1, ...], ellip_base[2:, ...]), axis=0)

segmentation = label(ellip_double < 0)

label_values = np.unique(segmentation)
all_vertices = []
all_faces = []
face_offset = 0
for value in label_values:
    if value == 0:
        # skip background
        continue
    vertices, faces, _, _ = marching_cubes(segmentation == value)
    all_vertices.append(vertices)
    all_faces.append(faces + face_offset)
    face_offset += len(vertices)

all_vertices = np.concatenate(all_vertices)
all_faces = np.concatenate(all_faces)


viewer = napari.Viewer()
viewer.add_image(ellip_double)
viewer.add_labels(segmentation)
viewer.add_surface((all_vertices, all_faces))

napari.run()
