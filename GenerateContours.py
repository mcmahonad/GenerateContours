
# This script clips batch downloaded DEM tiles to a geographic area of interest and creates contour line tiles from them

# ------------------------------------------------------------------------------------------------------------------------------------

# -------------------------------------------------------------- Notes ---------------------------------------------------------------

# ------------------------------------------------------------------------------------------------------------------------------------

'''
11/10 notes: 
    - Break up lines to improve performance. ArcGIS handles more features better than more vertices. 
        - This was done in the past by erasing annotation bounding boxes from lines to break them up
            - (also creates nice contour annotation)
        - Could also try to reduce vertices in the contour step
    - Read the 2002 contour generalization documentation for generalization tips.
        - generalize line tool trials
        - Try larger cell sizes 

    - Ownership/QC: these would be EE owned files assuming that 2002 contours are also EE owned.
        - Need to make sure datums are being tracked. 
        - Accuracy-wise, these would come with a disclaimer
        - Would wind up in SDE, so vtpk not an option. 

Roadmap: 
    - try larger cell sizes and generalize for smoothing. Remove smooth line.
    - try line splitting methodology listed above
    - need to add tile clipping
    - try final merge with reduced vertices
'''
# ------------------------------------------------------------------------------------------------------------------------------------
#
# --------------------------------------------- Imports, set environments/inputs -----------------------------------------------------
#
# ------------------------------------------------------------------------------------------------------------------------------------

import arcpy
from arcpy import env
import pandas as pd
import os
import datetime
from datetime import date

# Prevent file clutter during tests
env.overwriteOutput = True

# Desired smoothing tolerance for PAEK smoothing
smoothToler = "30 feet"

# Desired contour interval in feet
interval = 5

# tile overlap distance in meters. Length > of overlap smoothing for now. 
tileOverlap = "10 meters"

# Set workspace and export locations. Create these directories ahead of time. 

# contains DEM tiles downloaded from VGIN. Script currently configured for .img
RawDEMFolder = ""

# contains overlapping DEM tiles created from the mosaic merge and re-split. 
splitDEMFolder = ""  

# contains working data created by the tile overlaps
workingFolder = ""

# GDB containing working data. Nested under workingFolder. Mosaic dataset must go into a gdb. 
workingDB = 'Working.gdb'
workingGDBPath = workingFolder + "\\" + str(workingDB)

# contains output contours
contourExportLoc = 
contourGDB = 'OverlappingContour_working.gdb'
contourGDBPath = contourExportLoc +"\\"+ str(contourGDB)

# ------------------------------------------------------------------------------------------------------------------------------------
#
# ------------------------------------------------- delete rasters outside of the AOI ------------------------------------------------
#
# ------------------------------------------------------------------------------------------------------------------------------------

# Set workspace to folder containing DEM tiles and create list of rasters
env.workspace = RawDEMFolder

rasList = arcpy.ListRasters()

# No need to run this section after the first run.
'''
# Before running script, create a mosaic dataset in Pro and add DEM tiles. Once generated, select footprints intersecting the Area of interest and export these to the csv below
# The tile names are included in the footprints csv and will be used to delete unwanted tiles. 

# Read downloaded footprints table
footprintTable = pd.read_csv()
# extract tile names and convert to a list. Append raster file extension. 
footprintNames = list(footprintTable['Name'])
footprintNames = [footprint + ".img" for footprint in footprintNames]

# Verify that your rasters match the list of raster names so they aren't deleted accidentally. 
# A little clunky. Better ways to verify than list length. Also is for loop even needed? 
rasLen = []
for ras in rasList:
    if ras in footprintNames:
        rasLen.append(ras)
    else:
        pass

# delete all rasters in the DEM tile folder that aren't listed in the footprints list.
# Also a little clunky
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

# creating contours from the raw VGIN tiles creates gaps at the boundary of each tile and sometimes interpolates poorly along those gaps.
# in order to rectify, overlaps need to be created between tiles so that the contours cover the gaps.
# handle this by merging the tiles, resplit into new tiles with an overlap, create contours, and then clip to original tile boundaries. 

# Create mosaic -> Load datasets to mosaic -> Mosaic to new raster -> Export mosaic dataset geo -> Buffer -> Split raster

# the list of rasters in the workspace should be shorter after deleting unneeded ones.
rasListReduced = arcpy.ListRasters()
# create subset for testing. Remove index if running on whole dataset.  
rasSub = rasListReduced[0:5]

# create mosaic from the remaining tiles and load them in
rasMosaic = arcpy.management.CreateMosaicDataset(workingGDBPath, "workingMosaic_" + str(date.today()), arcpy.Describe(rasSub[0]).spatialReference, 1, "32_BIT_FLOAT")
arcpy.management.AddRastersToMosaicDataset(rasMosaic, "Raster Dataset", rasSub) 

# create footprints of the DEM tiles from the new mosaic
outFootprints = os.path.join(workingFolder, "MergedDEMfootprints_" + str(date.today()))
arcpy.management.ExportMosaicDatasetGeometry(in_mosaic_dataset = rasMosaic, out_feature_class = outFootprints, geometry_type = "FOOTPRINT")

# merge DEM tiles to new ras and buffer them to cover the gaps. Set buffer distance at head
rasMerge = "rasMerge_"+ str(date.today()) +  "_.img"
arcpy.management.MosaicToNewRaster(rasSub, workingFolder, rasMerge, arcpy.Describe(rasSub[0]).spatialReference,"32_BIT_FLOAT", 1, 1)
bufferedFootprints = os.path.join(workingFolder, "Bufferedfootprints_" + str(date.today()))
arcpy.Buffer_analysis(outFootprints + ".shp", bufferedFootprints, tileOverlap, "FULL")

# split raster into overlapping tiles using the buffered footproints.
outNameFormat = "Split_" + str(date.today()).replace("-", "_") + "_"
arcpy.management.SplitRaster(in_raster = os.path.join(workingFolder, rasMerge), out_folder = splitDEMFolder, out_base_name = outNameFormat + "_", split_method = "POLYGON_FEATURES", format = "IMAGINE IMAGE", resampling_type = "BILINEAR", split_polygon_feature_class = bufferedFootprints + ".shp") 

# ---------------------------------------------------------------------------------------------------------------------------------------
#
# ------------------------------------------------------ create contours from tiles -----------------------------------------------------
#
# ---------------------------------------------------------------------------------------------------------------------------------------

env.workspace = splitDEMFolder

# loop fails with dashes in file names. This gets split up above at split raster step. Needed here too?
rasSplit = [ras.replace("-", "_") for ras in arcpy.ListRasters()]
rasSplit = arcpy.ListRasters()

# get start time of loop execution and indicate which tile is being processed. 

startTime = time.time()
counter = 1

for ras in rasSplit:
    f"processing tile {counter} of {len(rasSplit)}"
    outContour = os.path.join(contourGDBPath, "raw_" + ras.split(".")[0])
    arcpy.sa.Contour(in_raster = ras, out_polyline_features = outContour, contour_interval = interval, z_factor = 3.28084)

    # Delete noise - contours under 20 ft length. Select by attribute probably faster than iterating? 

    trimContours = arcpy.management.SelectLayerByAttribute(outContour, "NEW_SELECTION", "shape_Length < 20")
    arcpy.DeleteFeatures_management(trimContours)
    # Smooth contour lines
    outSmooth = os.path.join(contourGDBPath, "smooth_" + ras.split(".")[0])
    arcpy.SmoothLine_cartography(outContour, outSmooth, "PAEK", smoothToler)

    counter = counter + 1
    
# get loop runtime in seconds after completion
executionTime = time.time() - startTime
print("created " + str(len(rasSplit)) + " tiles with " + str(interval) + " ft contour interval in " + str(round(executionTime,4)) +
 " sec (" + str(round(executionTime/len(rasSplit),4)) + " sec/tile)")

# fix this f-string later to replace print
# f"created {len(rasSplit)} tiles with {interval} ft contour interval in {round(executionTime ,4)} sec ({(round(executionTime/len(rasSplit),4)} sec/tile"