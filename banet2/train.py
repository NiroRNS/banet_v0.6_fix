# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/05_train.ipynb (unless otherwise specified).

__all__ = ['SampleEpisode', 'ImageSequence', 'get_y_fn', 'open_mat', 'open_mask', 'set_info_df', 'SegLabelListCustom',
           'SegItemListCustom', 'BCE', 'accuracy', 'dice2d', 'mae', 'train_model', 'cutout', 'cutout2']

# Cell
import fastai
from fastai import *
from fastai.vision import *
from fastai.callbacks import *
import scipy.io as sio
import sys

from banet.models import BA_Net

# Cell
class SampleEpisode(Sampler):
    def __init__(self, data_source, n_episodes, sequence_len, n_sequences, info_df, nburned=100):
        self.ds, self.epoch_size = data_source, n_episodes
        self.sequence_len, self.n_sequences = sequence_len, n_sequences
        self._epochs = []
        self.df = info_df
        self.nburned = nburned

    def __len__(self):
        return self.epoch_size*self.sequence_len*self.n_sequences

    def __iter__(self): return iter(self.get_epoch())

    def get_epoch(self):
        """Get indices for one epoch of size epoch_size"""
        idx = []
        for n in range(self.epoch_size):
            idx = [*idx, *self.get_batch()]
        return idx

    def get_batch(self):
        """Get indices for one mini-batch"""
        idx = []
        n = 0
        while n < self.n_sequences:
            k = np.random.choice(self.df.loc[self.df.ba>self.nburned].index, size=1, replace=False)[0]
            s = self.random_sample(k)
            if s is not None:
                idx = [*idx, *s]
                n += 1
        return idx

    def random_sample(self, k):
        """Random samples are n-way k-shot"""
        idx = []
        condition = ((self.df.name == self.df.loc[k, 'name']) &
            (self.df.time == self.df.loc[k, 'time'] + pd.Timedelta(days=self.sequence_len)) &
            (self.df.r == self.df.loc[k, 'r']) &
            (self.df.c == self.df.loc[k, 'c']))
        where = self.df.loc[condition].index.values
        if len(where) == 0:
            idx = None
        else:
            times = pd.date_range(self.df.loc[k-self.sequence_len//2, 'time'], periods=2*self.sequence_len, freq='D')
            condition = ((self.df.name == self.df.loc[k, 'name']) &
                (self.df.time.isin(times)) &
                (self.df.r == self.df.loc[k, 'r']) &
                (self.df.c == self.df.loc[k, 'c']))
            where = self.df.loc[condition].sort_values(by='time').index.values
            idx = where[:self.sequence_len]
            if len(idx) != self.sequence_len: idx = None
        return idx

class ImageSequence(LearnerCallback):
    def __init__(self, learn, sequence_len=64, n_sequences=1):
        super().__init__(learn)
        self.sequence_len = sequence_len
        self.n_sequences = n_sequences

    def on_batch_begin(self, last_input, last_target, epoch, iteration, **kwargs):
        bs, ch, sz1, sz2 = last_input.size()
        last_input = last_input.view(self.sequence_len, self.n_sequences, ch, sz1, sz2).permute(1, 2, 0, 3, 4)
        last_target = last_target.view(self.sequence_len, self.n_sequences, 1, sz1, sz2).permute(1, 2, 0, 3, 4)#.max(2)[0]
        return {'last_input': last_input, 'last_target': last_target}

# Cell
def get_y_fn(file, satellite='VIIRS750', target_product='MCD64A1C6'):
    f = str(Path(str(file))).replace('images', 'masks')
    f = f.replace(satellite, target_product)
    return f

def open_mat(fn, *args, **kwargs):
    data = sio.loadmat(fn)
    data = np.array([data[r] for r in ['Red', 'NIR', 'MIR', 'FRP']])
    data[np.isnan(data)] = 0
    data[-1, ...] = np.log1p(data[-1,...])
    data[np.isnan(data)] = 0
    data = torch.from_numpy(data).float()
    return Image(data)

def open_mask(fn, *args, **kwargs):
    data = sio.loadmat(fn)['bafrac']
    data[np.isnan(data)] = 0
    data = torch.from_numpy(data).float()
    return Image(data.view(-1, data.size()[0], data.size()[1]))

def set_info_df(items_list):
    names, dates = [], []
    rs, cs = [], []
    for o in items_list:
        name, date, r,  c = Path(o).stem.split('_')
        date = pd.Timestamp(date)
        names.append(name)
        dates.append(date)
        rs.append(r)
        cs.append(c)
    ba = [open_mask(get_y_fn(str(o))).data.sum().item() for o in progress_bar(items_list)]
    return pd.DataFrame({'name': names, 'time': dates, 'r':rs, 'c':cs, 'ba':ba})

class SegLabelListCustom(SegmentationLabelList):
    def open(self, fn): return open_mask(fn, div=True)

class SegItemListCustom(ImageList):
    _label_cls = SegLabelListCustom
    def open(self, fn): return open_mat(fn)

def _cutout(x, n_holes:uniform_int=1, length:uniform_int=40):
    "Cut out `n_holes` number of square holes of size `length` in image at random locations."
    h,w = x.shape[1:]
    for n in range(n_holes):
        h_y = np.random.randint(0, h)
        h_x = np.random.randint(0, w)
        y1 = int(np.clip(h_y - length / 2, 0, h))
        y2 = int(np.clip(h_y + length / 2, 0, h))
        x1 = int(np.clip(h_x - length / 2, 0, w))
        x2 = int(np.clip(h_x + length / 2, 0, w))
        #x[:2, y1:y2, x1:x2] = 1
        x[-1, y1:y2, x1:x2] = 0
    return x

cutout = TfmPixel(_cutout, order=20, )

def _cutout2(x, n_holes:uniform_int=1, length:uniform_int=40):
    "Cut out `n_holes` number of square holes of size `length` in image at random locations."
    h,w = x.shape[1:]
    for n in range(n_holes):
        h_y = np.random.randint(0, h)
        h_x = np.random.randint(0, w)
        y1 = int(np.clip(h_y - length / 2, 0, h))
        y2 = int(np.clip(h_y + length / 2, 0, h))
        x1 = int(np.clip(h_x - length / 2, 0, w))
        x2 = int(np.clip(h_x + length / 2, 0, w))
        x[0, y1:y2, x1:x2] = torch.rand(1)
        x[1, y1:y2, x1:x2] = torch.rand(1)
        x[2, y1:y2, x1:x2] = torch.rand(1)
    return x

cutout2 = TfmPixel(_cutout2, order=20)

class BCE(nn.Module):
    def forward(self, x, y):
        bce = nn.BCEWithLogitsLoss()
        return 100*bce(x.view(x.size()[0],-1),y.view(y.size()[0], -1))

def accuracy(input:Tensor, targs:Tensor, thr:int=0.5)->Rank0Tensor:
    "Compute accuracy with `targs` when `input` is bs * n_classes."
    input = (input.sigmoid()>thr).long()
    targs = (targs>thr).long()
    return (input==targs).float().mean()

def dice2d(pred, targs, thr=0.5):
    pred = pred.squeeze()
    targs = targs.squeeze().sum(0)
    pred = (pred.sigmoid().sum(0)>thr).float()
    targs = (targs>thr).float()
    return 2. * (pred*targs).sum() / (pred+targs).sum()

def mae(pred, targs, thr=0.5):
    a = pred.squeeze().sigmoid().sum(0)>thr
    pred = pred.squeeze().max(0)[1]
    targs = targs.squeeze().max(0)[1]
    pred = pred[a.byte()]
    targs = targs[a.byte()]
    return (pred-targs).abs().float().mean()

def train_model(val_year, r_fold, path, models_path, n_epochs=8, lr=1e-2, nburned=10, n_episodes_train=2000,
        n_episodes_valid=100, sequence_len=64, n_sequences=1, do_cutout=True, model_arch=None,
        pretrained_weights=None):
    path_img = path/'images'
    train_files = sorted([f.name for f in path_img.iterdir()])
    times = pd.DatetimeIndex([pd.Timestamp(t.split('_')[1]) for t in train_files])

    train_df = pd.DataFrame({'times': times, 'ID': train_files})
    valid_idx = train_df.loc[train_df.times.dt.year == val_year].index.values

    if do_cutout:
        tfms = get_transforms(do_flip=False, max_zoom=0, max_warp=0, max_rotate=0,
                          xtra_tfms=[cutout(n_holes=(1, 5), length=(5, 50), p=0.5),
                                     cutout2(n_holes=(1, 5), length=(5, 50), p=0.5)])
    else:
        tfms = get_transforms(do_flip=False, max_zoom=0, max_warp=0, max_rotate=0)

    data = (SegItemListCustom.from_df(train_df, path, cols='ID', folder='images')
        .split_by_idx(valid_idx)
        .label_from_func(get_y_fn, classes=['Burned'])
        .transform(tfms, size=128, tfm_y=False))

    info_train_df = set_info_df(data.train.items)
    info_valid_df = set_info_df(data.valid.items)

    bs = sequence_len*n_sequences
    train_dl = DataLoader(
        data.train,
        batch_size=bs,
        sampler=SampleEpisode(data.train, n_episodes=n_episodes_train,
                              sequence_len=sequence_len, n_sequences=n_sequences,
                              info_df=info_train_df, nburned=nburned))
    valid_dl = DataLoader(
        data.valid,
        batch_size=bs,
        sampler=SampleEpisode(data.valid, n_episodes=n_episodes_valid,
                              sequence_len=sequence_len, n_sequences=n_sequences,
                              info_df=info_valid_df, nburned=nburned))

    databunch = ImageDataBunch(train_dl, valid_dl, path='.')
    databunch = databunch.normalize([tensor([0.2349, 0.3548, 0.1128, 0.0016]),
                                     tensor([0.1879, 0.1660, 0.0547, 0.0776])])

    if model_arch is None:
        model = BA_Net(4, 1, sequence_len)
    else:
        model = model_arch(4, 1, sequence_len)

    if pretrained_weights is not None:
        print(f'Loading pretrained_weights from {pretrained_weights}\n')
        model.load_state_dict(torch.load(pretrained_weights)['model'])
    learn = Learner(databunch, model, callback_fns=[ImageSequence],
                    loss_func=BCE(), wd=1e-2, metrics=[accuracy, dice2d, mae])
    learn.clip_grad = 1
    print('Starting traning loop\n')
    learn.fit_one_cycle(n_epochs, lr)
    model_path.mkdir(exist_ok=True)
    torch.save(learn.model.state_dict(), model_path/f'banet-val{val_year}-fold{r_fold}-test.pth')
    print(f'Completed! banet-val{val_year}-fold{r_fold}-test.pth saved to {model_path}.')