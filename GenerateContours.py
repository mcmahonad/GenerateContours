# This script clips batch downloaded DEM tiles to a geographic area of interest and creates contour line tiles from them.
# requires pandas and arcpy installations

# ------------------------------------------------------------------------------------------------------------------------------------

# -------------------------------------------------------------- Notes ---------------------------------------------------------------

# ------------------------------------------------------------------------------------------------------------------------------------

'''
11/29: 5 ft contour creation complete. 
    478,000 features with avg. of 41.2 vertices = 19.7 million vertices
    compare to contours 2002: 457,000 features with avg. of 237.2 vertices = 108.4 million vertices
        - despite the big drop in vertices draw time still appears faster for 2002 contours?
    Some gaps along edge of tiles - not enough to be concerned about, but appear to have been created
    during focal statistics DEM resampling. 
Next steps:
    - test performance for smaller intervals? 2 ft desired but need at least 4 ft
        - 'memory leak' handling needed. Not explicitly saving to memory workspace but processing time greatly increases at higher iterations. 
    - confirm vertical and horizontal datum correct with no issues. 
'''
# ------------------------------------------------------------------------------------------------------------------------------------
#
# ------------------------------------ Imports, set environments/inputs/workspaces --------------------------------------------
#
# ------------------------------------------------------------------------------------------------------------------------------------

import arcpy
from arcpy import env
from arcpy.stats import MeanCenter
import pandas as pd
import os
import datetime
from datetime import date
import sys
sys.path.append(placeholder1)
import apshorthand as aps # personal module for reducing verbosity of arcpy function calls in terminal


# Prevent file clutter during tests
env.overwriteOutput = True

# Desired smoothing tolerance for line simplication algorithim. Very small values still produce big reductions in contour vertices. 
simpTolerance = "0.5 Feet"

# Desired contour interval in feet
interval = 5

# tile overlap distance in meters. 
tileOverlap = "10 meters"

# Set cell size for the merged DEM. Values larger than the input raster cell size will smooth contours
cellSize = 1

# Set workspace and export locations. Create these directories ahead of time. 
# contains DEM tiles downloaded from VGIN. Script currently configured for .img
rawDEMFolder = placeholder2

# contains overlapping DEM tiles created from the mosaic merge and re-split. 
outDEMFolder = placeholder3  

# contains working data created by the tile overlaps
workingFolder = placeholder4

# GDB containing working data (for now just mosaics). Nested under workingFolder. Mosaic dataset must go into a gdb. 
workingDB = 'Working.gdb'
workingGDBPath = workingFolder + "\\" + str(workingDB)

# contains output contours. Export fails if this is nested under the working folder. 
contourExportLoc = workingFolder
contourGDB = 'Working.gdb'
contourGDBPath = contourExportLoc +"\\"+ str(contourGDB)

# ------------------------------------------------------------------------------------------------------------------------------------
#
# ------------------------------------------------- delete rasters outside of the AOI ------------------------------------------------
#
# ------------------------------------------------------------------------------------------------------------------------------------

# Set workspace to folder containing DEM tiles and create list of rasters
env.workspace = rawDEMFolder

rasList = arcpy.ListRasters()

# No need to run this section after the first run.
'''
# Before running script, create a mosaic dataset in Pro and add DEM tiles. Once generated, select footprints intersecting the Area of interest and export these to the csv below
# The tile names are included in the footprints csv and will be used to delete unwanted tiles. 

# Read downloaded footprints table
footprintTable = pd.read_csv(placeholder5)
# extract tile names and convert to a list. Append raster file extension. 
footprintNames = list(footprintTable['Name'])
footprintNames = [footprint + ".img" for footprint in footprintNames]

# Verify that rasters match the list of raster names so they aren't deleted accidentally. 
rasLen = []
for ras in rasList:
    if ras in footprintNames:
        rasLen.append(ras)
    else:
        pass

# delete all rasters in the DEM tile folder that aren't listed in the footprints list.
if len(rasLen) == len(footprintNames):
    for ras in rasList:
        if ras not in footprintNames:
            arcpy.management.Delete(ras)
        else:
            pass
else:
    print("raster footprint file length does not match number of DEMs in directory. Prevented deletion")
'''
# ---------------------------------------------------------------------------------------------------------------------------------------
#
# --------------------------------------------------------- create tile overlaps --------------------------------------------------------
#
# ---------------------------------------------------------------------------------------------------------------------------------------
'''
creating contours from the raw VGIN tiles creates gaps at the boundary of each tile and sometimes interpolates poorly along those gaps.
in order to rectify, overlaps need to be created between tiles so that the contours cover the gaps.
handle this by merging the tiles, resplit into new tiles with an overlap, create contours, and then clip to original tile boundaries. 
'''
# create mosaic -> load datasets to mosaic -> mosaic to new raster -> export mosaic dataset footprints -> buffer footprints -> split raster with buffered footprints

# the list of rasters in the workspace should be shorter after deleting unneeded ones.
rasListReduced = arcpy.ListRasters()
# create subset for testing. Remove index if running the whole dataset.  
rasSub = rasListReduced

# create mosaic from the remaining tiles and load them in
rasMosaic = arcpy.management.CreateMosaicDataset(workingGDBPath, "workingMosaic_" + str(date.today()), arcpy.Describe(rasSub[0]).spatialReference, 1, "32_BIT_FLOAT")
arcpy.management.AddRastersToMosaicDataset(rasMosaic, "Raster Dataset", rasSub) 

# create footprints of the DEM tiles from the new mosaic.
outFootprintPath = os.path.join(workingFolder, "MergedDEMfootprints_" + str(date.today()))
outFootprints = arcpy.management.ExportMosaicDatasetGeometry(in_mosaic_dataset = rasMosaic, out_feature_class = outFootprintPath, geometry_type = "FOOTPRINT")

# merge DEM tiles to new ras and buffer foorprints to cover the gaps. Set buffer distance at head
rasMerge = "rasMerge_"+ str(date.today()) +  "_.img"
arcpy.management.MosaicToNewRaster(rasSub, workingFolder, rasMerge, arcpy.Describe(rasSub[0]).spatialReference,"32_BIT_FLOAT", cellSize, 1)
bufferedFootprints = os.path.join(workingFolder, "Bufferedfootprints_" + str(date.today()))
arcpy.Buffer_analysis(outFootprintPath + ".shp", bufferedFootprints, tileOverlap, "FULL")

# split raster into overlapping tiles using the buffered footprints. Run focal statistics for DEM smoothing. 
outNameFormat = "Split_" + str(date.today()).replace("-", "_")
arcpy.management.SplitRaster(in_raster = os.path.join(workingFolder, rasMerge), out_folder = outDEMFolder, out_base_name = outNameFormat + "_", split_method = "POLYGON_FEATURES", format = "IMAGINE IMAGE", resampling_type = "BILINEAR", split_polygon_feature_class = bufferedFootprints + ".shp") 

env.workspace = outDEMFolder

rasSplit = arcpy.ListRasters()

for ras in rasSplit:
    focalRas = arcpy.ia.FocalStatistics(ras, "Rectangle 3 3 CELL", "MEAN")
    focalRas.save(outDEMFolder + "\\Focal\\Focal_" + ras)

# ---------------------------------------------------------------------------------------------------------------------------------------
#
# ------------------------------------------------------ create contours from tiles -----------------------------------------------------
#
# ---------------------------------------------------------------------------------------------------------------------------------------
# set workspace to the procressed DEM tiles -> create contours -> delete noise -> reduce vertices -> clip to original (unbuffered) footprints -> merge

env.workspace = os.path.join(outDEMFolder, "Focal")
procRasSplit = arcpy.ListRasters()

# get start time of loop execution and indicate which tile is being processed. 
startTime = time.time()
counter = 1

# create list of rasters to be merged 
contourMergeList = []

for ras in procRasSplit:
    print(f"processing tile {counter} of {len(procRasSplit)}")
    outContour = os.path.join(contourGDBPath, "raw_" + ras.split(".")[0])
    arcpy.sa.Contour(in_raster = ras, out_polyline_features = outContour, contour_interval = interval, z_factor = 3.28084, max_vertices_per_feature = 400)

    # Delete noise - contours under 20 ft length.
    trimContours = arcpy.management.SelectLayerByAttribute(outContour, "NEW_SELECTION", "shape_Length < 20")
    arcpy.DeleteFeatures_management(trimContours)

    # Reduce line vertices
    outSimpPath = os.path.join(contourGDBPath, "simp_" + ras.split(".")[0])
    outSimp = arcpy.SimplifyLine_cartography(in_features = outContour, out_feature_class = outSimpPath, algorithm = "POINT_REMOVE",
                                    tolerance = simpTolerance, error_resolving_option = "RESOLVE_ERRORS", collapsed_point_option = "NO_KEEP")

    # Clip contours back down to the original footprints. Select each footprint using mean centers derived from contour tiles.
    footprintSelectorPath = os.path.join(contourGDBPath, "meanCenter" + ras.split(".")[0])
    footprintSelector = arcpy.MeanCenter_stats(outSimp, footprintSelectorPath)

    clipFootprint = arcpy.SelectLayerByLocation_management(outFootprints, "INTERSECT", footprintSelector)

    clipContourPath = os.path.join(contourGDBPath, "clip_" + ras.split(".")[0])
    clipContour = arcpy.Clip_analysis(outSimp, clipFootprint, clipContourPath)

    contourMergeList.append(clipContour)
    
    # tile complete, record next iteration
    counter = counter + 1

# get loop runtime in seconds after completion
executionTime = time.time() - startTime
print(f"created {len(procRasSplit)} tiles with {interval} ft contour interval in {round(executionTime, 4)} sec ({round(executionTime/len(procRasSplit),4)} sec/tile)")

# merge contours. Handling final clip in ArcGIS Pro. 
finalMergePath = os.path.join(contourGDBPath, "_contours" + str(interval) + "_ft")
arcpy.Merge_management(contourMergeList, finalMergePath)