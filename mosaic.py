#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2017 - Francesco de Gasperin
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

# Mosaic images

import os.path, sys, pickle, glob, argparse, re, logging
import numpy as np
from lib_fits import flatten
from astropy.io import fits as pyfits
from astropy.wcs import WCS as pywcs
from astropy.table import Table
import pyregion
from lib_beamdeconv import *
# https://github.com/astrofrog/reproject
from reproject import reproject_interp, reproject_exact
reproj = reproject_interp

tgss_catalog = '/home/fdg/scripts/autocal/TGSSADR1_5sigma_catalog_v3.fits'

parser = argparse.ArgumentParser(description='Mosaic ddf-pipeline directories')
parser.add_argument('--images', dest='images', nargs='+', help='List of images to combine')
parser.add_argument('--masks', dest='masks', nargs='+', help='List of masks/regions to blank images')
parser.add_argument('--beams', dest='beams', nargs='+', help='List of beams')
parser.add_argument('--beamcut', dest='beamcut', default=0.3, help='Beam level to cut at (default: 0.3, use 0.0 to deactivate)')
parser.add_argument('--beamcorr', dest='beamcorr', action='store_true', help='Pre-correct for beam before combining (default: do not apply)')
parser.add_argument('--beamarm', dest='beamarm', action='store_true', help='Convolve all images to minimum common beam (default: False)')
parser.add_argument('--header', dest='header', help='An image/header to use for the output mosaic coordinates')
parser.add_argument('--noises', dest='noises', type=float, nargs='+', help='UNSCALED Central noise level for weighting: must match numbers of maps')
parser.add_argument('--scales', dest='scales', type=float, nargs='+', help='Scale factors by which maps should be multiplied: must match numbers of maps')
parser.add_argument('--shift', dest='shift', action='store_true', help='Shift images before mosaicing')
parser.add_argument('--find_noise', dest='find_noise', action='store_true', help='Find noise from image (default: assume equal weights, ignored if noises are given)')
parser.add_argument('--save', dest='save', action='store_true', help='Save intermediate results (default: False)')
parser.add_argument('--output', dest='output', default='mosaic.fits', help='Name of output mosaic (default: mosaic.fits)')

args = parser.parse_args()
logging.root.setLevel(logging.DEBUG)

#######################################################
# input check

if args.scales is not None:
    if len(args.scales) != len(args.images):
        logging.error('Scales provided must match images')
        sys.exit(1)

if args.noises is not None:
    if len(args.noises) != len(args.imagess):
        logging.error('Noises provided must match images')
        sys.exit(1)

if args.images is None or len(args.images) < 2:
    logging.error('Requires at lest 2 images.')
    sys.exit(1)

if args.shift and not args.beamcorr:
    logging.warning('Attempting shift calculation on beam corrected images, this is not the best.')

#############################################################

from lib_fits import Image
class Direction(Image):

    def __init__(self, imagefile):
        logging.debug('Create direction for %s' % imagefile)
        Image.__init__(self, imagefile)
        self.scale = 1.
        self.shift = 0.
        self.beamfile = None
        self.noise = 1.
        self.imagefile = imagefile

    def set_beam_file(self, beamfile):
        if not os.path.exists(beamfile):
            logging.error('Beam file %s not found.' % beamfile)
            sys.exit(1)
        logging.debug('%s: set beam file %s' % (self.imagefile, beamfile))
        self.beamfile = beamfile
        self.beam_hdr, self.beam_data = flatten(self.beamfile)
        if self.beam_data.shape != self.img_data.shape:
            logging.error('Beam and image shape are different.')
            sys.exit(1)

    def apply_beam_cut(self, beamcut=0.3):
        if self.beamfile is None: return
        self.img_data[self.beam_data < beamcut] = 0.

    def apply_beam_corr(self):
        if self.beamfile is None: return
        self.img_data /= self.beam_data

    def calc_weight(self):
        self.weight_data = np.ones_like(self.img_data)
        self.weight_data[self.img_data == 0] = 0
        if self.beamfile is not None:
            self.weight_data *= self.beam_data
        # at this point this is the beam factor: we want 1/sigma**2.0, so divide by central noise and square
        self.weight_data /= self.noise * self.scale
        self.weight_data = self.weight_data**2.0

    def calc_shift(self, ref_cat, separation=15):
        """
        Find a shift cross-matching source extracted from the image and a given catalog
        separation in arcsec
        """
        import bdsf
        from astropy.coordinates import match_coordinates_sky
        from astropy.coordinates import SkyCoord
        import astropy.units as u

        img_cat = self.imagefile+'.cat'
        if not os.path.exists(img_cat):
            bdsf_img = bdsf.process_image(self.imagefile, rms_box=(100,30), \
                thresh_pix=5, thresh_isl=3, atrous_do=False, \
                adaptive_rms_box=True, adaptive_thresh=100, rms_box_bright=(30,10), quiet=True)
            bdsf_img.write_catalog(outfile=img_cat, catalog_type='srl', format='fits', clobber=True)

        # read catlogue
        ref_t = Table.read(ref_cat)
        img_t = Table.read(img_cat)

        # cross match
        idx_match, sep, _ = match_coordinates_sky(SkyCoord(ref_t['RA'], ref_t['DEC']),\
                                                  SkyCoord(img_t['RA'], img_t['DEC']))
        idx_match_img = idx_match[sep<separation*u.arcsec]
        idx_match_ref = np.arange(0,len(ref_t))[sep<separation*u.arcsec]
        
        # find & apply shift
        if len(idx_match) == 0:
            logging.warning('No match found in TGSS.')
            return
        dra = ref_t['RA'][idx_match_ref] - img_t['RA'][idx_match_img]
        dra[ dra>180 ] -= 360
        dra[ dra<-180 ] += 360
        ddec = ref_t['DEC'][idx_match_ref] - img_t['DEC'][idx_match_img]
        self.apply_shift(np.mean(dra), np.mean(ddec))

        # clean up
        if not args.save:
            os.system('rm '+img_cat)

logging.info('Reading files...')
directions = []
beams = []
for i, image in enumerate(args.images):
    d = Direction(image)
    #beams.append([d.get_beam()[0]+0.0001, d.get_beam()[0]+0.0001, 0]) 
    beams.append(d.get_beam()) 
    directions.append(d)

if args.beamarm:
    common_beam = findCommonBeam(beams)
    logging.debug('Minimum common beam: %.1f" %.1f" (pa %.1f deg)' % \
             (common_beam[0]*3600., common_beam[1]*3600., common_beam[2]))

for i, d in enumerate(directions):

    if args.beamarm:
        d.convolve(common_beam)

    if args.beams is not None:
        d.set_beam_file(args.beams[i])
        d.apply_beam_cut(beamcut = args.beamcut)

    if args.masks is not None:
        d.apply_region(args.masks[i], blankvalue=0, invert=True)

    if args.noises is not None: d.noise = args.noises[i]
    elif args.find_noise: d.calc_noise() # after beam cut/mask

    if args.scales is not None: d.scale = args.scales[i]

    if args.beamcorr: d.apply_beam_corr() # after noise calculation

    d.calc_weight() # after setting: beam, noise, scale

    if args.shift:
        d.calc_shift(tgss_catalog)


# prepare header for final gridding
if args.header is None:
    logging.warning('Calculate output headers...')
    mra = np.mean( np.array([d.get_wcs().wcs.crval[0] for d in directions]) )
    mdec = np.mean( np.array([d.get_wcs().wcs.crval[1] for d in directions]) )

    logging.info('Will make mosaic at %f %f' % (mra,mdec))
    
    # we make a reference WCS and use it to find the extent in pixels
    # needed for the combined image

    rwcs = pywcs(naxis=2)
    rwcs.wcs.ctype = directions[0].get_wcs().wcs.ctype
    rwcs.wcs.cdelt = directions[0].get_wcs().wcs.cdelt
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
        for x,y in ((axmin,aymin),(axmax,aymin),(axmin,aymax),(axmax,aymax)):
            ra, dec = [float(f) for f in w.wcs_pix2world(x,y,0)]
            #print ra,dec
            nx, ny = [float (f) for f in rwcs.wcs_world2pix(ra,dec,0)]
            #print nx,ny
            if nx < xmin: xmin=nx
            if nx > xmax: xmax=nx
            if ny < ymin: ymin=ny
            if ny > ymax: ymax=ny

    #print 'co-ord range:', xmin, xmax, ymin, ymax

    xsize = int(xmax-xmin)
    ysize = int(ymax-ymin)

    rwcs.wcs.crpix = [-int(xmin)+1,-int(ymin)+1]
    #print 'checking:', rwcs.wcs_world2pix(mra,mdec,0)

    regrid_hdr = rwcs.to_header()
    regrid_hdr['NAXIS'] = 2
    regrid_hdr['NAXIS1'] = xsize
    regrid_hdr['NAXIS2'] = ysize

else:
    try:
        logging.info("Using %s header for final gridding." % args.header)
        regrid_hdr = pyfits.open(args.header)[0].header
        xsize = regrid_hdr['NAXIS1']
        ysize = regrid_hdr['NAXIS2']
    except:
        logging.error("--header must be a fits file.")
        sys.exit(1)

logging.info('Making mosaic...')
isum = np.zeros([ysize,xsize])
wsum = np.zeros_like(isum)
mask = np.zeros_like(isum,dtype=np.bool)
for d in directions:
    logging.info('Working on: %s' % d.imagefile)

    outname = d.imagefile.replace('.fits','-reproj.fits')
    if os.path.exists(outname):
        logging.debug('Loading %s...' % outname)
        r = pyfits.open(outname)[0].data
    else:
        logging.debug('Reprojecting data...')
        r, footprint = reproj((d.img_data, d.img_hdr), regrid_hdr)#, parallel=True)
        r[ np.isnan(r) ] = 0
        hdu = pyfits.PrimaryHDU(header=regrid_hdr, data=r)
        if args.save:
            hdu.writeto(outname, clobber=True)

    outname = d.imagefile.replace('.fits','-reprojW.fits')
    if os.path.exists(outname):
        logging.debug('Loading %s...' % outname)
        w = pyfits.open(outname)[0].data
        mask |= (w>0)
    else:
        logging.debug('Reprojecting weights...')
        w, footprint = reproj((d.weight_data, d.img_hdr), regrid_hdr)#, parallel=True)
        mask |= ~np.isnan(w)
        w[ np.isnan(w) ] = 0
        hdu = pyfits.PrimaryHDU(header=regrid_hdr, data=w)
        if args.save:
            hdu.writeto(outname, clobber=True)
    logging.debug('Add to mosaic...')
    isum += r*w
    wsum += w

logging.debug('Write mosaic: %s...' % args.output)
# mask now contains True where a non-nan region was present in either map
isum /= wsum
isum[~mask] = np.nan

for ch in ('BMAJ', 'BMIN', 'BPA'):
    regrid_hdr[ch] = pyfits.open(directions[0].imagefile)[0].header[ch]
    regrid_hdr['ORIGIN'] = 'pill-pipe-mosaic'
    regrid_hdr['UNITS'] = 'Jy/beam'

hdu = pyfits.PrimaryHDU(header=regrid_hdr, data=isum)
hdu.writeto(args.output, clobber=True)

logging.debug('Done.')
