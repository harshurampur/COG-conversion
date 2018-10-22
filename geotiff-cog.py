from os.path import join as pjoin, basename, dirname, exists, splitext
import tempfile
from subprocess import check_call
import subprocess
import click
import os
import logging
import rasterio
import uuid
import yaml
from yaml import CLoader as Loader, CDumper as Dumper


def run_command(command, work_dir): 
    """ 
    A simple utility to execute a subprocess command. 
    """ 
    try:
        check_call(command, stderr=subprocess.STDOUT, cwd=work_dir)
    except subprocess.CalledProcessError as e:
        raise RuntimeError("command '{}' return with error (code {}): {}".format(e.cmd, e.returncode, e.output))


def prep_dataset(path):
    #left, right, top, bottom
    with rasterio.open(str(path)) as img:
        left, bottom, right, top = img.bounds

    creation_dt='2018-09-10T00:00:00'
    center_dt= '2013-01-01T00:00:00'

    doc = {
        'id': str(uuid.uuid4()),
        'product_type': 'landsat8_barest_earth_mosaic',
        'creation_dt': creation_dt,
        'platform': {'code': 'LANDSAT_8'},
        'instrument': {
            'name': 'OLI'
        },
        'extent': {
            'coord':{
                'ul':{'lon': left,  'lat': top},
                'ur':{'lon': right, 'lat': top},
                'll':{'lon': left,  'lat': bottom},
                'lr':{'lon': right, 'lat': bottom},
            },
            'from_dt': center_dt,
            'to_dt': center_dt,
            'center_dt': center_dt
        },
        'format': {'name': 'GeoTIFF'},
        'grid_spatial': {
            'projection': {
                'spatial_reference': str(getattr(img, 'crs_wkt', None) or img.crs.wkt),
                'geo_ref_points': {
                    'ul': {'x': left, 'y': top},
                    'ur': {'x': right, 'y': top},
                    'll': {'x': left, 'y': bottom},
                    'lr': {'x': right, 'y': bottom},
                }
            }
        },
        'image': {
            'bands': {
                'blue': {
                    'path': path,
                    'layer': 1
                },
                'green': {
                    'path': path,
                    'layer': 2
                },
                'red': {
                    'path': path,
                    'layer': 3
                },
                'nir': {
                    'path': path,
                    'layer': 4
                },
                'swir1': {
                    'path': path,
                    'layer': 5
                },
                'swir2': {
                    'path': path,
                    'layer': 6
                }
            }
        },
        'lineage': {
            'source_datasets': {}
        }
    }
    return doc


def check_dir(fname):
    directory_name = 'HLTC'
    Version_number = 'v2.0.0'
    composites = "composite"
    file_name = fname.split('/')[-1]
    fname_wo, extention = splitext(file_name)
    #Check whether High or Low
    highorlow = fname_wo.split("_")[1]
    if highorlow == "HIGH":
        level_name = "high-tide"
    else:
        level_name = "low-tide"
    x = 'lon_'+ (fname_wo.split('_')[-6]).split(".")[-2]
    y = 'lat_' + (fname_wo.split('_')[-5]).split(".")[-2]
    rel_path = pjoin(directory_name, Version_number,composites,level_name, x, y, file_name)
    return rel_path


def getfilename(fname, outdir):
    """ To create a temporary filename to add overviews and convert to COG
        and create a file name just as source but without '.TIF' extension
    """
    rel_path = check_dir(fname)
    out_fname = pjoin(outdir, rel_path)
    outdir = dirname(out_fname)
    if not exists(dirname(out_fname)): 
        os.makedirs(dirname(out_fname)) 
    return out_fname


def _write_dataset(fname, outfname):
    yname_wo, extension = splitext(outfname)
    yaml_name = yname_wo + '.yaml'
    dataset_object = prep_dataset(fname)
    dataset = yaml.load(str(dataset_object), Loader=Loader)
    with open(yaml_name, 'w') as fp:
        yaml.dump(dataset, fp, default_flow_style=False, Dumper=Dumper)
        logging.info("Writing dataset yaml to %s", basename(yaml_name))


def _write_cogtiff(fname, out_fname, outdir):
    """ Convert the Geotiff to COG using gdal commands
        Blocksize is 512
        TILED <boolean>: Switch to tiled format
        COPY_SRC_OVERVIEWS <boolean>: Force copy of overviews of source dataset
        COMPRESS=[NONE/DEFLATE]: Set the compression to use. DEFLATE is only available if NetCDF has been compiled with
                  NetCDF-4 support. NC4C format is the default if DEFLATE compression is used.
        ZLEVEL=[1-9]: Set the level of compression when using DEFLATE compression. A value of 9 is best,
                      and 1 is least compression. The default is 1, which offers the best time/compression ratio.
        BLOCKXSIZE <int>: Tile Width
        BLOCKYSIZE <int>: Tile/Strip Height
        PREDICTOR <int>: Predictor Type (1=default, 2=horizontal differencing, 3=floating point prediction)
        PROFILE <string-select>: possible values: GDALGeoTIFF,GeoTIFF,BASELINE,
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_fname = pjoin(tmpdir, basename(fname))
        
        env = ['GDAL_DISABLE_READDIR_ON_OPEN=YES',
               'CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif']
        subprocess.check_call(env, shell=True)
        
        # copy to a tempfolder
        to_cogtif = [
                     'gdal_translate',
                     '-of',
                     'GTIFF',
                     fname, 
                     temp_fname]
        run_command(to_cogtif, tmpdir)

        # Add Overviews
        # gdaladdo - Builds or rebuilds overview images.
        # 2, 4, 8,16,32 are levels which is a list of integral overview levels to build.
        add_ovr = [
                   'gdaladdo', 
                   '-r', 
                   'average',
                   '--config',
                   'GDAL_TIFF_OVR_BLOCKSIZE',
                   '512',
                   temp_fname, 
                   '2',
                   '4', 
                   '8', 
                   '16', 
                   '32',
                   '64']
        run_command(add_ovr, tmpdir)

        # Convert to COG 
        cogtif = [
                  'gdal_translate', 
                  '-co', 
                  'TILED=YES', 
                  '-co', 
                  'COPY_SRC_OVERVIEWS=YES', 
                  '-co', 
                  'COMPRESS=DEFLATE',
                  '-co',
                  'ZLEVEL=9',
                  '--config',
                  'GDAL_TIFF_OVR_BLOCKSIZE',
                  '512',
                  '-co',
                  'BLOCKXSIZE=512',
                  '-co',
                  'BLOCKYSIZE=512',
                  '-co',
                  'PREDICTOR=3',
                  '-co',
                  'PROFILE=GeoTIFF',
                  temp_fname, 
                  out_fname] 
        run_command(cogtif, outdir) 


@click.command(help="\b Convert Geotiff to Cloud Optimized Geotiff using gdal."
                    " Mandatory Requirement: GDAL version should be >=2.2")
@click.option('--path', '-p', required=True, help="Read the Geotiffs from this folder",
              type=click.Path(exists=True, readable=True))
@click.option('--output', '-o', required=True, help="Write COG's into this folder",
              type=click.Path(exists=True, writable=True))
def main(path, output):
    logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.INFO)
    gtiff_path = os.path.abspath(path)
    output_dir = os.path.abspath(output)
    count = 0
    for path, subdirs, files in os.walk(gtiff_path):
        for fname in files:
            if fname.startswith('COMPOSITE') and fname.endswith('.tif'):
                f_name = os.path.join(path, fname)
                logging.info("Reading %s", (f_name))
                filename = getfilename(f_name, output_dir)
                _write_cogtiff(f_name, filename, output_dir)
                count = count+1
                #_write_dataset(f_name, filename)
                logging.info("Writing COG to %s, %i", dirname(filename), count)

               
if __name__ == "__main__":
    main()
