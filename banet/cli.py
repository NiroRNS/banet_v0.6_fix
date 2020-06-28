# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/06_cli.ipynb (unless otherwise specified).

__all__ = ['banet_viirs750_download', 'banet_create_dataset', 'banet_dataset2tiles', 'banet_predict_monthly',
           'banet_predict_times', 'banet_train_model', 'banet_nrt_run']

# Cell
import calendar
import pandas as pd
from fastscript import call_parse, Param
import pdb
import os
import IPython

from geoget.download import run_all

from .core import InOutPath, Path, ls, dict2json
from .data import *
from .geo import Region
from .predict import predict_month, predict_time
from .models import BA_Net
from .train import train_model
from .nrt import ProjectPath, RunManager

# Cell
Path.ls = ls
_bands =  ['Reflectance_M5', 'Reflectance_M7', 'Reflectance_M10', 'Radiance_M12',
           'Radiance_M15', 'SolarZenithAngle', 'SatelliteZenithAngle']
_regions_path = '../data/regions'
_weight_files = ['models/banetv0.20-val2017-fold0.pth',
                 'models/banetv0.20-val2017-fold1.pth',
                 'models/banetv0.20-val2017-fold2.pth']
_weight_files = [os.path.expanduser('~/.banet/') + o for o in _weight_files]

# Cell
@call_parse
def banet_viirs750_download(region:Param("Region name", str),
    tstart:Param("Start of serach window yyyy-mm-dd HH:MM:SS", str),
    tend:Param("End of search windo yyyy-mm-dd HH:MM:SS", str),
    path_save:Param("Path to save the outputs of the request", str),
    regions_path:Param("Path for region json files", str)):
    Path(path_save).mkdir(exist_ok=True)
    region = Region.load(f'{regions_path}/R_{region}.json')
    viirs_downloader = VIIRS750_download(region, tstart, tend)
    viirs_downloader_list = viirs_downloader.split_times()
    print(f'Splitting request into {len(viirs_downloader_list)} orders.')
    run_all(viirs_downloader_list, path_save)

# Cell
@call_parse
def banet_create_dataset(region:Param("Region name", str),
                   viirs_path:Param("Input path for VIIRS raw data", str),
                   fires_path:Param("Input path for Active Fires csv", str),
                   save_path:Param("Path to save outputs", str),
                   regions_path:Param("Path where region defenition files are stored", str),
                   mcd64_path:Param("Input path for MCD64 raw data", str)=None,
                   cci51_path:Param("Input path for FireCCI51 raw data", str)=None,
                   bands:Param("List of bands to use as inputs for VIIRS raw data", str)=_bands,
                   year:Param("Set to process a single year instead of all available", int)=None):

    paths = InOutPath(f'{viirs_path}', f'{save_path}')
    R = Region.load(f'{regions_path}/R_{region}.json')

    # VIIRS750
    print('\nCreating dataset for VIIRS750')
    viirs = Viirs750Dataset(paths, R, bands=bands)
    viirs.filter_times(year)
    merge_tiles = MergeTiles('SatelliteZenithAngle')
    mir_calc = MirCalc('SolarZenithAngle', 'Radiance_M12', 'Radiance_M15')
    rename = BandsRename(['Reflectance_M5', 'Reflectance_M7'], ['Red', 'NIR'])
    bfilter = BandsFilter(['Red', 'NIR', 'MIR'])
    act_fires = ActiveFires(f'{fires_path}/hotspots{R.name}.csv')
    viirs.process_all(proc_funcs=[merge_tiles, mir_calc, rename, bfilter, act_fires])

    # MCD64A1C6
    if mcd64_path is not None:
        print('\nCreating dataset for MCD64A1C6')
        paths.input_path = Path(mcd64_path)
        mcd = MCD64Dataset(paths, R)
        mcd.match_times(viirs)
        mcd.process_all()

    # FireCCI51
    if cci51_path is not None:
        print('\nCreating dataset for FireCCI51')
        paths.input_path = Path(cci51_path)
        cci51 = FireCCI51Dataset(paths, R)
        cci51.match_times(viirs)
        cci51.process_all()

# Cell
@call_parse
def banet_dataset2tiles(region:Param("Region name", str),
                  input_path:Param("Input path for dataset", str),
                  output_path:Param("Output path for tiles dataset", str),
                  size:Param("Tiles size", int)=128,
                  step:Param("Step size of moving window to create tiles", int)=100,
                  year:Param("Set to process a single year instead of all available", int)=None):

    iop = InOutPath(input_path, output_path)
    r2t = Region2Tiles(iop, 'VIIRS750', 'MCD64A1C6', regions=[region],
                       bands=[['Red', 'NIR', 'MIR', 'FRP'], ['bafrac']],
                       size=size, step=step)
    if year is None: r2t.process_all()
    else: r2t.process_all(include=[f'_{year}'])

# Cell
@call_parse
def banet_predict_monthly(region:Param("Region name", str),
                    input_path:Param("Input path for dataset", str),
                    output_path:Param("Output path for tiles dataset", str),
                    year:Param("Set to process a single year instead of all available", int),
                    weight_files:Param("List of pth weight files", list)=_weight_files):

    iop = InOutPath(input_path, f'{output_path}')
    times = pd.DatetimeIndex([pd.Timestamp(o.stem.split('_')[-1])
                              for o in iop.src.ls(include=['.mat'])])
    times = times[times.year == year]
    tstart, tend = times.min(), times.max()
    month_start = (tstart + pd.Timedelta(days=31)).month
    for m in range(month_start, tend.month):
        print(f'Generating maps for {calendar.month_name[m]} {year}:')
        t = pd.Timestamp(f'{year}-{m}-01')
        predict_month(iop, t, weight_files, region)

# Cell
@call_parse
def banet_predict_times(region:Param("Region name", str),
                    tstart:Param("Start of serach window yyyy-mm-dd HH:MM:SS", str),
                    tend:Param("End of search windo yyyy-mm-dd HH:MM:SS", str),
                    input_path:Param("Input path for dataset", str),
                    output_path:Param("Output path for tiles dataset", str),
                    regions_path:Param("Path for region json files", str),
                    product:Param("Name of product (default VIIRS750)", str)="VIIRS750",
                    output:Param("Name of file to save results", str)="data",
                    weight_files:Param("List of pth weight files", list)=_weight_files):

    iop = InOutPath(input_path, f'{output_path}')
    times = pd.date_range(tstart, tend, freq='D')
    R = Region.load(f'{regions_path}/R_{region}.json')
    predict_time(iop, times, weight_files, R, product=product, output=output)

# Cell
@call_parse
def banet_train_model(val_year:Param('Validation year', int),
                r_fold:Param('Fold name', str),
                input_path:Param("Input path for tiles dataset", str),
                output_path:Param("Path to save the model weights", str),
                n_epochs:Param("Number of epochs to train", int)=8,
                lr:Param("Learning rate", float)=1e-2,
                nburned:Param("Minimum number of burned pixels to define a sequence", int)=10,
                n_episodes_train:Param("Number of episodes per train epoch", int)=2000,
                n_episodes_valid:Param("Number of episodes for validation", int)=100,
                sequence_len:Param("Number of time-steps in sequence", int)=64,
                n_sequences:Param("Number of sequences per batch", int)=1,
                pretrained_weights:Param("Path to a weights file", str)=None):

    path = Path(input_path)
    model_path = Path(output_path)
    print(f'Training model for {val_year}, fold {r_fold}:')
    train_model(val_year, r_fold, path, model_path, n_epochs, lr, nburned,
                n_episodes_train, n_episodes_valid, sequence_len, n_sequences,
                pretrained_weights=pretrained_weights)

# Cell
@call_parse
def banet_nrt_run(region:Param("Region name", str),
                  left:Param("Left limit of the bounding box.", float),
                  bottom:Param("Bottom limit of the bounding box.", float),
                  right:Param("Right limit of the bounding box.", float),
                  top:Param("Top limit of the bounding box.", float),
                  project_path:Param("Root directory of the project", str),
                  hotspots_region:Param("Hotspots region name", str),
                  skip_hotspots:Param("Skip download of ladsweb data", bool)=False,
                  skip_ladsweb:Param("Skip download of ladsweb data", bool)=False,
                  skip_preprocess:Param("Skip download of ladsweb data", bool)=False,
                  skip_getpreds:Param("Skip download of ladsweb data", bool)=False):
    paths = ProjectPath(project_path)
    weight_files = ['banetv0.20-val2017-fold0.pth',
                    'banetv0.20-val2017-fold1.pth',
                    'banetv0.20-val2017-fold2.pth']
    manager = RunManager(paths, region)
    R = {'name': region, 'bbox': [left, bottom, right, top], 'pixel_size': 0.01}
    dict2json(R, paths.config/f'R_{region}.json')
    if not skip_hotspots: manager.update_hotspots(hotspots_region)
    if not skip_ladsweb: manager.download_viirs()
    if not skip_preprocess: manager.preprocess_dataset()
    if not skip_getpreds: manager.get_preds(weight_files)