#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2013 - Francesco de Gasperin
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

import pyrap.images
import numpy as np
import optparse
import sys
import lib_coordinates_mode as cm
import math
from progressbar import * 

def isNaN(num):
  return num != num

def coordshift(ra, dec, rashift, decshift):
  # shift ra and dec by rashift and decshift
  # ra: string in the hh:mm:ss.ss format
  # dec: string in the dd.mm.ss.ss format
  # rashift: float in arcsec
  # dechift: float in arcsec
  (hh, mm, ss) = cm.ratohms(cm.hmstora(*ra.split(":")) + rashift/3600)
  ra = str(hh)+":"+str(mm)+":"+ '%.3f' % ss
  (dd, mm, ss) = cm.dectodms(cm.dmstodec(*dec.split(".",2)) + decshift/3600)
  dec = "+"+str(dd)+"."+str(mm)+"."+ '%.3f' % ss
  return ra, dec

def getPos(name, header):
    """Get the position from a header line like
    format = Name, Type, Patch, Ra, Dec, I, Q, U, V, MajorAxis, MinorAxis, Orientation, ReferenceFrequency='1.47797e+08', SpectralIndex='[]'
    """
    headers = header.split(',')
    for i, header in enumerate(headers):
        if header.split('=')[0].find(name) != -1:
            return i

opt = optparse.OptionParser(usage="%prog -o bbs.skymodel-new -i bbs.skymodel [and one or more of the following options]", version="%prog 0.1")
opt.add_option('-i', '--inbbs', help='Input bbs skymodel [default = bbs.skymodel]', default='bbs.skymodel')
opt.add_option('-o', '--outbbs', help='Output bbs skymodel [default = bbs.skymodel-new]', default='bbs.skymodel-new')
opt.add_option('-m', '--mask', help='Mask image for valid clean components [Default: not applying any mask]')
opt.add_option('-r', '--reverse', help='Reverse Mask [default = False]', action="store_true", default=False)
opt.add_option('-a', '--patch', help='Instead of removing the masked object their patch is renamed with this prefix')
opt.add_option('-p', '--spidximg', help='Spectral index image [Default: not changing spectral index]')
opt.add_option('-s', '--shift', help='Ra and Dec shift in arcsec [Format: +/-Ra shift, +/-Dec shift, Default: 0,0]')
opt.add_option('-v', '--verbose', help='Print some more output', action="store_true", default=False)
(options, foo) = opt.parse_args()
inbbs = options.inbbs
outbbs = options.outbbs
spidximg = options.spidximg
mask = options.mask
reverse = options.reverse
patchprefix = options.patch
shift = options.shift
verbose = options.verbose

print "Input BBS file = "+inbbs
print "Output BBS file = "+outbbs

if mask != None: print "Mask = "+mask
if patchprefix != None: print "Patch prefix = "+patchprefix
if spidximg != None: print "Spectral index image = "+spidximg

if shift != None:
  try:
    (rashift, decshift) = shift.replace(' ', '').split(',')
    rashift = float(rashift)
    decshift = float(decshift)
    print "Ra shift: ", rashift, "arcsec"
    print "Dec shift: ", decshift, "arcsec"
  except:
    print "ERROR: bad formatted Ra,Dec shift. Should be something like \"-s 2,5\""

if spidximg == None and mask == None and shift == None:
  print "Nothing to do!"
  exit(0)

# Open mask
if mask != None:
  try:
    maskdata = pyrap.images.image(mask)
    maskval = maskdata.getdata()[0][0]
  except:
    print "ERROR: error opening MASK (",mask,"), probably a wrong name/format"
    exit(1)

# Open spidx image
if spidximg != None:
  try:
    spidxdata = pyrap.images.image(spidximg)
    spidxval = spidxdata.getdata()[0][0]
  except:
    print "ERROR: error opening SPIDX image (",spidximg,"), probably a wrong name/format"
    exit(1)

sys.stdout.flush()

# Open BBS Input files
with open(inbbs) as f:
        lines = f.readlines()
bbsnewdata = []
patchtoupdate = []
totFluxMask = 0.
totFluxOutMask = 0.

# Get position of interesting arguments
header = [line.replace(' ','').replace('format=', '').replace('\n','').replace('#','') for line in lines if line[0:6] == 'format'][0]
bbsnewdata.append('format = '+header+'\n\n')
PosName = getPos('Name', header)
PosRA = getPos('Ra', header)
PosDec = getPos('Dec', header)
PosPatch = getPos('Patch', header)
PosSpidx = getPos('SpectralIndex', header)
PosI = getPos('I', header)

# for each component find the relative mask pix, spidx pix and do the shift
widgets = ['Makeskymodel: ', Percentage(), ' ', Bar(marker='0',left='[',right=']'),' ', ETA()]
pbar = ProgressBar(widgets=widgets, maxval=len(lines))
pbar.start()
for i, cc in enumerate(lines):
  pbar.update(i)
  if cc[0] == '\n' or cc[0] == '#' or cc[0:6] == 'format': continue # nothing
  if cc[0] == ',': 
      bbsnewdata.append(cc)
      continue
  cc = cc.replace(' ','').split(',')
  ccname = cc[PosName]
  ccra = cc[PosRA]
  ccdec = cc[PosDec]
  ccpatch = cc[PosPatch]
  ccspidx = cc[PosSpidx]
  ccI = float(cc[PosI])
   
  # first do the coordinate shift (assuming mask and spidx image have correct coordinates!)
  if shift != None:
    (ra, dec) = coordshift(ra, dec, rashift, decshift)
    ccra = ra; ccdec = dec

  if mask != None:
    (a,b,_,_) = maskdata.toworld([0,0,0,0])
    (_, _, pixY, pixX) = maskdata.topixel([a, b, \
      math.radians(cm.dmstodec(*ccdec.split(".",2))), math.radians(cm.hmstora(*ccra.split(":")))])
    try:
      # != is a XOR for booleans
      if (not maskval[math.floor(pixY)][math.floor(pixX)]) != reverse:
        totFluxMask += ccI
        if patchprefix == None:
            if verbose: print "Removing component \"",ccname,"\" because it is masked."
            continue
        else:
            if verbose: print "Renameing patch for \"",ccname,"\" because it is masked."
            # add to the list of patches to update
            if ccpatch not in patchtoupdate: patchtoupdate.append(ccpatch)
      else:
        totFluxOutMask += ccI

    except:
      print "WARNING: failed to find a good mask value for component \"", ccname, "\"."
      print "-> Removing this component"
      continue
   
  if spidximg != None:
    (a,b,_,_) = spidxdata.toworld([0,0,0,0])
    (_, _, pixY, pixX) = spidxdata.topixel([a, b, \
      math.radians(cm.dmstodec(*ccdec.split(".",2))), math.radians(cm.hmstora(*ccra.split(":")))])
    try:
      val = round(spidxval[math.floor(pixY)][math.floor(pixX)],2)
#      if (val < -3): val = -3.
#      if (val > 1): val = 1.
      ccspidx = '[%.2f]' % val
      if isNaN(val): raise ValueError('Nan occurred')
    except:
      print "WARNING: failed to find a good spidx value for component \"", ccname, "\"."
      print "-> Set spectral index to [-0.7]"
      ccspidx = '[-0.7]'

  cc[PosRA] = ccra
  cc[PosDec] = ccdec
  cc[PosSpidx] = ccspidx
  cc[PosPatch] = ccpatch
  bbsnewdata.append(', '.join(cc))

pbar.finish()

# print tot flux in mask values
if mask != None:
    print "Total masked flux:", totFluxMask
    print "Total UNmasked flux:", totFluxOutMask

# update patches names
if patchprefix != None:
    for i, cc in enumerate(bbsnewdata):
        cc = cc.replace(' ','').split(',')
        if cc[0] == ',': continue # patch definition
        ccpatch = cc[PosPatch]
        if ccpatch in patchtoupdate:
            for i, ccu in enumerate(bbsnewdata):
                bbsnewdata[i] = ccu.replace(', '+ccpatch+',',', '+patchprefix+ccpatch+',')
            patchtoupdate.remove(ccpatch)

# write to new BBS file
with open(outbbs, 'w') as f:
    for cc in bbsnewdata:
        f.write(cc)
