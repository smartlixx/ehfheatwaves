import warnings
warnings.filterwarnings('ignore')
import sys
try: 
    import pandas as pd
except ImportError:
    print "Please install pandas"
    sys.exit(2)
import numpy as np
import datetime as dt
import math
import qtiler
from netCDF4 import MFDataset, Dataset
import netcdftime
from optparse import OptionParser
import subprocess

# Parse command line arguments
usage = "usage: %prog -x <FILE> -n <FILE> -m <FILE> [options]"
parser = OptionParser(usage=usage)
parser.add_option('-x', '--tmax', dest='tmaxfile', 
        help='file containing tmax', metavar='FILE')
parser.add_option('--vnamex', dest='tmaxvname', default='tasmax',
        help='tmax variable name', metavar='STR')
parser.add_option('-n', '--tmin', dest='tminfile',
        help='file containing tmin', metavar='FILE')
parser.add_option('--vnamen', dest='tminvname', default='tasmin',
        help='tmin variable name', metavar='STR')
parser.add_option('-m', '--mask', dest='maskfile',
        help='file containing land-sea mask', metavar='FILE')
parser.add_option('--vnamem', dest='maskvname', default='sftlf',
        help='mask variable name', metavar='STR')
parser.add_option('-s', '--season', dest='season', default='summer',
        help='austal season for annual metrics. Defaults to austral summer',
        metavar='STR')
parser.add_option('-p', dest='pcntl', type='float', default=90,
        help='the percentile to use for thresholds. Defaults to 90',
        metavar='INT')
parser.add_option('--base', dest='bp', default='1961-1990',
        help='base period to calculate thresholds. Default 1961-1990',
        metavar='YYYY-YYYY')
parser.add_option('-q', '--qmethod', dest='qtilemethod', default='climpact',
        help='quantile interpolation method. Default is climpact', 
        metavar='STR')
parser.add_option('-d', '--daily', action="store_true", dest='daily', 
        help='output daily EHF values and heatwave indicators')
parser.add_option('--dailyonly', action="store_true", dest='dailyonly',
        help='output only daily values and suppress yearly output')
(options, args) = parser.parse_args()
if not options.tmaxfile or not options.tminfile:
    print "Please specify tmax and tmin files."
    sys.exit(2)
if not options.maskfile:
    print "You didn't specify a land-sea mask. It's faster if you do, so this might take a while."
if len(options.bp)!=9:
    print "Incorect base period format."
    sys.exit(2)
else:
    bpstart = int(options.bp[:4])
    bpend = int(options.bp[5:9])
# Percentile
pcntl = options.pcntl
# climpact/python/matlab
qtilemethod = options.qtilemethod
# season (winter/summer)
season = options.season
if (season!='summer')&(season!='winter'):
    print "Use either summer or winter. (Austral)"
    sys.exit(2)
# save daily EHF output
yearlyout = True
dailyout = options.daily
if options.dailyonly: 
    dailyout = True
    yearlyout = False

# Load data
try:
    tmaxnc = MFDataset(options.tmaxfile, 'r')
except IndexError:
    tmaxnc = Dataset(options.tmaxfile, 'r')
nctime = tmaxnc.variables['time']
calendar = nctime.calendar
if not calendar:
    print 'Unrecognized calendar. Using gregorian.'
    calendar = 'gregorian'
elif calendar=='360_day':
    daysinyear = 360
    seasonlen = 150
    if season=='winter':
        startday = 121
        endday = 271
    else:
        startday = 301
        endday = 451
    dayone = netcdftime.num2date(nctime[0], nctime.units,
            calendar=calendar)
    daylast = netcdftime.num2date(nctime[-1], nctime.units,
            calendar=calendar)
    class calendar360():
        def __init__(self,sdate,edate):
            self.year = np.repeat(range(sdate.year,edate.year+1), 360, 0)
            nyears = len(xrange(sdate.year,edate.year+1))
            self.month = np.tile(np.repeat(range(1,12+1), 30, 0), nyears)
            self.day = np.tile(np.tile(range(1,30+1), 12), nyears)
            if (sdate.day!=1)|(edate.month!=1):
                sdoyi = (sdate.month-1)*30+sdate.day-1
                self.year = self.year[sdoyi:]
                self.month = self.month[sdoyi:]
                self.day = self.day[sdoyi:]
            if (edate.day!=30)|(edate.month!=12):
                edoyi = (12-edate.month)*30+(30-edate.day)
                self.year = self.year[:-edoyi]
                self.month = self.month[:-edoyi]
                self.day = self.day[:-edoyi]
    dates = calendar360(dayone, daylast)
    shorten = 0
    if (daylast.day!=30)|(daylast.month!=12):
        shorten = 30*(13-daylast.month) - daylast.day
else:
    daysinyear = 365
    if season=='winter':
        seasonlen = 153
        startday = 121
        endday = 274
    else:
        seasonlen = 151
        startday = 304
        endday = 455
    dayone = netcdftime.num2date(nctime[0], nctime.units,
            calendar=calendar)
    daylast = netcdftime.num2date(nctime[-1], nctime.units,
            calendar=calendar)
    dates = pd.date_range(str(dayone), str(daylast))
    shorten = 0
    if (daylast.day!=30)|(daylast.month!=12):
        endofdata = dt.datetime(2000, daylast.month, daylast.day)
        shorten = dt.datetime(2000, 12, 31) - endofdata
        shorten = shorten.days

# Load land-sea mask
if options.maskfile:
    masknc = Dataset(options.maskfile, 'r')
    vname = options.maskvname
    mask = masknc.variables[vname][:]
    mask = mask.astype(np.bool)
    masknc.close()

# Load base period data
vname = options.tmaxvname
tmax = tmaxnc.variables[vname][(bpstart<=dates.year)&(dates.year<=bpend)]
original_shape = tmax.shape
if options.maskfile:
    tmax = tmax[:,mask]
if tmaxnc.variables[vname].units=='K': tmax -= 273.15
tminnc = MFDataset(options.tminfile, 'r')
vname = options.tminvname
tmin = tminnc.variables[vname][(bpstart<=dates.year)&(dates.year<=bpend)]
if options.maskfile:
    tmin = tmin[:,mask]
if tminnc.variables[vname].units=='K': tmin -= 273.15
tave_base = (tmax + tmin)/2.
del tmin
del tmax

# Remove leap days in gregorian calendars
if (calendar=='gregorian')|(calendar=='proleptic_gregorian')|\
            (calendar=='standard'):
    dates_base = dates[(bpstart<=dates.year)&(dates.year<=bpend)]
    tave_base = tave_base[(dates_base.month!=2)|(dates_base.day!=29),...]
    del dates_base

# Caclulate 90th percentile
tpct = np.ones(((daysinyear,)+tave_base.shape[1:]))*np.nan
window = np.zeros(daysinyear,dtype=np.bool)
wsize = 15.
window[-np.floor(wsize/2.):] = 1
window[:np.ceil(wsize/2.)] = 1
window = np.tile(window,bpend+1-bpstart)
if qtilemethod=='python':
    percentile = np.percentile
    parameter = 0
elif qtilemethod=='zhang':
    percentile = qtiler.quantile_zhang
    parameter = False
elif qtilemethod=='matlab':
    percentile = qtiler.quantile_R
    parameter = 5
elif qtilemethod=='climpact':
    percentile = qtiler.quantile_climpact
    parameter = False
for day in xrange(daysinyear):
    tpct[day,...] = percentile(tave_base[window,...], pcntl, parameter)
    window = np.roll(window,1)
del tave_base
del window

# Load data
tmax = tmaxnc.variables[options.tmaxvname][:]
tmin = tminnc.variables[options.tminvname][:]
if options.maskfile:
    tmax = tmax[:,mask]
if tmaxnc.variables[options.tmaxvname].units=='K': tmax -= 273.15
if options.maskfile:
    tmin = tmin[:,mask]
if tminnc.variables[options.tminvname].units=='K': tmin -= 273.15
tave = (tmax + tmin)/2.
del tmax
del tmin

# Remove leap days from tave
if (calendar=='gregorian')|(calendar=='proleptic_gregorian')|\
            (calendar=='standard'):
    tave = tave[(dates.month!=2)|(dates.day!=29),...]

# Remove incomplete starting year
first_year = dayone.year
if (dayone.month!=1)|(dayone.day!=1):
    first_year = dayone.year+1
    start = np.argmax(dates.year==first_year)
    tave = tave[start:,...]

# Calculate EHF
EHF = np.ones(tave.shape)*np.nan
for i in xrange(32,tave.shape[0]):
    EHIaccl = tave[i-2:i+1,...].sum(axis=0)/3. - \
            tave[i-32:i-2,...].sum(axis=0)/30.
    EHIsig = tave[i-2:i+1,...].sum(axis=0)/3. - \
            tpct[i-daysinyear*int((i+1)/daysinyear),...]
    EHF[i,...] = np.maximum(EHIaccl,1.)*EHIsig
EHF[EHF<0] = 0

def identify_hw(ehfs):
    """identify_hw locates heatwaves from EHF and returns an event indicator 
    and a duration indicator.
    """
    # Agregate consecutive days with EHF>0
    # First day contains duration
    events = (ehfs>0.).astype(np.int)
    for i in xrange(events.shape[0]-2,0,-1):
         events[i,events[i,...]>0] = events[i+1,events[i,...]>0]+1

    # Identify when heatwaves start with duration
    # Given that first day contains duration
    diff = np.zeros(events.shape)
    diff[1:,...] = np.diff(events, axis=0)
    endss = np.zeros(ehfs.shape,dtype=np.int)
    endss[diff>2] = events[diff>2]

    # Remove events less than 3 days
    events[diff==2] = 0
    events[np.roll(diff==2, 1, axis=0)] = 0
    events[diff==1] = 0
    del diff
    events[events>0] = 1
    events = events.astype(np.bool)
    endss[endss<3] = 0
    return events, endss

# For daily output
if dailyout:
    event, ends = identify_hw(EHF)

# Calculate metrics year by year
nyears = len(range(first_year,daylast.year+1))
if yearlyout:
    space = EHF.shape[1:]
    if len(space)>1:
        EHF = EHF.reshape(EHF.shape[0],space[0]*space[1])
    HWA = np.ones(((nyears,)+(EHF.shape[1],)))*np.nan
    HWM = HWA.copy()
    HWN = HWA.copy()
    HWF = HWA.copy()
    HWD = HWA.copy()
    HWT = HWA.copy()
    for iyear, year in enumerate(xrange(dayone.year,daylast.year)):
        if (year==daylast.year)&(season=='summer'): continue # Incomplete yr
        # Select this years season
        allowance = 10 # For including heawave days after the end of the season
        ifrom = startday + daysinyear*iyear
        ito = endday + daysinyear*iyear + allowance
        EHF_i = EHF[ifrom:ito,...]
        event_i, duration_i = identify_hw(EHF_i)
        # Remove events that start after the end of the season
        duration_i = duration_i[:-allowance]
        event_i = event_i[:-allowance]
        # Calculate metrics
        HWN[iyear,...] = (duration_i>0).sum(axis=0)
        HWF[iyear,...] = duration_i.sum(axis=0)
        HWD[iyear,...] = duration_i.max(axis=0)
        HWD[iyear,HWD[iyear,...]==0] = np.nan
        # HWM and HWA must be done on each gridcell
        for x in xrange(EHF_i.shape[1]):
            hw_mag = []
            # retrieve indices where heatwaves start.
            i = np.where(duration_i[:,x]>0)[0] # time
            d = duration_i[i,x] # duration
            if (d==0).all(): continue
            for hw in xrange(len(d)):
                # retireve this heatwave's EHF values and mean magnitude
                hwdat = EHF_i[i[hw]:i[hw]+d[hw],x]
                hw_mag.append(np.nanmean(hwdat))
            HWM[iyear,x] = np.nanmean(hw_mag)
            # Find the hottest heatwave magnitude
            idex = np.where(hw_mag==max(hw_mag))[0]
            # Find that heatwave's hottest day as EHF value.
            HWA[iyear,x] = EHF_i[i[idex]:i[idex]+d[idex],x].max()
        HWT[iyear,...] = np.argmax(event_i,axis=0)
    if len(space)>1:
    	EHF = EHF.reshape(EHF.shape[0],space[0],space[1])

# Save to netCDF
try:
    experiment = tmaxnc.__getattribute__('experiment')
    model = tmaxnc.__getattribute__('model_id')
    realization = tmaxnc.__getattribute__('realization')
except AttributeError:
    experiment = ''
    model = ''
    realization = ''
if yearlyout:
    yearlyout = Dataset('EHF_heatwaves_%s_%s_r%s_yearly_%s.nc'%(model, 
            experiment, realization, season), mode='w')
    yearlyout.createDimension('time', len(range(first_year,
            daylast.year+1)))
    yearlyout.createDimension('lon', tmaxnc.dimensions['lon'].__len__())
    yearlyout.createDimension('lat', tmaxnc.dimensions['lat'].__len__())
    yearlyout.createDimension('day', daysinyear)
    setattr(yearlyout, "author", "Tammas Loughran")
    setattr(yearlyout, "contact", "t.loughran@student.unsw.edu.au")
    setattr(yearlyout, "source", "https://github.com/tammasloughran/ehfheatwaves")
    setattr(yearlyout, "date", dt.datetime.today().strftime('%Y-%m-%d'))
    setattr(yearlyout, "script", "ehfheatwaves_CMIP5.py")
    if model:
        setattr(yearlyout, "model_id", model)
        setattr(yearlyout, "experiment", experiment)
        setattr(yearlyout, "realization", "%s"%(realization))
    setattr(yearlyout, "period", "%s-%s"%(str(first_year),str(daylast.year)))
    setattr(yearlyout, "base_period", "%s-%s"%(str(bpstart),str(bpend)))
    setattr(yearlyout, "percentile", "%sth"%(str(pcntl)))
    setattr(yearlyout, "frequency", "yearly")
    setattr(yearlyout, "season", season)
    if season=='summer':
        definition = 'Nov-Mar'
    elif season=='winter':
        definition = 'May-Sep'
    setattr(yearlyout, "definition", definition)
    setattr(yearlyout, "season_note", "The year of a season is the year it starts in")
    setattr(yearlyout, "git_commit", subprocess.check_output(['git', 'rev-parse', 'HEAD']))
    setattr(yearlyout, "tmax_file", options.tmaxfile)
    setattr(yearlyout, "tmin_file", options.tminfile)
    if options.maskfile:
        setattr(yearlyout, "mask_file", options.maskfile)
    otime = yearlyout.createVariable('time', 'f8', 'time', 
            fill_value=-999.99)
    setattr(otime, 'units', 'year')
    olat = yearlyout.createVariable('lat', 'f8', 'lat')
    setattr(olat, 'standard_name', 'latitude')
    setattr(olat, 'long_name', 'Latitude')
    setattr(olat, 'units', 'degrees_north')
    setattr(olat, 'axis', 'Y')
    olon = yearlyout.createVariable('lon', 'f8', 'lon')
    setattr(olon, 'standard_name', 'longiitude')
    setattr(olon, 'long_name', 'Longitude')
    setattr(olon, 'units', 'degrees_east')
    setattr(olon, 'axis', 'X')
    otpct = yearlyout.createVariable('t%spct'%(pcntl), 'f8', 
	    ('day','lat','lon'), fill_value=-999.99)
    setattr(otpct, 'long_name', '90th percentile')
    setattr(otpct, 'units', 'degC')
    setattr(otpct, 'description', 
            '90th percentile of %s-%s'%(str(bpstart),str(bpend)))
    HWAout = yearlyout.createVariable('HWA_EHF', 'f8', ('time','lat','lon'), 
            fill_value=-999.99)
    setattr(HWAout, 'long_name', 'Heatwave Amplitude')
    setattr(HWAout, 'units', 'degC2')
    setattr(HWAout, 'description', 
            'Peak of the hottest heatwave per year')
    HWMout = yearlyout.createVariable('HWM_EHF', 'f8', ('time','lat','lon'),
            fill_value=-999.99)
    setattr(HWMout, 'long_name', 'Heatwave Magnitude')
    setattr(HWMout, 'units', 'degC2')
    setattr(HWMout, 'description', 'Average magnitude of the yearly heatwave')
    HWNout = yearlyout.createVariable('HWN_EHF', 'f8', ('time', 'lat', 'lon'), 
            fill_value=-999.99)
    setattr(HWNout, 'long_name', 'Heatwave Number')
    setattr(HWNout, 'units','')
    setattr(HWNout, 'description', 'Number of heatwaves per year')
    HWFout = yearlyout.createVariable('HWF_EHF', 'f8', ('time','lat','lon'), 
            fill_value=-999.99)
    setattr(HWFout, 'long_name','Heatwave Frequency')
    setattr(HWFout, 'units', 'days')
    setattr(HWFout, 'description', 'Proportion of heatwave days per season')
    HWDout = yearlyout.createVariable('HWD_EHF', 'f8', ('time','lat','lon'), 
            fill_value=-999.99)
    setattr(HWDout, 'long_name', 'Heatwave Duration')
    setattr(HWDout, 'units', 'days')
    setattr(HWDout, 'description', 'Duration of the longest heatwave per year')
    HWTout = yearlyout.createVariable('HWT_EHF', 'f8', ('time','lat','lon'), 
            fill_value=-999.99)
    setattr(HWTout, 'long_name', 'Heatwave Timing')
    setattr(HWTout, 'units', 'days from strat of season')
    setattr(HWTout, 'description', 'First heat wave day of the season')
    otime[:] = range(first_year, daylast.year+1)
    olat[:] = tmaxnc.variables['lat'][:]
    olon[:] = tmaxnc.variables['lon'][:]
    dummy_array = np.ones((daysinyear,)+original_shape[1:])*np.nan
    if options.maskfile:
        dummy_array[:,mask] = tpct
        otpct[:] = dummy_array.copy()
        dummy_array = np.ones((nyears,)+original_shape[1:])*np.nan
        dummy_array[:,mask] = HWA
        HWAout[:] = dummy_array.copy()
        dummy_array[:,mask] = HWM
        HWMout[:] = dummy_array.copy()
        dummy_array[:,mask] = HWN
        HWNout[:] = dummy_array.copy()
        dummy_array[:,mask] = HWF
        HWFout[:] = dummy_array.copy()
        dummy_array[:,mask] = HWD
        HWDout[:] = dummy_array.copy() 
        dummy_array[:,mask] = HWT
        HWTout[:] = dummy_array.copy()
    else:
        otpct[:] = tpct
        HWAout[:] = HWA.reshape((nyears,)+space)
        HWMout[:] = HWM.reshape((nyears,)+space)
        HWNout[:] = HWN.reshape((nyears,)+space)
        HWFout[:] = HWF.reshape((nyears,)+space)
        HWDout[:] = HWD.reshape((nyears,)+space)
        HWTout[:] = HWT.reshape((nyears,)+space)
    yearlyout.close()

if dailyout:
    dailyout = Dataset('EHF_heatwaves_%s_%s_r%s_daily.nc'\
            %(model, experiment, realization), mode='w')
    dailyout.createDimension('time', EHF.shape[0])
    dailyout.createDimension('lon', tmaxnc.dimensions['lon'].__len__())
    dailyout.createDimension('lat', tmaxnc.dimensions['lat'].__len__())
    setattr(dailyout, "author", "Tammas Loughran")
    setattr(dailyout, "contact", "t.loughran@student.unsw.edu.au")
    setattr(dailyout, "source", "https://github.com/tammasloughran/ehfheatwaves")
    setattr(dailyout, "date", dt.datetime.today().strftime('%Y-%m-%d'))
    setattr(dailyout, "script", "ehfheatwaves_CMIP5.py")
    setattr(dailyout, "period", "%s-%s"%(str(first_year),str(daylast.year)))
    setattr(dailyout, "base_period", "%s-%s"%(str(bpstart),str(bpend)))
    setattr(dailyout, "percentile", "%sth"%(str(pcntl)))
    if model:
        setattr(dailyout, "model_id", model)
        setattr(dailyout, "experiment", experiment)
        setattr(dailyout, "realization", realization)
    setattr(dailyout, "git_commit", subprocess.check_output(['git', 'rev-parse', 'HEAD']))
    setattr(dailyout, "tmax_file", options.tmaxfile)
    setattr(dailyout, "tmin_file", options.tminfile)
    if options.maskfile:
        setattr(dailyout, "mask_file", str(options.maskfile))
    otime = dailyout.createVariable('time', 'f8', 'time',
                    fill_value=-999.99)
    setattr(otime, 'units', 'days since %s-01-01'%(first_year))
    if (calendar=='gregorian')|(calendar=='proleptic_gregorian')|(calendar=='standard'):
        calendar = '365_day'
    setattr(otime, 'calendar', calendar)
    olat = dailyout.createVariable('lat', 'f8', 'lat')
    setattr(olat, 'standard_name', 'latitude')
    setattr(olat, 'long_name', 'Latitude')
    setattr(olat, 'units', 'degrees_north') 
    olon = dailyout.createVariable('lon', 'f8', 'lon')
    setattr(olon, 'standard_name', 'longitude')
    setattr(olon, 'long_name', 'Longitude')
    setattr(olon, 'units', 'degrees_east')
    oehf = dailyout.createVariable('ehf', 'f8', ('time','lat','lon'),
                fill_value=-999.99)
    setattr(oehf, 'standard_name', 'EHF')
    setattr(oehf, 'long_name', 'Excess Heat Factor')
    setattr(oehf, 'units', 'degC2')
    oevent = dailyout.createVariable('event', 'f8', ('time','lat','lon'),
                fill_value=-999.99)
    setattr(oevent, 'long_name', 'Event indicator')
    setattr(oevent, 'description', 'Indicates whether a heatwave is happening on that day')
    oends = dailyout.createVariable('ends', 'f8', ('time','lat','lon'),
                        fill_value=-999.99)
    setattr(oends, 'long_name', 'Duration at start of heatwave')
    setattr(oends, 'units', 'days')
    otime[:] = range(1,nyears*daysinyear+1-shorten,1)
    olat[:] = tmaxnc.variables['lat'][:]
    olon[:] = tmaxnc.variables['lon'][:]
    if options.maskfile:
        dummy_array = np.ones((EHF.shape[0],)+original_shape[1:])*np.nan
        dummy_array[:,mask] = EHF
        oehf[:] = dummy_array.copy()
        dummy_array[:,mask] = event
        oevent[:] = dummy_array.copy()
        dummy_array[:,mask] = ends
        oends[:] = dummy_array.copy()
    else:
        oehf[:] = EHF
        oevent[:] = event
        oends[:] = ends
    dailyout.close()
