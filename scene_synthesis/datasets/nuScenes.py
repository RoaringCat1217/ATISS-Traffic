import math
import torch
from torch.utils.data import Dataset
import numpy as np
import os
import cv2
from pyquaternion import Quaternion
from nuscenes.map_expansion.map_api import NuScenesMap
from nuscenes.nuscenes import NuScenes
from nuscenes.utils.geometry_utils import BoxVisibility
from .utils import get_homogeneous_matrix, cartesian_to_polar


class NuScenesDataset(Dataset):
    layer_names = ['drivable_area',
                   'ped_crossing',
                   'walkway']
    Q = 0
    PEDESTRIAN = 1
    BICYCLIST = 2
    VEHICLE = 3
    END = 4
    category_mapping = {'human.pedestrian.adult': PEDESTRIAN,
                        'human.pedestrian.child': PEDESTRIAN,
                        'human.pedestrian.wheelchair': PEDESTRIAN,
                        'human.pedestrian.stroller': PEDESTRIAN,
                        'human.pedestrian.personal_mobility': PEDESTRIAN,
                        'human.pedestrian.police_officer': PEDESTRIAN,
                        'human.pedestrian.construction_worker': PEDESTRIAN,
                        'vehicle.car': VEHICLE,
                        'vehicle.motorcycle': BICYCLIST,
                        'vehicle.bicycle': BICYCLIST,
                        'vehicle.bus.bendy': VEHICLE,
                        'vehicle.bus.rigid': VEHICLE,
                        'vehicle.truck': VEHICLE,
                        'vehicle.construction': VEHICLE,
                        'vehicle.emergency.ambulance': VEHICLE,
                        'vehicle.emergency.police': VEHICLE,
                        'vehicle.trailer': VEHICLE}

    @classmethod
    def preprocess(cls, dataroot: str,
                   version: str,
                   output_path: str,
                   resolution: float = 0.25,
                   axes_limit: int = 40):
        nusc = NuScenes(version=version, dataroot=dataroot, verbose=False)
        wl = int(axes_limit * 2 / resolution)
        os.makedirs(output_path, exist_ok=True)
        os.chdir(output_path)
        os.makedirs('train', exist_ok=True)
        os.makedirs('test', exist_ok=True)
        # cache all nusc maps
        maps_cache = {}
        train_scenes = int(len(nusc.scene) * 0.8)
        for i, scene in enumerate(nusc.scene):
            if i < train_scenes:
                os.chdir('train')
            else:
                os.chdir('test')
            sample_token = scene['first_sample_token']
            while sample_token:
                sample = nusc.get('sample', sample_token)
                # get data from that sample
                sample_data = nusc.get('sample_data', sample['data']['LIDAR_TOP'])
                scene = nusc.get('scene', sample['scene_token'])
                log = nusc.get('log', scene['log_token'])
                map_name = log['location']
                pose = nusc.get('ego_pose', sample_data['ego_pose_token'])
                ego_to_world = get_homogeneous_matrix(np.zeros(3), Quaternion(pose['rotation']).rotation_matrix)

                # create directory
                os.makedirs(sample_data['token'], exist_ok=True)
                os.chdir(sample_data['token'])

                # get annotated map
                try:
                    nusc_map = maps_cache[map_name]
                except KeyError:
                    nusc_map = NuScenesMap(dataroot=dataroot, map_name=map_name)
                    maps_cache[map_name] = nusc_map
                patch_box = (pose['translation'][0], pose['translation'][1], axes_limit * 2, axes_limit * 2)
                patch_angle = math.degrees(Quaternion(pose['rotation']).yaw_pitch_roll[0])
                map_mask = nusc_map.get_map_mask(patch_box, patch_angle, cls.layer_names, canvas_size=None)
                map_mask = np.flip(map_mask, 1)
                scaled = []
                for layer in map_mask:
                    scaled.append(cv2.resize(layer, (wl, wl)))
                map_mask = np.stack(scaled, axis=0)
                # convert to torch.tensor and save it
                map_mask = torch.tensor(map_mask.copy(), dtype=torch.float32)
                torch.save(map_mask, 'map')

                # retrieve all objects that fall inside the boundaries
                _, boxes, _ = nusc.get_sample_data(sample['data']['LIDAR_TOP'], box_vis_level=BoxVisibility.ALL,
                                                   use_flat_vehicle_coordinates=True)
                boxes = filter(lambda x: -axes_limit < x.center[0] < axes_limit and -axes_limit < x.center[1] < axes_limit,
                               boxes)
                # filter out relevant categories
                boxes = filter(lambda x: x.name in cls.category_mapping, boxes)
                boxes = list(boxes)
                boxes.sort(key=lambda x: (-x.center[1], x.center[0]))
                # parse data
                category = []
                location = []
                bbox = []
                velocity = []
                for box in boxes:
                    box_to_ego = get_homogeneous_matrix(box.center, box.rotation_matrix)
                    # calculates vehicle heading direction
                    _, heading = cartesian_to_polar(box_to_ego[:2, 0])
                    # calculates velocity by differentiate
                    v = nusc.box_velocity(box.token)
                    # velocity could be nan. If so, drop it
                    if True in np.isnan(v):
                        continue
                    # convert to ego coordinate
                    v = np.dot(np.linalg.inv(ego_to_world[:3, :3]), v[..., None]).flatten()[:2]
                    category.append(cls.category_mapping[box.name])
                    location.append(box.center[:2])
                    bbox.append((box.wlh[0], box.wlh[1], heading))
                    velocity.append(cartesian_to_polar(v))
                # append end token
                category.append(0)
                location.append(np.zeros(2))
                bbox.append(np.zeros(3))
                velocity.append(np.zeros(2))
                # convert to tensor and save
                torch.save(torch.tensor(category, dtype=torch.int64), 'category')
                torch.save(torch.tensor(location, dtype=torch.float32), 'location')
                torch.save(torch.tensor(bbox, dtype=torch.float32), 'bbox')
                torch.save(torch.tensor(velocity, dtype=torch.float32), 'velocity')

                os.chdir('..')
                sample_token = sample['next']
            os.chdir('..')

    def __init__(self, dataroot: str):
        self.dataroot = dataroot
        self.samples = os.listdir(dataroot)

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        path = os.path.join(self.dataroot, self.samples[idx])
        data = {}
        for filename in os.listdir(path):
            datapath = os.path.join(path, filename)
            data[filename] = torch.load(datapath)
        return data
