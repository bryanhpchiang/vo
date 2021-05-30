# Initial test for factor graph optimization
# Not incremental

from pathlib import Path

import cv2
import gtsam
import jax
import jax.numpy as jnp
import matplotlib.pyplot as plt
import numpy as onp
import pandas as pd
from gtsam import symbol
from gtsam.utils import plot
from IPython import embed
from mpl_toolkits import mplot3d
import inspect

import calib

# Show plots
show = False

from gtsam.utils import plot


def _load_text(p):
    with open(p, "r") as f:
        return [x.strip() for x in f.readlines()]


def _load_image(p):
    img = cv2.imread(str(data_path / p), cv2.IMREAD_GRAYSCALE)
    # img = onp.float32(img) / 255
    return img


poses_path = "/media/bryan/shared/kitti2/dataset/poses/00.txt"
poses = []
for l in _load_text(poses_path):
    poses.append(jnp.array([float(x) for x in l.split(" ")]).reshape((3, 4)))
poses = jnp.array(poses)
print(f"{poses.shape = }")
gt_positions = jnp.array([x[:, -1] for x in poses])

data_path = Path("/media/bryan/shared/kitti2/dataset/sequences/00")
calib_path = data_path / "calib.txt"
times_path = data_path / "times.txt"

left_img_paths = _load_text(data_path / "left_imgs.txt")
left_img_paths = [data_path / "image_0" / x for x in left_img_paths]

right_img_paths = _load_text(data_path / "right_imgs.txt")
right_img_paths = [data_path / "image_1" / x for x in right_img_paths]
times = _load_text(times_path)  # In seconds
times = [float(x) for x in times]

num_imgs = len(left_img_paths)
assert len(left_img_paths) == len(right_img_paths)
assert len(left_img_paths) == len(times)

left_path = left_img_paths[0]
right_path = right_img_paths[0]

left = _load_image(left_path)
right = _load_image(right_path)

# embed()

fig, axs = plt.subplots(nrows=1, ncols=2)
axs[0].imshow(left)
axs[0].set_title("left")
axs[1].imshow(right)
axs[1].set_title("right")
if show:
    plt.show()

# Extract disparity
window_size = 5
min_disp = 0
num_disp = 64

stereo = cv2.StereoSGBM_create(minDisparity=min_disp,
                               numDisparities=num_disp,
                               blockSize=16,
                               P1=8 * 3 * window_size**2,
                               P2=8 * 3 * window_size**2,
                               disp12MaxDiff=1,
                               uniquenessRatio=10,
                               speckleWindowSize=100,
                               speckleRange=32)

# Convert to pixel-level disparity
disparity = stereo.compute(left, right) / 16.0

plt.figure()
plt.title("initial disparity")
plt.imshow(disparity)

if show:
    plt.show()

# Verify results
x = 800
y = 300
fig, axs = plt.subplots(nrows=1, ncols=2)
axs[0].imshow(left)
axs[0].set_title("left")
axs[0].scatter(x, y, c='r')

axs[1].imshow(right)
axs[1].set_title("right")
axs[1].scatter(x, y, c='c', label="original")
axs[1].scatter(x - disparity[y, x], y, c='r', label="adjusted")
plt.legend()
if show:
    plt.show()

# embed()

# Find point features
corners = cv2.goodFeaturesToTrack(left,
                                  maxCorners=500,
                                  qualityLevel=0.3,
                                  minDistance=50)
corners = onp.squeeze(corners).astype(int)

disparity_corners = disparity[corners[:, 1], corners[:, 0]]

# embed()
valid = disparity_corners > 10
disparity_corners = disparity_corners[valid]
corners = corners[valid]

fig, axs = plt.subplots(nrows=1, ncols=2)
axs[0].imshow(left)
axs[0].set_title("corners on left")
axs[0].scatter(corners[:, 0], corners[:, 1], c='r')

axs[1].imshow(right)
axs[1].set_title("corners on right")
axs[1].scatter(corners[:, 0], corners[:, 1], c='c', label="original")
axs[1].scatter(corners[:, 0] - disparity_corners,
               corners[:, 1],
               c='r',
               label="adjusted")
plt.legend()
if show:
    plt.show()

# Back project to 3D for the left camera
P0, P1 = calib._load_calib(calib_path)

# Calculate depth
cx = P0[0, 2]
cy = P0[1, 2]
fx_px = P0[0, 0]
fy_px = P0[1, 1]  # fx = fy for KITTI
baseline_px = P1[0, 3]
baseline_m = 0.54

z = (fx_px * baseline_m) / disparity_corners

# Camera coordinate system is as follows
# z pointing into the screen
# ------> x
# |
# |
# v
# y

# Calculate x, y coordinates
bp_x = (corners[:, 0] - cx) * (z / fx_px)
bp_y = (corners[:, 1] - cy) * (z / fy_px)
bp_z = z

# Plot backprojection results (2D)
fig, axs = plt.subplots(nrows=2, ncols=1)

im = axs[0].scatter(corners[:, 0], corners[:, 1], c=bp_z)
axs[0].invert_yaxis()
fig.colorbar(im, ax=axs[0])
axs[0].set_title("x, y")
axs[0].set_aspect('equal', adjustable='box')

axs[1].scatter(bp_x, bp_y, c=bp_z)
axs[1].invert_yaxis()
axs[1].set_title("after back projection")
axs[1].set_aspect('equal', adjustable='box')

if show:
    plt.show()

# Plot backprojected result in 3D
fig = plt.figure()
ax = plt.axes(projection='3d')
# ax.set_aspect('equal')

ax.scatter3D(corners[:, 0], corners[:, 1], bp_z, c=bp_z)
ax.set_xlabel('x')
ax.set_ylabel('y')
ax.set_zlabel('z')
ax.invert_xaxis()
ax.invert_zaxis()
ax.set_title("image x, y with depth")

# Set aspect ratio (space out the z-axis to see the depth more clearly)
ax.set_box_aspect(
    (onp.ptp(corners[:, 0]), onp.ptp(corners[:, 1]), 5 * onp.ptp(bp_z)))

if show:
    plt.show()

fig = plt.figure()
ax = plt.axes(projection='3d')
ax.scatter3D(bp_x, bp_y, bp_z, c=bp_z)
ax.set_xlabel('x')
ax.set_ylabel('y')
ax.set_zlabel('z')
ax.invert_xaxis()
ax.invert_zaxis()
ax.set_title("backprojected x, y with depth")

# Set aspect ratio (space out the z-axis to see the depth more clearly)
ax.set_box_aspect(
    (onp.ptp(corners[:, 0]), onp.ptp(corners[:, 1]), 5 * onp.ptp(bp_z)))

if show:
    plt.show()

# Observation model (project 3D points down to 2D)
# 4 x N
features = onp.vstack((bp_x, bp_y, bp_z)).T
num_features = len(features)
projected_features = P0 @ onp.append(
    features, onp.ones((num_features, 1)), axis=1).T  # 3 x N
# Normalize by homogenous coordinate
projected_features = (projected_features / projected_features[-1]).T
projected_features = round(projected_features[:, :2])
onp.testing.assert_allclose(corners, projected_features)

plt.figure()
plt.imshow(left)
plt.scatter(projected_features[:, 0],
            projected_features[:, 1],
            c='r',
            label="reprojected features")
plt.legend()
if show:
    plt.show()

plt.close('all')

#  - For simplicity this example is in the camera's coordinate frame
#  - X: right, Y: down, Z: forward
#  - Pose x1 is at the origin, Pose 2 is 1 meter forward (along Z-axis)
#  - x1 is fixed with a constraint, x2 is initialized with noisy values
#  - No noise on measurements


def _xsym(idx):
    return symbol(ord('x'), idx)


def _lsym(idx):
    return symbol(ord('l'), idx)


# Start the loop - add more factors for future poses
first_idx = 0
start_idx = first_idx + 1
num_frames = 15

## Create graph container and add factors to it
graph = gtsam.NonlinearFactorGraph()

## add a constraint on the starting pose
first_pose = gtsam.Pose3()
graph.add(gtsam.NonlinearEqualityPose3(_xsym(first_idx), first_pose))

## Create realistic calibration and measurement noise model
# format: fx fy skew cx cy baseline
K = gtsam.Cal3_S2Stereo(fx_px, fy_px, 0, cx, cy, baseline_m)
stereo_model = gtsam.noiseModel_Diagonal.Sigmas(onp.array([1.0, 1.0, 1.0]))

## Create initial estimate for camera poses and landmarks
initialEstimate = gtsam.Values()
initialEstimate.insert(_xsym(first_idx), first_pose)

# relinearizeInterval = 1
# isam = gtsam.NonlinearISAM(relinearizeInterval)
isam = gtsam.ISAM2()

for i in range(num_features):
    uL, v = corners[i]
    x, y, z = features[i]
    d = disparity_corners[i]
    uR = uL - d
    graph.add(
        gtsam.GenericStereoFactor3D(gtsam.StereoPoint2(uL, uR,
                                                       v), stereo_model,
                                    _xsym(first_idx), _lsym(i), K))
    initialEstimate.insert(_lsym(i), gtsam.Point3(x, y, z))
print("Created factors for initial pose")

# Set up optical flow
old_left = left
points = corners
status = onp.ones(num_features)

# status = 1 if we should track be tracking a feature in the optical flow, otherwise 0.
# Once status goes to 0, we should no longer track that feature in the future since the accuracy
# of the previous position can no longer be relied upon.

lk_params = dict(
    winSize=(15, 15),
    maxLevel=2,
    criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03),
)
img_w, img_h = (1241, 376)
new_feature_threshold = 30
velocity = 2

isam.update(graph, initialEstimate)
result = isam.calculateEstimate()

embed()

# Utility functions


def _predict_next_pose(pose):
    """
    Estimate the next camera pose.
    Simple constant velocity motion model.
    We assume same rotation as before, we're moving forward by 1 meter
    The z-axis represents the direction forward.
    """
    rot = pose.rotation()
    new_pos = pose.transformFrom(gtsam.Point3(0, 0, velocity))
    return gtsam.Pose3(rot, new_pos)


def _find_new_points(left,
                     points,
                     status,
                     disparity,
                     show=False,
                     title="new points"):
    """
    left: image to find new points in.
    points: existing points in the points.
    disparity: disparity of current stereo pair.
    """
    corners = cv2.goodFeaturesToTrack(left,
                                      maxCorners=500,
                                      qualityLevel=0.3,
                                      minDistance=50)
    corners = onp.squeeze(corners).astype(int)
    disparity_corners = disparity[corners[:, 1], corners[:, 0]]
    valid = disparity_corners > 10
    disparity_corners = disparity_corners[valid]
    corners = corners[valid]

    good_current_points = points[status == 1]
    bad_current_points = points[status == 0]

    # We want to find new points. The distance to existing **good** points > 50.
    new_points = []
    for c in corners:
        dist = onp.linalg.norm(good_current_points - c, axis=1)
        closest = onp.min(dist)
        if closest > new_feature_threshold:
            new_points.append(c)
    new_points = onp.array(new_points)

    if show:
        plt.figure()
        plt.imshow(left)
        plt.scatter(good_current_points[:, 0],
                    good_current_points[:, 1],
                    c='xkcd:pale lilac',
                    edgecolors='b',
                    label="good current")
        plt.scatter(bad_current_points[:, 0],
                    bad_current_points[:, 1],
                    c='w',
                    label="bad current")
        plt.scatter(new_points[:, 0],
                    new_points[:, 1],
                    c='xkcd:bright red',
                    label="new points")
        plt.title(title)
        plt.legend()
        plt.show()

    return new_points


def _plot_points(left, points, status):
    plt.figure()
    good = points[status == 1]
    bad = points[status == 0]
    plt.imshow(left)
    plt.scatter(good[:, 0], good[:, 1], c='m', label="tracked")
    plt.scatter(bad[:, 0], bad[:, 1], c='w', label="bad")
    plt.legend()
    plt.show()


def _get_pose(result, idx):
    return result.atPose3(_xsym(idx))


for i in range(start_idx, start_idx + num_frames):
    # Update iSAM with new factors
    graph = gtsam.NonlinearFactorGraph()
    initialEstimate = gtsam.Values()

    # Initial estimate for pose at current frame
    prev_pose = _get_pose(result, i - 1)
    cur_pose_estimate = _predict_next_pose(prev_pose)
    initialEstimate.insert(_xsym(i), cur_pose_estimate)

    # Add stereo factors
    left_path = left_img_paths[i]
    right_path = right_img_paths[i]

    left = _load_image(left_path)
    right = _load_image(right_path)

    # Track features
    # We only want to track old points that were successfully tracked in the previous frame.
    inds_to_track = onp.argwhere(status == 1).flatten()
    points_to_track = points[inds_to_track]
    points_to_track = onp.float32(points_to_track).reshape((-1, 1, 2))
    p1, st, err = cv2.calcOpticalFlowPyrLK(
        old_left,  #
        left,
        points_to_track,
        None,
        **lk_params)

    st = st.flatten()
    p1 = onp.int32(p1.reshape((-1, 2)))
    tracked_inds = inds_to_track[st == 1]
    untracked_inds = inds_to_track[st == 0]

    print(f"Number good features for frame = {len(tracked_inds)}")
    print(f"Number of missed features for frame = {len(untracked_inds)}")

    # Update status of points that we were unable to track
    status[untracked_inds] = 0
    tracked_points = p1[st == 1]
    points[tracked_inds] = tracked_points
    old_left = left  # Update old frame

    print(f"Total missed = {len(jnp.argwhere(status == 0))}")

    if show:
        embed()
        _plot_points(left, points, status)

    disparity = stereo.compute(left, right) / 16.0

    for j in range(len(points)):
        # Only add factors for good features
        if status[j] == 0:
            continue

        # In bounds
        uL, v = points[j]
        uL = onp.clip(uL, 0, img_w - 1)
        v = onp.clip(v, 0, img_h - 1)

        d = disparity[v, uL]

        uR = uL - d
        uR = onp.clip(uR, 0, img_w - 1)
        graph.add(
            gtsam.GenericStereoFactor3D(gtsam.StereoPoint2(uL, uR, v),
                                        stereo_model, _xsym(i), _lsym(j), K))

    # Calculate best estimate
    print(f"i = {i}")
    if i == 12:
        embed()
    isam.update(graph, initialEstimate)
    result = isam.calculateEstimate()
    print("Done")

    # ==== Add new features ====
    continue
    if i % 10 != 0:
        continue

    graph = gtsam.NonlinearFactorGraph()
    initialEstimate = gtsam.Values()

    cur_pose_smoothed = _get_pose(result, i)
    new_points = _find_new_points(left,
                                  points,
                                  status,
                                  disparity,
                                  show=False,
                                  title=f"new points for frame {i}")
    new_points = new_points[:5]

    num_new_points = len(new_points)
    for j in range(num_new_points):
        landmark_symbol = _lsym(len(points) + j)
        uL, v = new_points[j]
        d = disparity[v, uL]
        uR = uL - d

        # Careful with indexing of new points!
        graph.add(
            gtsam.GenericStereoFactor3D(gtsam.StereoPoint2(uL, uR,
                                                           v), stereo_model,
                                        _xsym(i), landmark_symbol, K))

        # Retrieve depth from disparity
        z = (fx_px * baseline_m) / d

        # Backproject
        x = (uL - cx) * (z / fx_px)
        y = (uR - cy) * (z / fy_px)

        initialEstimate.insert(landmark_symbol, gtsam.Point3(x, y, z))

    # Extend points
    points = onp.vstack((points, new_points))
    status = onp.hstack((status, onp.ones(num_new_points)))

    # Adding 5 new landmarks - remove oldest 5 landmarks
    print("Adding new points")
    isam.update(graph, initialEstimate)
    # embed()

factor_indices = gtsam.FactorIndices()
factor_indices.push_back(0)
isam.update(gtsam.NonlinearFactorGraph(), gtsam.Values(), factor_indices)
embed()
plot.plot_3d_points(1, result)
plot.plot_trajectory(1, result)
plot.set_axes_equal(1)
plt.show()