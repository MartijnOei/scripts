#!/usr/bin/env python

# Mosaic images

# Input:
# - images
# - beam (optional)
# - masks (optional)
# - header/image (optional) - if not provided use first image
# Output:
# - regridded, beam-corrected image

import os.path, sys, pickle, glob, argparse, re, logging
import numpy as np
from astropy.io import fits as pyfits
from astropy.wcs import WCS as pywcs
from astropy.table import Table
import pyregion

tgss_catalog = '/home/fdg/script/autocal/TGSSADR1_5sigma_catalog_v3.fits'

parser = argparse.ArgumentParser(description='Mosaic ddf-pipeline directories')
parser.add_argument('--images', dest='images', nargs='+', help='List of images to combine')
parser.add_argument('--masks', dest='masks', nargs='+', help='List of masks/regions to blank images')
parser.add_argument('--beams', dest='beams', nargs='+', help='List of beams')
parser.add_argument('--beamcut', dest='beamcut', default=0.3, help='Beam level to cut at (default: 0.3, use 0.0 to deactivate)')
parser.add_argument('--beamcorr', dest='beamcorr', action='store_true', help='Pre-correct for beam before combining (default: do not apply)')
parser.add_argument('--header', dest='header', help='An image/header to use for the output mosaic coordinates')
parser.add_argument('--noises', dest='noise', type=float, nargs='+', help='UNSCALED Central noise level for weighting: must match numbers of maps')
parser.add_argument('--scales', dest='scale', type=float, nargs='+', help='Scale factors by which maps should be multiplied: must match numbers of maps')
parser.add_argument('--shift', dest='shift', action='store_true', help='Shift images before mosaicing')
parser.add_argument('--find_noise', dest='find_noise', action='store_true', help='Find noise from image (default: assume equal weights, ignored if noises are given)')
parser.add_argument('--output', dest='output', default='mosaic.fits' help='Name of output mosaic (default: mosaic.fits)')

args = parser.parse_args()

#######################################################
# input check

if args.scale is not None:
    if len(args.scale) != len(args.images):
        logging.error('Scales provided must match images')
        sys.exit(1)

if args.noise is not None:
    if len(args.noise) != len(args.imagess):
        logging.error('Noises provided must match images')
        sys.exit(1)

#############################################################

class Direction(object):
    def __init__(self, imagefile):
        logging.debug('Create direction for %s' % imagefile)
        self.imagefile = imagefile
        self.beamfile = None
        self.maskfile = None
        self.noise = 1.
        self.scale = 1.
        self.shift = 0.
        self.img_data, self.img_hdr = pyfits.getdata(self.imagefile, header=True)

    def set_mask(self, maskfile):
        if not os.path.exists(maskfile):
            logging.error('Mask file %s not found.' % maskfile)
            sys.exit(1)
        self.maskfile = maskfile

    def apply_mask(self):
        """
        Set to 0 all pixels outside the given mask (ds9 region)
        """
        if self.maskfile is None: return
        r = pyregion.open(self.maskfile)
        mask = r.get_mask(header=self.img_hdr, shape=self.img_data.shape)
        self.img_data[~mask] = 0.

    def set_beam(self, beamfile):
        if not os.path.exists(beamfile):
            logging.error('Beam file %s not found.' % beamfile)
            sys.exit(1)
        self.beamfile = beamfile
        self.beam_data, self.beam_hdr = pyfits.getdata(self.beamfile, header=True)
        if beam_data.shape != self.img_data.shape:
            logging.error('Beam and image shape are different.')
            sys.exit(1)

    def apply_beam_cut(self, beamcut=0.3):
        if self.beamfile is None: return
        self.img_data[self.beam_data < self.beamcut] = 0.

    def apply_beam_corr(self):
        if self.beamfile is None: return
        self.img_data /= self.beam_data

    def reproject(self):
        pass

    def calc_noise(self, niter=20, eps=1e-5):
        """
        Return the rms of all the pixels in an image
        niter : robust rms estimation
        eps : convergency
        """
        with pyfits.open(self.imagefile) as fits:
            data = fits[0].data
            oldrms = 1.
            for i in range(niter):
                rms = np.nanstd(data)
                if np.abs(oldrms-rms)/rms < eps:
                    self.noise = rms
                    break
                subim = subim[np.abs(subim)<5*rms]
                oldrms=rms
            raise Exception('Failed to converge')

    def calc_weight(self):
        self.weight_data = np.ones_like(self.img_data)
        if self.beamfile is not None:
            self.weight_data *= self.beam_data
        # at this point this is the beam factor: we want 1/sigma**2.0, so divide by central noise and square
        self.weight_data /= self.noise * self.scale
        self.weight_data = self.weight_data**2.0

    def get_wcs(self):
        return pywcs(self.img_hdr)

    def calc_shift(self, ref_cat):
        """
        Find a shift cross-matching source extracted from the image and a given catalog
        """
        from lofar import bdsm
        from astropy.coordinates import match_coordinates_sky

        img_cat = self.imagefile+'-.cat'
        bdsm_img = bdsm.process_image(self.imagefile, rms_box=(100,30), \
            thresh_pix=5, thresh_isl=3, atrous_do=False, \
            adaptive_rms_box=True, adaptive_thresh=100, rms_box_bright=(30,10), quiet=True)
        bdsm_img.write_catalog(img_cat, catalog_type='srl', format='fits', clobber=True)

        # read catlogue
        ref_t = Table.read(ref_cat)
        img_t = Table.read(img_cat)

        # cross match
        idx_match, sep, _ = match_coordinates_sky(SkyCoord(ref_t['RA'], ref_t['DEC']),\
                                                  SkyCoord(img_t['RA'], img_t['DEC']))
        idx_match = idx_match[sep<5*u.arcsec]
        
        # find & apply shift
        dra = np.mean(ref_t['RA'][idx_match] - img_t['RA'][idx_match])
        ddec = np.mean(ref_t['DEC'][idx_match] - img_t['DEC'][idx_match])
        ra = self.img_hdr['CRVAL1']
        dec = self.img_hdr['CRVAL2']
        self.hdr['CRVAL1'] -= dra/(3600.*np.cos(np.pi*dec/180.))
        self.hdr['CRVAL2'] -= ddec/3600.

        # clean up
        os.system('rm '+img_cat)

logging.info('Reading files...')
directions = []
for i, image in enumerate(args.images):
    d = Direction(image)

    if args.beams is not None:
        d.set_beam(args.beams[i])
        d.apply_beam_cut(beamcut = args.beamcut)

    if args.masks is not None:
        d.set_mask(args.masks[i])
        d.apply_mask()

    if args.noise is not None: d.noise = args.noise[i]
    elif args.find_noise: d.calc_noise() # after beam cut

    if args.scales is not None: d.scale = args.scales[i]

    if args.beamcorr: d.apply_beam_corr() # after noise calculation

    d.calc_weight() # after setting: beam, noise, scale

    if args.shift:
        d.calc_shift(tgss_catalog)

    directions.append(d)

# prepare header for final gridding
if args.header is None:
    logging.warning('Calculate output headers...')
    mra = np.mean( np.array([d.get_wcs().crval[0] for d in directions]) )
    mdec = np.mean( np.array([d.get_wcs().crval[1] for d in directions]) )

    logging.info('Will make mosaic at %f %f' % (mra,mdec))
    
    # we make a reference WCS and use it to find the extent in pixels
    # needed for the combined image

    rwcs = pywcs(naxis=2)
    rwcs.wcs.ctype = directions[0].get_wcs().ctype
    rwcs.wcs.cdelt = directions[0].get_wcs().cdelt
    rwcs.wcs.crval = [mra,mdec]
    rwcs.wcs.crpix = [1,1]

    xmin=0
    xmax=0
    ymin=0
    ymax=0
    for d in directions:
        w = d.get_wcs()
        ys, xs = np.where(d.img_data)
        axmin = xs.min()
        aymin = ys.min()
        axmax = xs.max()
        aymax = ys.max()
        del(xs)
        del(ys)
        print 'non-zero',axmin,aymin,axmax,aymax
        for x,y in ((axmin,aymin),(axmax,aymin),(axmin,aymax),(axmax,aymax)):
            ra, dec = [float(f) for f in w.wcs_pix2world(x,y,0)]
            #print ra,dec
            nx, ny = [float (f) for f in rwcs.wcs_world2pix(ra,dec,0)]
            #print nx,ny
            if nx < xmin: xmin=nx
            if nx > xmax: xmax=nx
            if ny < ymin: ymin=ny
            if ny > ymax: ymax=ny

    print 'co-ord range:', xmin, xmax, ymin, ymax

    xsize = int(xmax-xmin)
    ysize = int(ymax-ymin)

    rwcs.wcs.crpix = [-int(xmin)+1,-int(ymin)+1]
    print 'checking:', rwcs.wcs_world2pix(mra,mdec,0)
    print rwcs

    regrid_hdr = rwcs.to_header()
    regrid_hdr['NAXIS'] = 2
    regrid_hdr['NAXIS1'] = xsize
    regrid_hdr['NAXIS2'] = ysize

else:
    try:
        logging.info("Using %s header for final gridding." % args.header)
        regrid_hrd = pyfits.open(args.header)[0].header
    except:
        logging.error("--header must be a fits file.")
        sys.exit(1)

logging.info('Now making the mosaic...')
isum = np.zeros([ysize,xsize])
wsum = np.zeros_like(isum)
mask = np.zeros_like(isum,dtype=np.bool)
for d in directions:
    logging.info('Working on: %s' % d.imagefile)
    outname = 'reproject-'+d.imagename
    if args.load and os.path.exists(outname):
        logging.debug('Loading...')
        r = fits.open(outname)[0].data
    else:
        logging.debug('Reprojecting...')
        r, footprint = reproj(d.img_data, regrid_hdr, hdu_in=0, parallel=False)
        r[ np.isnan(r) ] = 0
        hdu = pyfits.PrimaryHDU(header=regrid_hdr, data=r)
        hdu.writeto(outname, clobber=True)
    outname='weight-'+d.imagename
    if args.load and os.path.exists(outname):
        logging.debug('Loading...')
        w = fits.open(outname)[0].data
        mask |= (w>0)
    else:
        logging.debug('Reprojecting...')
        w, footprint = reproj(d.beam_data, regrid_hdr, hdu_in=0, parallel=False)
        mask |= ~np.isnan(w)
        w[ np.isnan(w) ] = 0
        hdu = fits.PrimaryHDU(header=regrid_hdr, data=w)
        hdu.writeto(outname, clobber=True)
    logging.debug('Add to mosaic...')
    isum+=r*w
    wsum+=w

isum/=wsum
# mask now contains True where a non-nan region was present in either map
isum[~mask]=np.nan
for ch in ('BMAJ', 'BMIN', 'BPA', 'RESTFRQ', 'TELESCOP', 'OBSERVER'):
    regrid_hdr[ch] = directions[0].img_hdr[ch]
    regrid_hdr['ORIGIN'] = 'ddf-pipeline-mosaic'
    regrid_hdr['UNITS'] = 'Jy/beam'

    hdu = fits.PrimaryHDU(header=regrid_hdr, data=isum)
    hdu.writeto(args.output, clobber=True)
