#!/usr/bin/python
# casapy --nogui --log2term --nologger -c this_script.py picklefile

import sys, pickle

def casa_clean(msfile='', imagename='', imtype='normal', uvrange=''):
    """
    imtype: 'lr' for low resolution, large version of the image (larger FoV to get possible new extended emission)
            'wide' for wide FoV image
            'normal' for full res M87 image
    """
    if imtype == 'cocoon': 
        default('clean')
        clean(vis=msfile,imagename=imagename,mode="mfs",gridmode="widefield",wprojplanes=512,niter=1000,gain=0.05,psfmode="clark",imagermode="csclean",multiscale=[],interactive=False,mask='/home/fdg/scripts/autocal/VirA_LBA/m87.crtf',imsize=[512],cell=['0.5arcsec'],weighting="briggs",robust=0,cyclefactor=8,cyclespeedup=-1,nterms=3,uvrange=uvrange)

    elif imtype == 'normal': 
        default('clean')
        clean(vis=msfile,imagename=imagename,mode="mfs",gridmode="widefield",wprojplanes=512,niter=300,gain=0.05,psfmode="clark",imagermode="csclean",multiscale=[],interactive=False,mask='/home/fdg/scripts/autocal/VirA_LBA/m87.crtf',imsize=[2500],cell=['0.5arcsec'],weighting="briggs",robust=0,cyclefactor=8,cyclespeedup=-1,nterms=3,uvrange=uvrange)

        default('clean')
        scales=[0, 5, 20, 80, 320]
        clean(vis=msfile,imagename=imagename,mode="mfs",gridmode="widefield",wprojplanes=512,niter=10000,gain=0.1,psfmode="clark",imagermode="csclean",multiscale=scales,interactive=False,mask='/home/fdg/scripts/autocal/VirA_LBA/m87.crtf',imsize=[2500],cell=['0.5arcsec'],weighting="briggs",robust=0,cyclefactor=5,cyclespeedup=-1,nterms=3,uvrange=uvrange)

    elif imtype == 'lr':
        default('clean')
        clean(vis=msfile,imagename=imagename,mode="mfs",gridmode="widefield",wprojplanes=1024,niter=50,gain=0.05,psfmode="clark",imagermode="csclean",multiscale=[],interactive=False,mask='/home/fdg/scripts/autocal/VirA_LBA/m87.crtf',imsize=[512],cell=['10arcsec'],weighting="briggs",robust=0,cyclefactor=8,cyclespeedup=-1,nterms=3,uvtaper=T,outertaper='60arcsec',uvrange=uvrange)

        default('clean')
        scales=[0, 5, 10, 20, 40]
        clean(vis=msfile,imagename=imagename,mode="mfs",gridmode="widefield",wprojplanes=1024,niter=5000,gain=0.1,psfmode="clark",imagermode="csclean",multiscale=scales,interactive=False,mask='/home/fdg/scripts/autocal/VirA_LBA/m87.crtf',imsize=[512],cell=['10arcsec'],weighting="briggs",robust=0,cyclefactor=5,cyclespeedup=-1,nterms=3,uvtaper=T,outertaper='60arcsec',uvrange=uvrange)

    elif imtype == 'wide':
        default('clean')
        clean(vis=msfile,imagename=imagename,mode="mfs",gridmode="widefield",wprojplanes=1024,niter=500,gain=0.05,psfmode="clark",imagermode="csclean",multiscale=[],interactive=False,imsize=[1024],cell=['10arcsec'],weighting="briggs",robust=0,cyclefactor=5,cyclespeedup=-1,nterms=3,uvtaper=T,outertaper='120arcsec',uvrange=uvrange)

    else:
        print "Error: Wrong imtype."
        return 1

params = pickle.load( open( sys.argv[6], "rb" ) )
os.system('rm '+sys.argv[6])
casa_clean(**params)
