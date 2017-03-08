#!/usr/bin/env python

# Mosaic final images

# arguments are directories with final images
# we use the .smooth.int.restored.fits and .fluxscale.fits files

#from reproject import reproject_interp,reproject_exact
#from reproj_test import reproject_interp_chunk_2d
import os.path, sys, pickle, glob, argparse, re
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS
import numpy as np
from autocal.lib_pipeline import *
from autocal.lib_pipeline_img import *

parser = argparse.ArgumentParser(description='Mosaic ddf-pipeline directories')
#parser.add_argument('--directories', metavar='D', nargs='+',
#                    help='directory name')
parser.add_argument('--images', dest='images', nargs='+', help='List of images to combine')
parser.add_argument('--regions', dest='regions', nargs='+', help='List of regions used to blank images')
parser.add_argument('--beams', dest='beams', nargs='+', help='List of beams')
parser.add_argument('--beamcut', dest='beamcut', default=0.3, help='Beam level to cut at')
#parser.add_argument('--exact', dest='exact', action='store_true', help='Do exact reprojection (slow)')
#parser.add_argument('--save', dest='save', action='store_true', help='Save intermediate images')
#parser.add_argument('--load', dest='load', action='store_true', help='Load existing intermediate images')
parser.add_argument('--noise', dest='noise', type=float, nargs='+', help='UNSCALED Central noise level for weighting: must match numbers of maps')
parser.add_argument('--scale', dest='scale', type=float, nargs='+', help='Scale factors by which maps should be multiplied: must match numbers of maps')
parser.add_argument('--shift', dest='shift', action='store_true', help='Shift images before mosaicing')
#parser.add_argument('--no_write', dest='no_write', action='store_true', help='Do not write final mosaic')
parser.add_argument('--find_noise', dest='find_noise', action='store_true', help='Find noise from image')
#parser.add_argument('--load_layout', dest='load_layout', action='store_true', help='Load a previously defined mosaic layout rather than determining from the images.')

args = parser.parse_args()

# if pipe then find images, regions and pb automatically
re 
if args.pipe == True:
    args.images = sorted(glob.glob('peel/ddcal*/images/facetM-facet-MFS-image.fits'))
    args.regions = []
    for image in args.images:
        args.regions.append('regions/%s-facet.reg' % re.)
    args.beams = makeBeam('self/images/beam') # TODO: uno per facet

if args.scale is not None:
    if len(args.scale) != len(args.directories):
        logging.error('Scales provided must match directories')
        sys.exit()

if args.noise is not None:
    if len(args.noise) != len(args.directories):
        logging.error('Noises provided must match directories')
        sys.exit()


class Direction(object):
    def __init__(self, imagefile, beamfile, region=None):
        self.imagefile = imagefile
        self.beamfile = beamfile
        self.region = region


#if args.exact:
#    reproj=reproject_exact
#else:
#    reproj=reproject_interp_chunk_2d

threshold = float(args.beamcut)
hdus=[]
app=[]
wcs=[]

logging.info('Reading files...')
directions = []
for image in args.images:
    directions.append(Direction(image,))

noise=[]
name=[]
for d in args.directories:
    name.append(d.split('/')[-1])
    hdu=fits.open(d+'/image_full_ampphase1m.smooth.int.restored.fits')
    if args.find_noise:
        noise.append(get_rms(hdu))
    hdus.append(flatten(hdu))
    app.append(flatten(fits.open(d+'/image_full_ampphase1m.app.restored.fits')))

if args.find_noise:
    args.noise=noise
    print 'Noise values are:'
    for t,n in zip(name,noise):
        print t,n

logging.info('Computing noise/beam factors...')
for i in range(len(app)):
    app[i].data/=hdus[i].data
    app[i].data[app[i].data<threshold]=0
    # at this point this is the beam factor: we want 1/sigma**2.0, so divide by central noise and square
    if args.noise is not None:
        if args.scale is not None:
            app[i].data/=args.noise[i]*args.scale[i]
        else:
            app[i].data/=args.noise[i]

    app[i].data=app[i].data**2.0

    if args.scale is not None:
        hdus[i].data*=args.scale[i]

if args.shift:
    logging.info('Finding shifts...')
    # shift according to the FIRST delta ra/dec from quality pipeline
    dras=[]
    ddecs=[]
    for d in args.directories:
        t=Table.read(d+'/image_full_ampphase1m.cat.fits_FIRST_match_filtered.fits')
        dras.append(np.mean(t['FIRST_dRA']))
        ddecs.append(np.mean(t['FIRST_dDEC']))
    print 'Applying shifts:',dras,ddecs
    for i in range(len(app)):
        for hdu in [hdus[i],app[i]]:
            ra=hdu.header['CRVAL1']
            dec=hdu.header['CRVAL2']
            hdu.header['CRVAL1']-=dras[i]/(3600.0*np.cos(np.pi*dec/180.0))
            hdu.header['CRVAL2']-=ddecs[i]/3600.0

logging.info('WCS values are:')
for i in range(len(app)):
    wcs.append(WCS(hdus[i].header))
    print wcs[-1]

if args.load_layout:
    with open('mosaic-header.pickle') as f:
        header=pickle.load(f)
    xsize=header['NAXIS1']
    ysize=header['NAXIS2']
    print 'Mosaic using loaded header:'
    print header
else:

    ras=np.array([w.wcs.crval[0] for w in wcs])
    decs=np.array([w.wcs.crval[1] for w in wcs])

    mra=np.mean(ras)
    mdec=np.mean(decs)
    logging.info('Will make mosaic at %f %f' % (mra,mdec))
    
    # we make a reference WCS and use it to find the extent in pixels
    # needed for the combined image

    rwcs=WCS(naxis=2)
    rwcs.wcs.ctype=wcs[0].wcs.ctype
    rwcs.wcs.cdelt=wcs[0].wcs.cdelt
    rwcs.wcs.crval=[mra,mdec]
    rwcs.wcs.crpix=[1,1]

    xmin=0
    xmax=0
    ymin=0
    ymax=0
    for a,w in zip(app,wcs):
        ys,xs=np.where(a.data)
        axmin=xs.min()
        aymin=ys.min()
        axmax=xs.max()
        aymax=ys.max()
        del(xs)
        del(ys)
        print 'non-zero',axmin,aymin,axmax,aymax
        for x,y in ((axmin,aymin),(axmax,aymin),(axmin,aymax),(axmax,aymax)):
            ra,dec=[float(f) for f in w.wcs_pix2world(x,y,0)]
            #print ra,dec
            nx,ny=[float (f) for f in rwcs.wcs_world2pix(ra,dec,0)]
            print nx,ny
            if nx<xmin: xmin=nx
            if nx>xmax: xmax=nx
            if ny<ymin: ymin=ny
            if ny>ymax: ymax=ny

    print 'co-ord range:', xmin, xmax, ymin, ymax

    xsize=int(xmax-xmin)
    ysize=int(ymax-ymin)

    rwcs.wcs.crpix=[-int(xmin)+1,-int(ymin)+1]
    print 'checking:', rwcs.wcs_world2pix(mra,mdec,0)
    print rwcs

    header=rwcs.to_header()
    header['NAXIS']=2
    header['NAXIS1']=xsize
    header['NAXIS2']=ysize

    with open('mosaic-header.pickle','w') as f:
        pickle.dump(header,f)

isum=np.zeros([ysize,xsize])
wsum=np.zeros_like(isum)
mask=np.zeros_like(isum,dtype=np.bool)
print 'now making the mosaic'
for i in range(len(hdus)):
    print 'image',i,'(',name[i],')'
    outname='reproject-'+name[i]+'.fits'
    if args.load and os.path.exists(outname):
        print 'loading...'
        hdu=fits.open(outname)
        r=hdu[0].data
    else:
        print 'reprojecting...'
        r, footprint = reproj(hdus[i], header, hdu_in=0, parallel=False)
        r[np.isnan(r)]=0
        hdu = fits.PrimaryHDU(header=header,data=r)
        if args.save: hdu.writeto(outname,clobber=True)
    print 'weights',i,'(',name[i],')'
    outname='weight-'+name[i]+'.fits'
    if args.load and os.path.exists(outname):
        print 'loading...'
        hdu=fits.open(outname)
        w=hdu[0].data
        mask|=(w>0)
    else:
        print 'reprojecting...'
        w, footprint = reproj(app[i], header, hdu_in=0, parallel=False)
        mask|=~np.isnan(w)
        w[np.isnan(w)]=0
        hdu = fits.PrimaryHDU(header=header,data=w)
        if args.save: hdu.writeto(outname,clobber=True)
    print 'add to mosaic...'
    isum+=r*w
    wsum+=w

if not(args.no_write):
    isum/=wsum
    # mask now contains True where a non-nan region was present in either map
    isum[~mask]=np.nan
    for ch in ('BMAJ', 'BMIN', 'BPA', 'RESTFRQ', 'TELESCOP', 'OBSERVER'):
        header[ch]=hdus[0].header[ch]
    header['ORIGIN']='ddf-pipeline-mosaic'
    header['UNITS']='Jy/beam'

    hdu = fits.PrimaryHDU(header=header,data=isum)
    hdu.writeto('mosaic.fits',clobber=True)
