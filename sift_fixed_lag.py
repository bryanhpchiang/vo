"""
Incremental fixed lag smoother with SIFT features.
"""

from pathlib import Path
from re import A

import cv2
import gtsam
import jax
from jax.dtypes import dtype
from jax.interpreters.xla import prefetch
import jax.numpy as jnp
import matplotlib.pyplot as plt
import numpy as onp
import pandas as pd
from gtsam import symbol
from gtsam.utils import plot
from IPython import embed
from mpl_toolkits import mplot3d
import gtsam_unstable
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

# Copied from someone else
stereo = cv2.StereoSGBM_create(minDisparity=min_disp,
                               numDisparities=num_disp,
                               blockSize=9,
                               P1=8 * 9 * 9,
                               P2=32 * 9 * 9,
                               disp12MaxDiff=1,
                               preFilterCap=63,
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

# Find point features
corners = cv2.goodFeaturesToTrack(left,
                                  maxCorners=500,
                                  qualityLevel=0.5,
                                  minDistance=150)
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


def X(idx):
    return symbol(ord('x'), idx)


def L(idx):
    return symbol(ord('l'), idx)


# Start the loop - add more factors for future poses
first_idx = 0
start_idx = first_idx + 1
num_frames = 150

lag = 5
incremental = False

if incremental:
    smoother = gtsam_unstable.IncrementalFixedLagSmoother(lag)
else:
    smoother = gtsam_unstable.BatchFixedLagSmoother(lag)

new_factors = gtsam.NonlinearFactorGraph()
new_values = gtsam.Values()
new_timestamps = gtsam_unstable.FixedLagSmootherKeyTimestampMap()

## Create realistic calibration and measurement noise model
# format: fx fy skew cx cy baseline
K = gtsam.Cal3_S2Stereo(fx_px, fy_px, 0, cx, cy, baseline_m)
prior_mean = gtsam.Pose3()
prior_noise = gtsam.noiseModel_Isotropic.Sigma(6, 0.1)
stereo_model = gtsam.noiseModel_Diagonal.Sigmas(onp.array([1.0, 1.0, 1.0]))

new_factors.push_back(
    gtsam.PriorFactorPose3(X(first_idx), prior_mean, prior_noise))
new_values.insert(X(first_idx), prior_mean)


def _timestamp(key, t):
    return gtsam_unstable.FixedLagSmootherKeyTimestampMapValue(key, t)


new_timestamps.insert(_timestamp(X(first_idx), 0.0))

if False:
    # We're using SIFT now, now this Shi-Tomasi garbage
    for i in range(num_features):
        uL, v = corners[i]
        x, y, z = features[i]
        d = disparity_corners[i]
        uR = uL - d
        new_factors.add(
            gtsam.GenericStereoFactor3D(gtsam.StereoPoint2(uL, uR, v),
                                        stereo_model, X(first_idx), L(i), K))
        new_values.insert(L(i), gtsam.Point3(x, y, z))
        # Timestamp - the time of the frame at which the landmark inserted
        if False:
            new_timestamps.insert(_timestamp(L(i), 0.0))


def _update_smoother(new_factors, new_values, new_timestamps):
    """
    Impure update.
    """
    try:
        smoother.update(new_factors, new_values, new_timestamps)
    except Exception as e:
        print("rip update")
        print(e)
        embed()

    result = smoother.calculateEstimate()
    new_timestamps.clear()
    new_values.clear()
    new_factors.resize(0)
    return result


print("Created factors for initial pose.")
result = _update_smoother(new_factors, new_values, new_timestamps)

# Store the final poses / landmark positions
final_result = gtsam.Values()

# Set up optical flow
"""
status = 1 if we should track be tracking a feature in the optical flow, otherwise 0.
Once status goes to 0, we should no longer track that feature in the future since the accuracy
of the previous position can no longer be relied upon.
"""

img_w, img_h = (1241, 376)
velocity = 2

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


def _plot_points(left, points, status):
    plt.figure()
    good = points[status == 1]
    bad = points[status == 0]
    plt.imshow(left)
    plt.scatter(good[:, 0], good[:, 1], c='m', label="tracked")
    plt.scatter(bad[:, 0], bad[:, 1], c='w', label="bad")
    plt.legend()
    plt.show()


def _get_pose(result, key):
    return result.atPose3(key)


def _merge(a, b):
    """
    Add / update all items in b to a.
    """
    keys = b.keys()
    for i in range(keys.size()):
        k = keys.at(i)
        # Try to retrieve point or pose
        try:
            v = b.atPose3(k)
        except:
            v = b.atPoint3(k)

        # Update if exists, otherwise insert
        if a.exists(k):
            a.update(k, v)
        else:
            a.insert(k, v)


def _detect_keypoints(img):
    kp, des = sift.detectAndCompute(img, None)
    pts = onp.array([x.pt for x in kp])
    pts_unique, inds = onp.unique(pts, axis=0, return_index=True)
    print(f"num before = {len(kp)}, num unique = {len(pts_unique)}")
    kp_unique = list(onp.array(kp)[inds])
    des_unique = des[inds]
    return kp_unique, des_unique


# Initiate SIFT detector
sift = cv2.SIFT_create(200)
kp1, des1 = _detect_keypoints(left)
print(len(kp1))
embed()

# find the keypoints and descriptors with SIFT
old_left = left
old_right = right

num_landmarks = 0
frame_point2landmarks = {first_idx: {}}

for i in range(start_idx, start_idx + num_frames):
    t = times[i]
    print(f"frame = {i}, time = {t}")

    # Initial estimate for pose at current frame
    previous_key = X(i - 1)
    current_key = X(i)

    previous_pose = _get_pose(result, previous_key)
    current_pose_estimate = _predict_next_pose(previous_pose)

    # # Estimate current pose + add timestamp
    new_values.insert(X(i), current_pose_estimate)
    new_timestamps.insert(_timestamp(X(i), t))

    left_path = left_img_paths[i]
    right_path = right_img_paths[i]

    left = _load_image(left_path)
    right = _load_image(right_path)

    kp2, des2 = _detect_keypoints(left)

    FLANN_INDEX_KDTREE = 1
    index_params = dict(algorithm=FLANN_INDEX_KDTREE, trees=5)
    search_params = dict(checks=50)
    flann = cv2.FlannBasedMatcher(index_params, search_params)
    matches = flann.knnMatch(des1, des2, k=2)
    # store all the good matches as per Lowe's ratio test.
    good = []
    for m, n in matches:
        if m.distance < 0.7 * n.distance:
            good.append(m)
    src_pts = onp.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 2)
    dst_pts = onp.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 2)

    print(len(src_pts), len(dst_pts))

    _, inds = onp.unique(dst_pts, axis=0, return_index=True)

    src_pts = src_pts[inds]
    dst_pts = dst_pts[inds]

    print("filter dst unique")
    print(len(src_pts), len(dst_pts))

    _, inds = onp.unique(src_pts, axis=0, return_index=True)

    src_pts = src_pts[inds]
    dst_pts = dst_pts[inds]

    print("filter src unique")
    print(len(src_pts), len(dst_pts))

    # M, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
    # mask = mask.flatten()
    mask = onp.ones(len(src_pts))

    if show:
        matchesMask = mask.ravel().tolist()
        draw_params = dict(
            matchColor=(0, 255, 0),  # draw matches in green color
            singlePointColor=None,
            matchesMask=matchesMask,  # draw only inliers
            flags=2)
        img3 = cv2.drawMatches(old_left, kp1, left, kp2, good, None,
                               **draw_params)
        plt.imshow(img3, 'gray')
        plt.show()

    good_src_pts = src_pts[mask == 1].reshape((-1, 2))
    good_dst_pts = dst_pts[mask == 1].reshape((-1, 2))

    print(f"num matches = {len(good_src_pts)}")

    # Match features from frame i-1 to frame i
    old_point2landmark = frame_point2landmarks[i - 1]
    current_point2landmark = {}

    print(f"num landmarks = {num_landmarks}")
    num_hit = 0

    disparity = stereo.compute(left, right) / 16.0
    # Add more stereo factors
    for j in range(len(good_dst_pts)):
        old_x, old_y = good_src_pts[j]
        x, y = good_dst_pts[j]

        uL = x
        v = y
        d = disparity[int(v), int(uL)]

        # If we're missing disparity, just ignore it
        if d < 10:
            continue

        uR = uL - d
        landmark_idx = None

        # Check if old point associated with existing landmark
        if (old_x, old_y) in old_point2landmark:
            landmark_idx = old_point2landmark[(old_x, old_y)]
            num_hit += 1
            current_point2landmark[(x, y)] = landmark_idx

            # Add new factor for new frame to existing landmark
            new_factors.add(
                gtsam.GenericStereoFactor3D(gtsam.StereoPoint2(uL, uR, v),
                                            stereo_model, current_key,
                                            L(landmark_idx), K))
        else:
            if i % 10 != 1:
                continue

            # This is a new landmark
            if (x, y) in current_point2landmark:
                print("fucked")
                embed()
            landmark_idx = num_landmarks
            print(f"new landmark, landmark idx = {landmark_idx}")
            num_landmarks += 1
            current_point2landmark[(x, y)] = landmark_idx

            # Insert new factor
            new_factors.add(
                gtsam.GenericStereoFactor3D(gtsam.StereoPoint2(uL, uR, v),
                                            stereo_model, current_key,
                                            L(landmark_idx), K))

            # Retrieve depth from disparity
            z = (fx_px * baseline_m) / d

            # Backproject
            x = (uL - cx) * (z / fx_px)
            y = (uR - cy) * (z / fy_px)

            # Insert estimate
            landmark_view = gtsam.Point3(x, y, z)
            landmark_world = current_pose_estimate.transformFrom(landmark_view)
            new_values.insert(L(landmark_idx), landmark_world)

    print(f"num landmarks in previous frame = {len(old_point2landmark)}")
    print(f"num hit from previous frame = {num_hit}")
    if len(old_point2landmark) > 0:
        print(f"percentage = {num_hit / len(old_point2landmark)}")
    print(f"num of new landmarks = {len(current_point2landmark)}")
    print(f"total num landmarks = {num_landmarks}")
    frame_point2landmarks[i] = current_point2landmark

    old_left = left
    old_right = right

    kp1 = kp2
    des1 = des2

    # Update smoother
    print("Updating smoother...")
    # embed()
    result = _update_smoother(new_factors, new_values, new_timestamps)
    print("Estimated pose", _get_pose(result, current_key))

    # Update final result since we're doing fixed-lag smoothing
    _merge(final_result, result)

embed()
plot.plot_3d_points(1, final_result)
plot.plot_trajectory(1, final_result)
plot.set_axes_equal(1)
plt.show()

positions = []
for i in range(first_idx, start_idx + num_frames):
    pose = _get_pose(final_result, X(i))
    pos = pose.translation()
    positions.append([pos.x(), pos.y(), pos.z()])
positions = onp.array(positions)

plt.figure()
plt.plot(positions[:, 0], positions[:, 2], label="estimated")
plt.plot(gt_positions[:start_idx + num_frames, 0],
         gt_positions[:start_idx + num_frames, 2],
         label="ground truth")
plt.xlabel("x")
plt.ylabel("z")
plt.title("batch fixed lag smoothing")
plt.gca().set_aspect('equal')
plt.legend()
plt.show()