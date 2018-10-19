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
from osgeo import osr


def run_command(command, work_dir): 
    """ 
    A simple utility to execute a subprocess command. 
    """ 
    try:
        check_call(command, stderr=subprocess.STDOUT, cwd=work_dir)
    except subprocess.CalledProcessError as e:
        raise RuntimeError("command '{}' return with error (code {}): {}".format(e.cmd, e.returncode, e.output))


def get_projection(path):
    with rasterio.open(str(path)) as img:
        left, bottom, right, top = img.bounds
        spatial_reference =  str(getattr(img, 'crs_wkt', None) or img.crs.wkt)
        geo_ref_points = {
            'ul': {'x': left, 'y': top},
            'ur': {'x': right, 'y': top},
            'll': {'x': left, 'y': bottom},
            'lr': {'x': right, 'y': bottom},
        }
    return spatial_reference, geo_ref_points


def get_coords(geo_ref_points, spatial_ref):
    spatial_ref = osr.SpatialReference(spatial_ref)
    t = osr.CoordinateTransformation(spatial_ref, spatial_ref.CloneGeogCS())

    def transform(p):
        lon, lat, z = t.TransformPoint(p['x'], p['y'])
        return {'lon': lon, 'lat': lat}

    return {key: transform(p) for key, p in geo_ref_points.items()}


def prep_dataset(path):
    #left, right, top, bottom
    with rasterio.open(str(path)) as img:
        left, bottom, right, top = img.bounds
    spatial_ref, geo_ref = get_projection(path)

    creation_dt='2018-10-15T10:00:39.601578'
    start_dt = '1986-01-01T00:00:00'
    center_dt= '2016-12-31T00:00:00'

    doc = {
        'id': str(uuid.uuid4()),
        'product_type': 'nidem_v1.0.0',
        'creation_dt': creation_dt,
        'extent': {
            'coord': get_coords(geo_ref, spatial_ref),
            'from_dt': start_dt,
            'to_dt': center_dt,
            'center_dt': center_dt
        },
        'format': {'name': 'GeoTIFF'},
        'grid_spatial': {
            'projection': {
                'spatial_reference': "EPSG:4326",
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
                'nidem': {
                    'path': basename(path) ,
                    'layer': 1
                },

            }
        },
        'lineage': {
            'source_datasets': {}
        }
    }
    return doc


def check_dir(fname):
    directory_name = 'nidem'
    #addition = 'summary'
    Version_number = 'v1.0.0'
    #instrument = 'L8'
    file_name = fname.split('/')[-1]
    fname_wo, extention = splitext(file_name)
    x = 'lon_'+ (fname_wo.split('_')[-2]).split(".")[-2]
    y = 'lat_' + (fname_wo.split('_')[-1]).split(".")[-2]
    rel_path = pjoin(directory_name, Version_number, x, y, file_name)
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



@click.command(help="\b Extract a dataset from a GeoTIFF.")
@click.option('--path', '-p', required=True, help="Read the Geotiffs from this folder",
              type=click.Path(exists=True, readable=True))
@click.option('--output', '-o', required=True, help="Write Yamls into this folder",
              type=click.Path(exists=True, writable=True))
def main(path, output):
    logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.INFO)
    gtiff_path = os.path.abspath(path)
    output_dir = os.path.abspath(output)
    count = 0
    for path, subdirs, files in os.walk(gtiff_path):
        for fname in files:
            if fname.endswith('.tif'):
                f_name = os.path.join(path, fname)
                logging.info("Reading %s", (f_name))
                filename = getfilename(f_name, output_dir)
                count = count+1
                _write_dataset(f_name, filename)
                logging.info("Writing Yaml to %s, %i", dirname(filename), count)

               
if __name__ == "__main__":
    main()
