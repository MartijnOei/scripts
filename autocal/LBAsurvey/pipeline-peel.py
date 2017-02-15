#!/usr/bin/python
# perform peeling on a group of TCs. Script should be run in the directory with MSs inside.
# widefield-group#.skymodel is required for each group
# Input:
# * group#_TC###.MS must have instrument table with amp+phase+TEC and beam uncorrected "empty" data in SUBTRACTED_DATA
# it should be possible to collect MSs after the run of pipeline-self.py
# * .model images are in the "self/models" dir made by pipeline-self
# * list of regions
# Output:
# DD-calibrated and subtracted data in SUBTRACTED_DATA
# Image of the facet


# coordinate of the region to find the DD
#ddset = [{'name': 'src1', 'reg': 'src1.reg', 'reg_facet': 'facet1.reg', 'faint': False, 'coord':[]},
#         {'name': 'src2', 'reg': 'src2.reg', 'reg_facet': 'facet2.reg', 'faint': False, 'coord':[]}]
#        {'name': 'tooth', 'reg': 'src3.reg', 'reg_facet': 'facet3.reg', 'faint': True, 'coord':[]}]
parset_dir = '/home/fdg/scripts/autocal/LBAsurvey/parset_peel'
maxniter = 10 # max iteration if source not converged

##########################################################################################

import sys, os, glob, re
import numpy as np
from lofar import bdsm
import pyrap.tables as pt
from autocal.lib_pipeline import *
from autocal.lib_pipeline_dd import *
from make_mask import make_mask
import lofar.bdsm as bdsm

set_logger('pipeline-peel.logging')
check_rm('logs')
s = Scheduler(dry=False)

def clean(c, mss, dd, avgfreq=4, avgtime=10, facet=False):
    """
    c = cycle/name
    mss = list of mss to avg/clean
    """
    # averaging before cleaning *.MS:CORRECTED_DATA -> *-avg.MS:DATA
    logging.info('Averaging before cleaning...')
    check_rm('mss_imgavg')
    os.mkdir('mss_imgavg')
    nchan = find_nchan(mss[0])
    for ms in mss:
        msout = 'mss_imgavg/'+os.path.basename(ms)
        check_rm(msout)
        s.add('NDPPP '+parset_dir+'/NDPPP-avg.parset msin='+ms+' msin.nchan='+str(nchan-nchan%4)+' msin.datacolumn=CORRECTED_DATA \
                msout='+msout+' avg.freqstep='+str(avgfreq)+' avg.timestep='+str(avgtime), log=ms+'_cleanavg-c'+str(c)+'.log', cmd_type='NDPPP')
    s.run(check=True)
    mssavg = [ms for ms in glob.glob('mss_imgavg/*MS')]

    # set image name
    imagename = 'peel/'+dd['name']+'/images/peel-'+str(c)

    # set pixscale, imsize and niter
    pixscale = scale_from_ms(mss[0])
    if facet:
        imsize = size_from_reg('peel/'+dd['name']+'/models/peel_facet-0000-model.fits', 'regions/'+dd['name']+'-facet.reg', [dd['RA'],dd['DEC']], pixscale, pad=1.5)
    else:
        imsize = size_from_reg('peel/'+dd['name']+'/models/peel_dd-0000-model.fits', 'regions/'+dd['name']+'.reg', [dd['RA'],dd['DEC']], pixscale, pad=1.5)

    if imsize < 512:
        trim = 512
        imsize = 1024
    elif imsize < 1024:
        trim = 1024
        imsize = 1024
    else:
        trim = imsize

    logging.debug('Image size: '+str(imsize)+' - Pixel scale: '+str(pixscale))

    # TODO: add multiscale
    logging.info('Cleaning (cycle: '+str(c)+')...')
    imagename = 'img/wide-'+str(c)
    s.add('wsclean -reorder -name ' + imagename + ' -size '+str(imsize)+' '+str(imsize)+' -trim '+str(trim)+' '+str(trim)+' \
            -mem 90 -j '+str(s.max_processors)+' -baseline-averaging 2.0 \
            -scale '+str(pixscale)+'arcsec -weight briggs 0.0 -niter 100000 -no-update-model-required -mgain 0.8 -pol I \
            -joinchannels -fit-spectral-pol 2 -channelsout 10 -deconvolution-channels 5 \
            -auto-mask 5 -auto-threshold 1 '+' '.join(mss), \
            log='wsclean-c'+str(c)+'.log', cmd_type='wsclean', processors='max')
    s.run(check=True)

    # make mask
    maskname = imagename+'-mask.fits'
    make_mask(image_name = imagename+'-MFS-image.fits', mask_name = maskname, threshisl = 4)
    # remove CC not in mask
    for modelname in sorted(glob.glob(imagename+'*model.fits')):
        blank_image_fits(modelname, maskname, inverse=True)

    check_rm('mss_imgavg')
    return imagename


def losoto(c, mss, dd, parset):
    logging.info('Running LoSoTo...')
    check_rm('plots')
    os.makedirs('plots')
    check_rm('globaldb')
    os.makedirs('globaldb')

    for num, ms in enumerate(mss):
        os.system('cp -r '+ms+'/instrument globaldb/instrument-'+str(num))
        if num == 0: os.system('cp -r '+ms+'/ANTENNA '+ms+'/FIELD globaldb/')

    h5parm = 'global-c'+str(c)+'.h5'

    s.add('H5parm_importer.py -v '+h5parm+' globaldb', log='losoto-c'+str(c)+'.log', log_append=True, cmd_type='python')
    s.run(check=False)
    s.add('losoto -v '+h5parm+' '+parset, log='losoto-c'+str(c)+'.log', log_append=True, cmd_type='python')
    s.run(check=False)
    s.add('H5parm_exporter.py -v -c '+h5parm+' globaldb', log='losoto-c'+str(c)+'.log', log_append=True, cmd_type='python')
    s.run(check=True)

    for num, ms in enumerate(mss):
        check_rm(ms+'/instrument')
        os.system('mv globaldb/sol000_instrument-'+str(num)+' '+ms+'/instrument')

    os.system('mv plots peel/'+dd['name']+'/plots/plots-c'+str(c))
    os.system('mv '+h5parm+' peel/'+dd['name']+'/h5')


def peel(dd):

    logging.info('Peeling: '+dd['name'])

    #########################################################################################
    # Clear
    logging.info('Cleaning...')
    check_rm('mss_peel') 
    check_rm('mss_facet') 
    check_rm('mss_shiftback') 
    check_rm('plot')
    check_rm('img')
    
    logging.info('Creating dirs...')
    os.makedirs('logs/mss')
    os.makedirs('logs/mss_peel')
    os.makedirs('logs/mss_facet')
    os.makedirs('logs/mss_shiftback')
    os.makedirs('mss_peel')
    os.makedirs('mss_facet')
    os.makedirs('mss_shiftback')
    check_rm('peel/'+dd['name'])
    os.makedirs('peel/'+dd['name'])
    os.makedirs('peel/'+dd['name']+'/models')
    os.makedirs('peel/'+dd['name']+'/images')
    os.makedirs('peel/'+dd['name']+'/plots')
    os.makedirs('peel/'+dd['name']+'/h5')
    os.makedirs('img')
    
    logging.info('Indexing...')
    allmss = sorted(glob.glob('mss/TC*.MS'))
    phasecentre = get_phase_centre(allmss[0])
    
    #centroid_ra, centroid_dec = get_coord_centroid(glob.glob('self/models/*.fits')[0], 'regions/'+dd['name']+'.reg')
    #dd['coord'] = [centroid_ra, centroid_dec]
    modeldir = 'peel/'+dd['name']+'/models/'

    # preparing concatenated dataset
    concat_ms = 'mss/concat.MS'
    check_rm(concat_ms+'*')
    pt.msutil.msconcat(allmss, 'mss/concat.MS', concatTime=False)
    
    #################################################################################################
    # Blank unwanted part of models
    
    logging.info('Splitting skymodels...')
    for model in sorted(glob.glob('self/models/*.fits')):
        logging.debug(model)
        outfile = modeldir+'/'+os.path.basename(model).replace('coadd','peel_dd')
        blank_image_reg(model, 'regions/'+dd['name']+'.reg', outfile, inverse=True)
        outfile = modeldir+'/'+os.path.basename(model).replace('coadd','peel_facet')
        blank_image_reg(model, 'regions/'+dd['name']+'-facet.reg', outfile, inverse=True)

    #clean('emptybefore', allmss, dd, avgfreq=1, avgtime=5, facet=True) # DEBUG

    #####################################################################################################
    # Add DD cal model - mss/TC*.MS:MODEL_DATA (high+low resolution model)
    logging.info('Ft DD calibrator model...')
    s.add('wsclean -predict -name ' + modeldir + 'peel_dd -mem 90 -j '+str(s.max_processors)+' -channelsout 10 '+concat_ms, \
            log='wscleanPRE-dd.log', cmd_type='wsclean', processors='max')
    s.run(check=True)

    ###########################################################################################################
    # ADD model mss/TC*.MS:CORRECTED_DATA + MODEL_DATA -> mss/TC*.MS:CORRECTED_DATA (empty data + DD cal from model)
    logging.info('Add SUBTRACTED_DATA...')
    for ms in allmss:
        s.add('addcol2ms.py -m '+ms+' -c SUBTRACTED_DATA -i CORRECTED_DATA', log=ms+'_init-addcol1.log', cmd_type='python', processors='max')
    s.run(check=True, max_threads=4)
    logging.info('Add model...')
    for ms in allmss:
        s.add('taql "update '+ms+' set CORRECTED_DATA = SUBTRACTED_DATA + MODEL_DATA"', log=ms+'_init-taql.log', cmd_type='general')
    s.run(check=True)
    
    # avg and ph-shift (to 1 chan/SB, 5 sec) -  mss/TC*.MS:CORRECTED_DATA -> mss_peel/TC*.MS:DATA (empty+DD, avg, phase shifted)
    logging.info('Shifting+averaging (CORRECTED_DATA)...')
    for ms in allmss:
        msout = ms.replace('mss','mss_peel')
        s.add('NDPPP '+parset_dir+'/NDPPP-shiftavg.parset msin='+ms+' msout='+msout+' msin.datacolumn=CORRECTED_DATA \
                shift.phasecenter=\['+str(dd['RA'])+'deg,'+str(dd['DEC'])+'deg\]', log=msout+'_init-shiftavg.log', cmd_type='NDPPP')
    s.run(check=True)
    
    peelmss = sorted(glob.glob('mss_peel/TC*.MS'))
    
    # Add MODEL_DATA and CORRECTED_DATA for cleaning
    logging.info('Add MODEL_DATA and CORRECTED_DATA...')
    for ms in peelmss:
        s.add('addcol2ms.py -m '+ms+' -c CORRECTED_DATA -i DATA', log=ms+'_init-addcol2.log', cmd_type='python', processors='max')
    s.run(check=True, max_threads=4)
    for ms in peelmss:
        s.add('addcol2ms.py -m '+ms+' -c MODEL_DATA', log=ms+'_init-addcol3.log', cmd_type='python', processors='max')
    s.run(check=True, max_threads=4)

    # do a first clean to get the starting model (CORRECTED_DATA is == DATA now)
    #clean('initdd', peelmss, dd, avgfreq=2, avgtime=5, facet=True) # DEBUG
    model = clean('init', peelmss, dd)

    ###################################################################################################################
    # self-cal cycle
    rms_noise_pre = np.inf
    for c in xrange(maxniter):
        logging.info('Start peel cycle: '+str(c))

        # Smooth
        logging.info('BL-based smoothing...')
        for ms in peelmss:
            s.add('BLsmooth.py -r -i DATA -o SMOOTHED_DATA '+ms, log=ms+'_smooth-c'+str(c)+'.log', cmd_type='python')
            #s.add('BLsmooth.py -r -w -i DATA -o SMOOTHED_DATA '+ms, log=ms+'_smooth-c'+str(c)+'.log', cmd_type='python')
        s.run(check=True)

        if c == 0:
            # make concat after the smoother to have the WEIGHT_SPECTRUM_ORIG and SMOOTHED_DATA included
            logging.info('Concatenating TCs...')
            concat_ms_peel = 'mss_peel/concat.MS'
            check_rm(concat_ms_peel+'*')
            pt.msutil.msconcat(peelmss, concat_ms_peel, concatTime=False)
    
        # ft model - mss_peel/TC*.MS:MODEL_DATA (best available model)
        logging.info('FT model...')
        s.add('wsclean -predict -name ' + model + ' -mem 90 -j '+str(s.max_processors)+' -channelsout 10 '+concat_ms_peel, \
                log='wscleanPRE-c'+str(c)+'.log', cmd_type='wsclean', processors='max')
        s.run(check=True)
    
        # solve+correct TEC - mss_peel/TC*.MS:SMOOTHED_DATA -> mss_peel/TC*.MS:CORRECTED_DATA
        logging.info('Solving TEC...')
        for ms in peelmss:
            check_rm(ms+'/instrument-tec')
            s.add('NDPPP '+parset_dir+'/NDPPP-solTEC.parset msin='+ms+' sol.parmdb='+ms+'/instrument-tec', \
                log=ms+'_sol-tec-c'+str(c)+'.log', cmd_type='NDPPP')
        s.run(check=True)
        logging.info('Correcting TEC...')
        for ms in peelmss:
            s.add('NDPPP '+parset_dir+'/NDPPP-corTEC.parset msin='+ms+' cor1.parmdb='+ms+'/instrument-tec cor2.parmdb='+ms+'/instrument-tec', \
                log=ms+'_cor-tec-c'+str(c)+'.log', cmd_type='NDPPP')
        s.run(check=True)

        # calibrate amplitude (solve only) - mss_peel/TC*.MS:CORRECTED_DATA
        # TODO: do it only after 3rd cycle
        logging.info('Calibrating amplitude...')
        for ms in peelmss:
            check_rm(ms+'/instrument-amp')
            s.add('NDPPP '+parset_dir+'/NDPPP-solG.parset msin='+ms+' sol.parmdb='+ms+'/instrument-amp csol.solint=100', \
                log=ms+'_sol-g-c'+str(c)+'.log', cmd_type='NDPPP')
        s.run(check=True)
    
        # merge parmdbs
        logging.info('Merging instrument tables...')
        for ms in peelmss:
            merge_parmdb(ms+'/instrument-tec', ms+'/instrument-amp', ms+'/instrument', clobber=True)
    
        # LoSoTo Amp rescaling + plotting
        losoto(c, peelmss, dd, parset_dir+'/losoto.parset')
    
        # correct TEC+amplitude - mss_peel/TC*.MS:DATA -> mss_peel/TC*.MS:CORRECTED_DATA
        logging.info('Correcting phase+amplitude...')
        for ms in peelmss:
            s.add('NDPPP '+parset_dir+'/NDPPP-corTECG.parset msin='+ms+' cor1.parmdb='+ms+'/instrument cor2.parmdb='+ms+'/instrument cor3.parmdb='+ms+'/instrument', \
                log=ms+'_cor-c'+str(c)+'.log', cmd_type='NDPPP')
        s.run(check=True)

        #logging.info('Restoring WEIGHT_SPECTRUM...')
        #s.add('taql "update '+concat_ms_peel+' set WEIGHT_SPECTRUM = WEIGHT_SPECTRUM_ORIG"', log='taql-resetweights-c'+str(c)+'.log', cmd_type='general')
        #s.run(check=True)
    
        # clean
        model = clean(c, peelmss, dd)

        # get noise, if larger than 95% of prev cycle: break
        rms_noise = get_nose_img(model+'-MFS-residual.fits')
        if rms_noise > 0.95 * rms_noise_pre: break
        rms_noise_pre = rms_noise

    
    # now do the same but for the entire facet to obtain a complete image of the facet and do a final subtraction
    ##############################################################################################################################
    # Add rest of the facet - mss/TC*.MS:MODEL_DATA (high+low resolution facet model)
    # TODO: mHdr -p 5 "10.68469 +41.26904" 0.5 m31.hdr
    logging.info('Ft facet model...')
    s.add('wsclean -predict -name ' + modeldir + 'peel_facet -mem 90 -j '+str(s.max_processors)+' -channelsout 10 '+concat_ms, \
            log='wscleanPRE-facet.log', cmd_type='wsclean', processors='max')
    s.run(check=True)

    # ADD mss/TC*.MS:SUBTRACTED_DATA + MODEL_DATA -> mss/TC*.MS:CORRECTED_DATA (empty data + facet from model)
    logging.info('Add facet model...')
    for ms in allmss:
        s.add('taql "update '+ms+' set CORRECTED_DATA = SUBTRACTED_DATA + MODEL_DATA"', log=ms+'_facet-taql.log', cmd_type='general')
    s.run(check=True)
    
    # Cannot avg since the same dataset has to be shifted back and used for other facets
    # Phase shift -  mss/TC*.MS:CORRECTED_DATA -> mss_facet/TC*.MS:DATA (not corrected, field subtracted but facet, phase shifted)
    logging.info('Shifting (CORRECTED_DATA)...')
    for ms in allmss:
        msout = ms.replace('mss','mss_facet')
        s.add('NDPPP '+parset_dir+'/NDPPP-shift.parset msin='+ms+' msout='+msout+' msin.datacolumn=CORRECTED_DATA \
                shift.phasecenter=\['+str(dd['RA'])+'deg,'+str(dd['DEC'])+'deg\]', log=msout+'_facet-shift.log', cmd_type='NDPPP')
    s.run(check=True)
    
    facetmss = sorted(glob.glob('mss_facet/TC*.MS'))

    ### DEBUG
    logging.info('Set CORRECTED_DATA = DATA')
    for ms in facetmss:
        s.add('addcol2ms.py -m '+ms+' -c CORRECTED_DATA -i DATA', log=ms+'_facet-addcolDEBUG.log', cmd_type='python', processors='max', log_append=True)
    s.run(check=True, max_threads=4)
    clean('initfacet', facetmss, dd, avgfreq=4, avgtime=5, facet=True) # DEBUG
    
    # Correct amp+ph - mss_facet/TC*.MS:DATA -> mss_facet/TC*.MS:CORRECTED_DATA (selfcal tec+amp corrected)
    # Copy instrument table in facet dataset
    for msFacet in facetmss:
        msDD = msFacet.replace('mss_facet','mss_peel')
        logging.debug(msDD+'/instrument -> '+msFacet+'/instrument')
        check_rm(msFacet+'/instrument')
        os.system('cp -r '+msDD+'/instrument '+msFacet+'/instrument')
    logging.info('Correcting facet amplitude+phase...')
    for ms in facetmss:
        s.add('NDPPP '+parset_dir+'/NDPPP-corTECG.parset msin='+ms+' cor1.parmdb='+ms+'/instrument cor2.parmdb='+ms+'/instrument cor3.parmdb='+ms+'/instrument', \
            log=ms+'_cor-facet.log', cmd_type='NDPPP')
    s.run(check=True)
    
    # Cleaning facet
    facetmodel = clean('facet', facetmss, dd, avgfreq=4, avgtime=5, facet=True)
    # DEBUG
    #facetmodel = 'peel/src1/images/peel-facet'

    # Blank pixels outside facet, new foccussed sources are cleaned (so they don't interfere) but we don't want to subtract them
    logging.info('Blank pixels outside facet...')
    for modelfits in glob.glob(facetmodel+'*model.fits'):
        blank_image_reg(modelfits, 'regions/'+dd['name']+'-facet.reg', inverse=True, blankval=0.)

    logging.info('Add MODEL_DATA')
    for ms in facetmss:
        s.add('addcol2ms.py -m '+ms+' -c MODEL_DATA', log=ms+'_facet-addcol.log', cmd_type='python', processors='max', log_append=True)
    s.run(check=True)

    logging.info('Concatenating TCs...')
    concat_ms_facet = 'mss_peel/concat.MS'
    check_rm(concat_ms_facet+'*')
    pt.msutil.msconcat(facetmss, concat_ms_facet, concatTime=False)
    
    # ft model - mss_peel/TC*.MS:MODEL_DATA (best available model)
    logging.info('FT facet model...')
    s.add('wsclean -predict -name ' + facetmodel + ' -mem 90 -j '+str(s.max_processors)+' -channelsout 10 '+concat_ms_facet, \
            log='wscleanPRE-facet2.log', cmd_type='wsclean', processors='max')
    s.run(check=True)

    for ms in facetmss:
        s.add('taql "update '+ms+' set CORRECTED_DATA = CORRECTED_DATA - MODEL_DATA"', log=ms+'_facet-taql2.log', cmd_type='general')
    s.run(check=True)

    # Corrupt empty data amp+ph - mss_facet/TC*.MS:CORRECTED_DATA -> mss_facet/TC*.MS:CORRECTED_DATA (selfcal empty)
    logging.info('Corrupting facet amplitude+phase...')
    for ms in facetmss:
        s.add('NDPPP '+parset_dir+'/NDPPP-corTECG.parset msin='+ms+' msin.datacolumn=CORRECTED_DATA \
                cor1.parmdb='+ms+'/instrument cor1.invert=false cor2.parmdb='+ms+'/instrument cor2.invert=false cor3.parmdb='+ms+'/instrument cor3.invert=false', \
                log=ms+'_corrupt-facet.log', cmd_type='NDPPP')
    s.run(check=True)

    logging.info('Shifting back...')
    for ms in facetmss:
        msout = ms.replace('mss_facet','mss_shiftback')
        s.add('NDPPP '+parset_dir+'/NDPPP-shift.parset msin='+ms+' msout='+msout+' msin.datacolumn=CORRECTED_DATA \
                shift.phasecenter=\['+str(phasecentre[0])+'deg,'+str(phasecentre[1])+'deg\]', log=msout+'_facet-shiftback.log', cmd_type='NDPPP')
    s.run(check=True)
    shiftbackmss = sorted(glob.glob('mss_shiftback/TC*.MS'))
    for ms in shiftbackmss:
        msorig = ms.replace('mss_shiftback','mss')
        s.add('taql "update '+msorig+', '+ms+' as shiftback set SUBTRACTED_DATA=shiftback.DATA"', log=ms+'_final-taql.log', cmd_type='general')
    s.run(check=True)

    #clean('emptyafter', allmss, dd, avgfreq=4, avgtime=5, facet=True) # DEBUG

    # backup logs
    os.system('mv logs peel/'+dd['name']+'/')
    # save images
    os.system('mv img/*MFS-image.fits peel/'+dd['name']+'/images/')

# end peeling function

# Run pyBDSM to create a model used to find good DD-calibrator
imagename = sorted(glob.glob('self/images/wide*MFS-image.fits'))[0]
if not os.path.exists('regions/DIEcatalog.fits'):
    bdsm_img = bdsm.process_image(imagename, rms_box=(55,12), \
        thresh_pix=5, thresh_isl=3, atrous_do=False, atrous_jmax=3, \
        adaptive_rms_box=True, adaptive_thresh=150, rms_box_bright=(80,20), \
        quiet=True)
    check_rm('regions')
    os.makedirs('regions')
    bdsm_img.write_catalog('regions/DIEcatalog.fits', catalog_type='srl', format='fits')

ddset = make_directions_from_skymodel('regions/DIEcatalog.fits', outdir='regions', flux_min_Jy=1.0, size_max_arcmin=3.0,
        directions_separation_max_arcmin=5.0, directions_max_num=20, flux_min_for_merging_Jy=0.2)

for dd in ddset: peel(dd)
logging.info("Done.")
