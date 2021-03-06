# library imports
import cv2
import math
import numpy as np
import random
import os
import colorsys
import csv

# -------------------------------------------------------------------
# INITIALISE CONSTANTS
# -------------------------------------------------------------------

# focal length in pixels
camera_focal_length_px = 399.9745178222656
# focal length in metres (4.8 mm) 
camera_focal_length_m = 4.8 / 1000
# camera baseline in metres    
stereo_camera_baseline_m = 0.2090607502
# image center point and widths
image_centre_h = 262.0;
image_centre_w = 474.5;
# maximum disparity
max_disparity = 128;
# initial load of stereo processor
stereoProcessor = cv2.StereoSGBM_create(0, max_disparity, 21);
    
# load pre-requisite masks s.t they're ready for when they are needed on an image.
disparity_range = cv2.imread("masks/disparity_cap.png", cv2.IMREAD_GRAYSCALE)
road_threshold_mask = cv2.imread("masks/road_threshold_mask.png", cv2.IMREAD_GRAYSCALE)
car_front_mask = cv2.imread("masks/car_front_mask.png", cv2.IMREAD_GRAYSCALE);
blackImg = cv2.imread("masks/black.png", cv2.IMREAD_GRAYSCALE);
view_range = cv2.imread("masks/view_range.png", cv2.IMREAD_GRAYSCALE);
plane_sample = cv2.imread("masks/plane_sample.png", cv2.IMREAD_GRAYSCALE);
carmask = cv2.bitwise_and(car_front_mask, car_front_mask, mask=view_range)

# -------------------------------------------------------------------
# IMAGE LOADING FUNCTIONS
# -------------------------------------------------------------------

def getImagePaths(filename_l, path_dir_l, path_dir_r):
    # from the left image filename get the correspondoning right image
    filename_right = filename_l.replace("_L", "_R");
    full_path_filename_l = os.path.join(path_dir_l, filename_l);
    full_path_filename_r = os.path.join(path_dir_r, filename_right);
    # check the file is a PNG file (left) and check a corresponding right image actually exists
    if ('.png' in filename_l) and (os.path.isfile(full_path_filename_r)):
        return (full_path_filename_l, full_path_filename_r)
    else:
        return False

def loadImages(image_paths):
    filename_l, filename_r = image_paths
    # RGB images so load both as such
    return (cv2.imread(filename_l), cv2.imread(filename_r))

# -------------------------------------------------------------------
# IMAGE COLOUR MANIPULATION FUNCTIONS
# -------------------------------------------------------------------

def gammaChange(image, gamma=1.0):
    # build a lookup table mapping the pixel values to their adjusted gamma values
    invGamma = 1.0 / gamma
    table = np.array([((i / 255.0) ** invGamma) * 255
        for i in np.arange(0, 256)]).astype("uint8")
    # apply gamma correction using lookup table
    return cv2.LUT(image, table)

def getPointColour(point):
    # to be used on a 3d point cloud with RGB.
    return (point[3], point[4], point[5])

def BGRtoHSVHue(rgb):
    # Converts RGB to HSV.
    r,g,b = rgb
    hue = round(colorsys.rgb_to_hsv(r,g,b)[0], 3)
    # return the hue value as a string.
    return str(hue)

def preProcessImages(imgL,imgR):
    images = [imgL, imgR]
    for i in range(len(images)):
        # adjust gamma on images.
        images[i] = gammaChange(images[i], 1.4)
    # return the left and right image channels.
    return (images[0],images[1])

def greyscale(imgL,imgR):
    # converts images to greyscale.
    images = [imgL, imgR]
    for i in range(len(images)):
        # convert greyscale
        images[i] = cv2.cvtColor(images[i], cv2.COLOR_BGR2GRAY);
        # equalise the histogram to improve greyscale performance
        images[i] = cv2.equalizeHist(images[i])
    return (images[0],images[1])

# -------------------------------------------------------------------
# DISPARITY GENERATION FUNCTIONS
# -------------------------------------------------------------------

# compute disparity image from undistorted and rectified stereo images that we have loaded
# (which for reasons best known to the OpenCV developers is returned scaled by 16)
def disparity(grayL, grayR, max_disparity, crop_disparity):
    # compute disparity image from undistorted and rectified stereo images
    # that we have loaded
    # (which for reasons best known to the OpenCV developers is returned scaled by 16)
    disparity = stereoProcessor.compute(grayL,grayR);
    # filter out noise and speckles (adjust parameters as needed)
    dispNoiseFilter = 5; # increase for more agressive filtering
    cv2.filterSpeckles(disparity, 0, 4000, max_disparity - dispNoiseFilter);
    # scale the disparity to 8-bit for viewing
    # divide by 16 and convert to 8-bit image (then range of values should
    # be 0 -> max_disparity) but in fact is (-1 -> max_disparity - 1)
    # so we fix this also using a initial threshold between 0 and max_disparity
    # as disparity=-1 means no disparity available
    _, disparity = cv2.threshold(disparity,0, max_disparity * 16, cv2.THRESH_TOZERO);
    disparity_scaled = (disparity / 16.).astype(np.uint8);
    # crop disparity to chop out left part where there are with no disparity
    # as this area is not seen by both cameras and also
    # chop out the bottom area (where we see the front of car bonnet)
    if (crop_disparity):
        width = np.size(disparity_scaled, 1);
        disparity_scaled = disparity_scaled[0:390,135:width];
    # display image (scaling it to the full 0->255 range based on the number
    # of disparities in use for the stereo part)
    disparity_scaled = (disparity_scaled * (256. / max_disparity)).astype(np.uint8)
    return disparity_scaled

def disparityCleaning(disparity, option, prev_disp=None):
     # compute disparity filling (for missing data)
    if option == 'previous':
        # load previous disparity to fill in missing content.
        if prev_disp is not None:
            disparity = fillDisparity(disparity, prev_disp)
    elif option == 'mean':
        disparity = fillAltDisparity(disparity)
    return disparity

def fillDisparity(disparity, previousDisparity):
    if previousDisparity is not None:
        ret, mask = cv2.threshold(disparity, 2, 255, cv2.THRESH_BINARY)
        mask = cv2.bitwise_not(mask)
        # Take only region of logo from logo image.
        filling = cv2.bitwise_and(previousDisparity,previousDisparity,mask = mask)
        disparity = cv2.add(disparity,filling)
    return disparity

def fillAltDisparity(disparity):
    # get non-black points in image
    averagePoints = []
    for i in disparity:
        mean = i[i.nonzero()].mean()
        if np.isnan(mean):
            mean = 0.0
        averagePoints.append(mean)
    # fill empty points with the mean.
    for i in range(len(disparity)):
        for j in range(len(disparity[i])):
            if disparity[i][j] < 2:
                disparity[i][j] = averagePoints[i]
    return disparity

def capDisparity(disparity):
    # only keep the road range.
    cv2.bitwise_and(disparity,disparity,mask = disparity_range)
    return disparity

def maskDisparity(disparity):
    # Take only a particular region (remove car parts)
    disparity = cv2.bitwise_and(disparity,disparity,mask = carmask)
    return disparity

# -------------------------------------------------------------------
# 3D CALCULATIONS
# -------------------------------------------------------------------

def projectDisparityTo3d(disparity, max_disparity, rgb=[]):
    # list of points
    points = [];
    f = camera_focal_length_px;
    B = stereo_camera_baseline_m;
    height, width = disparity.shape[:2];

    for y in range(0,height-1, 2): # 0 - height is the y axis index
        for x in range(0,width-1, 2): # 0 - width is the x axis index
            # if we have a valid non-zero disparity
            if (disparity[y,x] > 0):
                # calculate corresponding 3D point [X, Y, Z]
                # stereo lecture - slide 22 + 25
                Z = (f * B) / disparity[y,x];
                X = ((x - image_centre_w) * Z) / f;
                Y = ((y - image_centre_h) * Z) / f;
                if(len(rgb) > 0):
                    points.append([X,Y,Z,rgb[y,x,2], rgb[y,x,1],rgb[y,x,0]]);
                else:
                    points.append([X,Y,Z]);
    return points;

# project a set of 3D points back the 2D image domain
def project3DPointsTo2DImagePoints(points):
    pts = [];
    for i1 in range(len(points)):
        # reverse earlier projection for X and Y to get x and y again
        Z = points[i1][2]
        x = ((points[i1][0] * camera_focal_length_px) / Z) + image_centre_w;
        y = ((points[i1][1] * camera_focal_length_px) / Z) + image_centre_h;
        pts.append([x,y]);
    return pts;

# -------------------------------------------------------------------
# HISTOGRAM FUNCTIONS
# -------------------------------------------------------------------

def calculateColourHistogram(points):
    # get colour points for each point in plane.
    # convert it to greyscale
    colours = [BGRtoHSVHue((pt[3],pt[4],pt[5])) for pt in points]
    # print(colours)
    histogram = {}
    for i in colours:
        if i not in histogram:
            histogram[i] = 1
        else:
            histogram[i] += 1
    return histogram

def filterPointsByHistogram(points, histogram, threshold=100):
    # pythonic expression for filtering points by histogram
    return [x for x in points if histogram[BGRtoHSVHue(getPointColour(x))] > threshold]

def calculateHistogram(img):
    hist = cv2.calcHist([img],[0],None,[256],[0,256])
    return hist

# -------------------------------------------------------------------
# RANSAC
# -------------------------------------------------------------------

def randomNonCollinearPoints(points):
    cross_product_check = np.array([0,0,0]);
    # cross product checks
    cp_check0 = True if cross_product_check[0] == 0 else False
    cp_check1 = True if cross_product_check[1] == 0 else False
    cp_check2 = True if cross_product_check[2] == 0 else False
    
    P1 = None
    P2 = None
    P3 = None

    while cp_check0 and cp_check1 and cp_check2:
        P1 = np.array([x[:3] for x in random.sample(points, 1)])[0]
        P2 = np.array([x[:3] for x in random.sample(points, 1)])[0]
        P3 = np.array([x[:3] for x in random.sample(points, 1)])[0]
        # make sure they are non-collinear
        cross_product_check = np.cross(P1-P2, P2-P3)
        cp_check0 = True if cross_product_check[0] == 0 else False
        cp_check1 = True if cross_product_check[1] == 0 else False
        cp_check2 = True if cross_product_check[2] == 0 else False
    return (P1, P2, P3)

def planarFitting(randomPoints, points):
    # generate random colinear points.
    # Here we choose from the whole point range
    P1, P2, P3 = randomNonCollinearPoints(points)
    # calculate coefficents a,b, and c
    abc = np.dot(np.linalg.inv(np.array([P1,P2,P3])), np.ones([3,1]))
    # calculate coefficents d
    d = math.sqrt(abc[0]*abc[0]+abc[1]*abc[1]+abc[2]*abc[2])
    # make sure we have random points
    if len(randomPoints[0]) > 3:
        randomPoints = [[item[0], item[1], item[2]] for item in randomPoints]
    # measure distance of our random points from plane given 
    # the plane coefficients calculated
    dist = abs((np.dot(randomPoints, abc) - 1)/d)
    return abc, abc, dist

def RANSAC(points, trials):
    # init variables
    bestPlane = (None, None)
    bestError = float("inf")
    # compute plane.
    for i in range(trials):
        # select T data points randomly
        try:
            T = random.sample(points, 600)
            # estimate the plane using this subset of information
            coefficents, normal, dist = planarFitting(T, points)
            error = np.mean(dist)
            # store the results in our dictionary.
            if error < bestError:
                bestPlane = (normal,coefficents)
                bestError = error
        except Exception as e:
            # probably found some random error in terms of singular matrix.
            pass
    # return the best plane.
    return bestPlane

def calculatePointErrors(abc, points):
    # rearrange points s.t we can perform matrix operations on them.
    the_list = []
    for i in points:
        the_list.append([i[0],i[1],i[2]])
    points = np.array(the_list)
    # calculate coefficents d
    d = math.sqrt(abc[0]*abc[0]+abc[1]*abc[1]+abc[2]*abc[2])
    # measure distance of all points from plane given 
    # the plane coefficients calculated
    dist = abs((np.dot(points, abc) - 1)/d)
    # return a matrix of results
    return dist

def computePlanarThreshold(points,differences,threshold=0.01):
    """
    Discards points on the disparity where it is not within the plane.
    """
    new_points = []
    for i in range(len(points)):
        # we only keep points that are within the threshold.
        if differences[i] < threshold:
            new_points.append(points[i])
    return new_points

# -------------------------------------------------------------------
# POST RANSAC POINT COLOURING & FILTERING
# automatically adjusting the parameters initial region of interest extraction or image prefiltering based on some form of preliminary analysis image
# -------------------------------------------------------------------

def removeSmallParticles(image, threshold=20):
    _, contours, _= cv2.findContours(image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for spectacle in contours:
        area = cv2.contourArea(spectacle)
        if area < threshold:
            # its most likely a particle, colour it black.
            cv2.drawContours(image,[spectacle],0,0,-1)
    return image

def generatePointsAsImage(points):
    img = blackImg.copy()
    # draw points on image.
    for i in points:
        img[i[0][1]][i[0][0]] = 255
    return img

def sanitiseRoadImage(img, size):
    (height, width) = size
    referenceImg = img.copy()
    # perform closing on the image to fill holes
    kernel = np.ones((9,9),np.uint8)
    img = cv2.morphologyEx(img, cv2.MORPH_CLOSE, kernel)
    # erode a little bit.
    img = cv2.erode(img,kernel,iterations = 2)
    # put a threshold for the road points (used for convex hull purposes)
    img = cv2.bitwise_and(img,img,mask = road_threshold_mask)
    img = cv2.morphologyEx(img, cv2.MORPH_CLOSE, kernel)
    # remove small particles manually
    img = ParticleCleansing(img)
    pts = []
    for i in range(height):
        for j in range(width):
            if img[i][j] != 0:
                k = [j,i]
                pts.append(k)
    pts = np.matrix(pts)
    return img, pts

def generatePlaneShape(points, copy):
    img = cv2.cvtColor(copy,cv2.COLOR_BGR2GRAY)
    img[:] = 0
    for i in points:
        img[i[0][1]][i[0][0]] = 255
    kernel = np.ones((5,5),np.uint8)
    img = cv2.erode(img,kernel,iterations = 1)
    img = ParticleCleansing(img)
    return img

def ParticleCleansing(image):
	_, contours, _= cv2.findContours(image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
	for spot in contours:
		area = cv2.contourArea(spot)
		if area < 70:
			cv2.drawContours(image,[spot],0,255,-100)
	return image

# -------------------------------------------------------------------
# CONTOURS AND NORMAL LINES
# -------------------------------------------------------------------

def drawRoadLine(image, points):
    # generate convex hull
    hull = cv2.convexHull(points)
    # draw hull on image
    return (cv2.drawContours(image,[hull],0,(0,0,255),5), hull)

def getNormalVectorLine(basePoint, abc, disparity):
    # basepoint is x,y
    x,y = basePoint
    f = camera_focal_length_px;
    B = stereo_camera_baseline_m;
    # calculate X,Y,Z
    Z = (f * B) / disparity[y,x];
    X = ((x - image_centre_w) * Z) / f;
    Y = ((y - image_centre_h) * Z) / f;
    # increment Y.
    newY = Y - 0.7
    newX = X + 0.0
    # calculate D
    d = math.sqrt(abc[0]*abc[0]+abc[1]*abc[1]+abc[2]*abc[2])
    # calculate new Z
    Z = d - ((abc[0] * newX) + (abc[1]*newY))
    # convert points back to 2D
    newX = ((newX * camera_focal_length_px) / Z) + image_centre_w;
    newY = ((newY * camera_focal_length_px) / Z) + image_centre_h;
    results = (int(newX), int(newY))
    return results

def getCenterPoint(points):
    # calculate the centre point from the points from the hull
    (x,y),_ = cv2.minEnclosingCircle(points)
    return (int(x),int(y))

# plotting of the planar normal direction direction glyph / vector in the image
def drawNormalLine(baseImage, center, normal, disparity):
    newLine = getNormalVectorLine(center, normal, disparity)
    lineThickness = 2
    normalLineColor = (204,185,22)
    cv2.line(baseImage, center, newLine, normalLineColor, lineThickness)
    circleHeadColour = (normalLineColor[0]+10, normalLineColor[1]+10, normalLineColor[2]+10)
    cv2.circle(baseImage, newLine, 2, circleHeadColour, thickness=10, lineType=8, shift=0)
    return baseImage

# -------------------------------------------------------------------
# MISC
# -------------------------------------------------------------------

def printFilenamesAndNormals(filename_l, normal):
    normalString = "(0,0,0)"
    nd = 1/math.sqrt(normal[0]*normal[0]+normal[1]*normal[1]+normal[2]*normal[2])

    if normal is not None:
        normalString = "("+str(round(nd*normal[0][0],4))+", " + str(round(nd*normal[1][0],4))+", " + str(round(nd*normal[2][0],4))+")"

    filename_r = filename_l.replace("_L", "_R")
    print(filename_l);
    print(filename_r + " - Road Surface Normal:" + normalString)

def getBlackImage():
    # returns a black image (the size of our reference image)
    return blackImg

def resizeImage(image, height, width):
    image = cv2.resize(image, (width, height))
    return image

def batchImages(imgList, size):
    # for each image, resize them.
    counts = len(imgList)

    # resize all images s.t they all fit accordingly.
    images = []
    for i in imgList:
        fixedScaleImg = resizeImage(i[1], size[0], size[1])
        # check if greyscale
        dim = len(fixedScaleImg.shape)
        if dim != 3:
            # convert to colour.
            fixedScaleImg = cv2.cvtColor(fixedScaleImg, cv2.COLOR_GRAY2BGR)
        # add to list.
        images.append(fixedScaleImg)
        
    if counts == 1:
        return images[0]
    if counts == 2:
        stack = np.hstack((images[0], images[1]))
        return cv2.resize(stack, (0,0), fx=0.5, fy=0.5) 
    if counts == 3:
        p1 = np.hstack((images[0], images[1]))
        p2 = np.hstack((images[2], images[2]))
        stack = np.vstack((p1, p2))
        return cv2.resize(stack, (0,0), fx=0.5, fy=0.5) 
    if counts == 4:
        p1 = np.hstack((images[0], images[1]))
        p2 = np.hstack((images[2], images[3]))
        stack = np.vstack((p1, p2))
        return cv2.resize(stack, (0,0), fx=0.5, fy=0.5)
    if counts == 4:
        p1 = np.hstack((images[0], images[1]))
        p2 = np.hstack((images[2], images[3]))
        stack = np.vstack((p1, p2))
        return cv2.resize(stack, (0,0), fx=0.5, fy=0.5)
    if counts == 5:
        p1 = np.hstack((images[0], images[1]))
        p2 = np.hstack((images[2], images[3]))
        stack = np.vstack((p1, p2))
        l = cv2.resize(stack, (0,0), fx=0.25, fy=0.25)
        r =  cv2.resize(images[4], (0,0), fx=0.5, fy=0.5)
        r = np.hstack((l, r))
        return r
    else:
        pass

def handleKey(cv2, pause_playback, disparity_scaled, imgL, imgR, crop_disparity):
    # keyboard input for exit (as standard), save disparity and cropping
        # exit - x
        # save - s
        # crop - c
        # pause - space
    # wait 40ms (i.e. 1000ms / 25 fps = 40 ms)
    key = cv2.waitKey(2 * (not(pause_playback))) & 0xFF;
    if (key == ord('s')):     # save
        cv2.imwrite("sgbm-disparty.png", disparity_scaled);
        cv2.imwrite("left.png", imgL);
        cv2.imwrite("right.png", imgR);
    elif (key == ord('c')):     # crop
        crop_disparity = not(crop_disparity);
    elif (key == ord(' ')):     # pause (on next frame)
        pause_playback = not(pause_playback);
    elif (key == ord('x')):       # exit
        raise ValueError("exiting manually")