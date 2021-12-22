# This script clips batch downloaded DEM tiles to a geographic area of interest and creates contour line tiles from them.
# requires pandas and arcpy installations

# ------------------------------------------------------------------------------------------------------------------------------------
#
# ------------------------------------------- Imports, set environments/inputs/workspaces --------------------------------------------
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

# file paths go in configuration file
import configparser
configPath = os.path.join(os.getcwd(), "WorkspaceConfig.ini")
config = configparser.ConfigParser()
config.read(configPath)

sys.path.append(config['MODULES']['apshorthand'])
from apshorthand import * # personal module for more convenient arcpy function call syntax in terminal

# Allow overwriting output to prevent file clutter during tests
env.overwriteOutput = True

# Desired smoothing tolerance for line simplication algorithm. Very small values still produce big reductions in contour vertices. 
simpTolerance = "0.5 Feet"

# Desired contour interval in feet
interval = 2

# tile overlap distance in meters. 
tileOverlap = "10 meters"

# Set cell size for the merged DEM. Values larger than the input raster cell size will smooth contours
cellSize = 1

# Set workspace and export locations.
# contains DEM tiles downloaded from VGIN. Script currently configured for .img
rawDEMFolder = config['FOLDERS']['rawDEMFolder']

# contains overlapping DEM tiles created from the mosaic merge and re-split.
outDEMFolder = config['FOLDERS']['outDEMFolder'] 

# contains working data created by the tile overlaps
workingFolder = config['FOLDERS']['workingFolder']

# GDB containing working mosaics. Nested under workingFolder. Mosaic dataset must go into a gdb. 
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
# Before running script, create a mosaic dataset in Pro and add DEM tiles.
# Once generated, select footprints intersecting the area of interest and export these to the csv below
# The tile names are included in the footprints csv and will be used to delete unwanted tiles. 

# Read downloaded footprints table
footprintTable = pd.read_csv(config['FOLDERS']['footprintTable'])
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

create mosaic -> load datasets to mosaic -> mosaic to new raster -> export mosaic dataset footprints -> buffer footprints -> split raster with buffered footprints
'''

# the list of rasters in the workspace should be shorter after deleting unneeded ones.
rasListReduced = arcpy.ListRasters()
# create subset for testing. Remove index if running the whole dataset.  
rasSub = rasListReduced[0:100]

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

# run focal statistics on merged raster to create smoothed contour lines that don't look "chunky" like lines simplified by generalization/simplifaction of existing lines.
for ras in rasSplit:
    focalRas = arcpy.ia.FocalStatistics(ras, "Rectangle 3 3 CELL", "MEAN")
    focalRas.save(outDEMFolder + "\\Focal\\Focal_" + ras)

# ---------------------------------------------------------------------------------------------------------------------------------------
#
# ------------------------------------------------------ create contours from tiles -----------------------------------------------------
#
# ---------------------------------------------------------------------------------------------------------------------------------------
# set workspace to the procressed DEM tiles -> create contours -> delete noise -> reduce vertices -> clip to original (unbuffered) footprints -> merge

# if the contour creation loop is interrupted outFootprints need to be redefined. Harcoded by index, use with caution. 
# env.workspace = workingFolder
# outFootprints = os.path.join(workingFolder, arcpy.ListFeatureClasses()[1])

env.workspace = os.path.join(outDEMFolder, "Focal")
procRasSplit = arcpy.ListRasters()[540:]

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
    iterationTime = time.time() - startTime
    print(f"tile completed in {round(iterationTime, 4)} sec")

    # free memory after iteration complete
    del outContour, trimContours, outSimp, outSimpPath, footprintSelector, footprintSelectorPath, clipFootprint, clipContourPath, clipContour

# get loop runtime in seconds after completion
executionTime = time.time() - startTime
print(f"created {len(procRasSplit)} tiles with {interval} ft contour interval in {round(executionTime, 4)} sec ({round(executionTime/len(procRasSplit),4)} sec/tile)")

# merge contours. Handling final clip and reprojection in ArcGIS Pro. 
finalMergePath = os.path.join(contourGDBPath, "_contours" + str(interval) + "_ft")
arcpy.Merge_management(contourMergeList, finalMergePath)
