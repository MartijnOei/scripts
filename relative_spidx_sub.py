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

# read a MS and then rescale all the channels to subtract
# a -0.7 spidx from all of them, the central freq is taken
# as a reference

# Usage: ./retive_spidx_sub.py dataset.MS

import pyrap.tables as pt
import sys, cmath
import numpy as np

# open MS and get channels
t = pt.table(sys.argv[1]+'/SPECTRAL_WINDOW',ack=False,readonly=True)
freq_ref = t.getcell('REF_FREQUENCY', 0)
freq_chans = t.getcell('CHAN_FREQ', 0)
print "Central freq:", freq_ref

t = pt.table(sys.argv[1],ack=False,readonly=False)
data = t.getcol('CORRECTED_DATA')
for i, freq_chan in enumerate(freq_chans):
	print "Working on chan:", freq_chan,
	# find factor
	fact = 10.**(0.7 * np.log10(freq_chan/freq_ref))
	print "(factor:", fact, ")", " - ",
	amp = np.absolute(data[:,i,:])
	ph = np.angle(data[:,i,:])
	print np.mean(amp), " -> ",
	amp *= fact
	print np.mean(amp)
	data[:,i,:] = amp * np.exp(1j*ph)

# write MS
t.putcol('CORRECTED_DATA', data)
t.close()
