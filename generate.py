import numpy as np
from matplotlib import pyplot as plt
import torch
from datasets import NuScenesDataset, AutoregressiveProcessor, collate_fn
from torch.utils.data import DataLoader
from networks.autoregressive_transformer import AutoregressiveTransformer
from collections import OrderedDict


def to_numpy(data: dict):
    for k in data:
        if isinstance(data[k], torch.Tensor):
            data[k] = data[k].squeeze()
            if not data[k].shape:
                data[k] = data[k].item()
            else:
                data[k] = data[k].numpy()
        elif isinstance(data[k], dict):
            to_numpy(data[k])


np.random.seed(0)
torch.manual_seed(0)
plt.ion()
dataset = NuScenesDataset("/shared/perception/datasets/nuScenesProcessed/test")
dataloader = DataLoader(dataset, batch_size=1, shuffle=False, num_workers=4, collate_fn=collate_fn)
processor = AutoregressiveProcessor('cpu').test()
axes_limit = 40
cat2color = {1: 'red', 2: 'blue', 3: 'green'}
model = AutoregressiveTransformer()
state_dict = torch.load('/shared/perception/personals/yefanlin/project/ATISS-Traffic/ckpts/08-28-23:34:58/final')
new_state_dict = OrderedDict()
for k, v in state_dict.items():
    name = k[7:] # remove module.
    new_state_dict[name] = v
model.load_state_dict(new_state_dict)

for i_data, batch in enumerate(dataloader):
    batch, length, _ = processor(batch, n_keep=0)

    condition = {
        "category": None,  # int
    }

    cnt = 0
    while True:
        preds, probs, batch, length = model.generate(batch, length, condition, n_sample=10)
        cnt += 1
        print(cnt)
        to_numpy(preds)
        category = preds['category']
        if category == 0 or cnt > 100:
            break

    fig, ax = plt.subplots(figsize=(10, 10))
    drivable_area = batch['map'][0, 0]
    ped_crossing = batch['map'][0, 1]
    walkway = batch['map'][0, 2]
    lane_divider = batch['map'][0, 5]
    map_layers = np.stack([
        drivable_area + lane_divider,
        ped_crossing,
        walkway
    ], axis=-1) * 0.2
    ax.imshow(map_layers, extent=[-axes_limit, axes_limit, -axes_limit, axes_limit])
    for i in range(length.item()):
        if batch['category'][0, i] != 0:
            color = cat2color[batch['category'][0, i].item()]
            loc = batch['location'][0, i].numpy()
            ax.plot(loc[0], loc[1], 'x', color=color)
            w, l, theta = batch['bbox'][0, i].numpy()
            corners = np.array([[0, 0],
                                [l / 2, 0],
                                [l / 2, w / 2],
                                [-l / 2, w / 2],
                                [-l / 2, -w / 2],
                                [l / 2, -w / 2],
                                [l / 2, 0]])
            rotation = np.array([[np.cos(theta), np.sin(theta)],
                                 [-np.sin(theta), np.cos(theta)]])
            corners = np.dot(corners, rotation) + loc
            ax.plot(corners[:, 0], corners[:, 1], color=color, linewidth=2)
            speed, omega = batch['velocity'][0, i].numpy()
            rotation = np.array([[np.cos(omega), np.sin(omega)],
                                 [-np.sin(omega), np.cos(omega)]])
            velocity = np.dot(np.array([speed, 0]), rotation)
            ax.arrow(loc[0], loc[1], velocity[0] * 5, velocity[1] * 5, color=color, width=0.05)
    ax.set_xlim([-axes_limit, axes_limit])
    ax.set_ylim([-axes_limit, axes_limit])

    fig.savefig(f"./result/test-{i_data}.png")
    plt.close(fig)
