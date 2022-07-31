# AUTOGENERATED! DO NOT EDIT! File to edit: 00_processing.ipynb (unless otherwise specified).

__all__ = ['load_actiwatch_data', 'SALAFrame', 'remove_first_day']

# Cell
import numpy as np
import pandas as pd

from joblib import Parallel, delayed
from pandas.tseries.holiday import USFederalHolidayCalendar as calendar
from astral import LocationInfo, sun, pytz

import glob
import sys

# Internal Cell
def firstAndLastLight(data, threshold_list, resamp=False):
    ''' firstAndLastLight(data, threshold_list, resamp=False) applies all thresholds in the list to each unique person-day in the data, finding the first and last times as well as total times light intensity is above those thresholds for any non-zero number.  A 0 threshold is a request to calc amount of time spent at 5 lux and under.  Time resampling of the data is done if resamp is of the form [func name,'time'], such as [np.mean,'5T'] or [np.max,'15T'].'''
    ids = data.UID.unique()
    firstlight = []
    lastlight = []
    min2fl = []
    min2ll = []
    whoswatch = []
    watchperiod = []
    thresholds = []
    datelist = []
    grouplist = []
    totalact=[]
    tabvlight=[]
    tabvlightAM=[]
    tluxmin = []
    tluxminAM = []

    for uid in ids:
            these_rows = (data.UID == uid) & (data['Interval Status'].isin(['ACTIVE','REST'])) & np.logical_not(data['Off-Wrist Status'])

            assert (these_rows.sum() > 0),"ISSUE: "+uid+" has no ACTIVE rows"


            daysofdata = set( data[ these_rows ].index.date )

            if 'Group' in data.columns:
                group = data[data.UID == uid].iloc[0,:]["Group"]
            elif 'Season' in data.columns:
                group = data[data.UID == uid].iloc[0,:]["Season"]
            else:
                print("ISSUE: Potentially no group variable?")
                raise ValueError

            for a_day in daysofdata:
                nextday = a_day + pd.tseries.offsets.Day()
                nextday = nextday.date().isoformat()
                thisday = a_day.isoformat()
                daylight = data[these_rows][thisday + ' 04:00:00' : nextday + ' 03:59:00']['White Light']
                if resamp: # resample if the function argument is set
                    daylight = daylight.resample(resamp[1]).apply(resamp[0])

                # watch update period for todays data
                dperiod = daylight.index.to_series().diff().min()
                dpmult = dperiod/pd.Timedelta('1 min') # multiplier to get lux-minutes later

                lxmin =  dpmult * daylight.sum()
                lxminAM = dpmult * daylight[:thisday + ' 12:00'].sum()

                for a_thresh in threshold_list:
                    thresholds.append(a_thresh)
                    if a_thresh == 0 :
                        abovethresh = daylight.index[ daylight < 5] # 0 theshold is a request to calculate under 5 lux
                        abovethreshAM = daylight[:thisday + ' 12:00'].index[ daylight[:thisday + ' 12:00'] < 5]
                    else:
                        abovethresh = daylight.index[ daylight > a_thresh]
                        abovethreshAM = daylight[:thisday + ' 12:00'].index[ daylight[:thisday + ' 12:00'] > a_thresh]
                    tabvlight.append( dperiod * len(abovethresh))
                    tabvlightAM.append( dperiod * len(abovethreshAM))
                    tluxmin.append( lxmin )
                    tluxminAM.append( lxminAM )
                    watchperiod.append(dperiod)
                    datelist.append(a_day)
                    grouplist.append(group)
                    try:
                        timelight = abovethresh[-1] # last time is above threshold
                        mins4am = (timelight.time().hour - 4) * 60 + timelight.time().minute
                        if mins4am < 0: # if after midnight, then value above is negative
                            mins4am += 24 * 60 # fix by adding 24 hours (in minutes) to it
                    except IndexError: # there is no above threshold level all day long
                        timelight = np.nan
                        mins4am = np.nan
                    lastlight.append(timelight)
                    min2ll.append(mins4am)
                    try:
                        timelight = abovethresh[0] # first time is above threshold
                        mins4am = (timelight.time().hour - 4) * 60 + timelight.time().minute
                        if mins4am < 0: # if after midnight, then value above is negative
                            mins4am += 24 * 60 # fix by adding 24 hours (in minutes) to it
                    except IndexError: # there is no above threshold level all day long
                        timelight = np.nan
                        mins4am = np.nan
                    firstlight.append(timelight)
                    min2fl.append(mins4am)
                    whoswatch.append(uid)
    return pd.DataFrame( {'UID': whoswatch, 'Date': datelist, 'Threshold': thresholds,
                          'Last Light': lastlight, 'Mins to LL from 4AM': min2ll,
                          'First Light': firstlight, 'Mins to FL from 4AM': min2fl,
                          'Time above threshold': tabvlight, 'Time above threshold AM': tabvlightAM,
                          'Minutes above threshold': [ el.total_seconds()/60.0 for el in tabvlight],
                          'Minutes above threshold AM': [ el.total_seconds()/60.0 for el in tabvlightAM],
                          'Lux minutes': tluxmin, 'Lux minutes AM': tluxminAM,
                          'Group': grouplist,
                          'Watch period': watchperiod
                         } )


# Cell
def load_actiwatch_data(path,uidprefix=''):

    if path[-1]!='/':    # make sure path has a trailing slash
        path = path + '/'
    files = glob.glob(path+'*.csv') # gets all .csv filenames in directory
    if not files: # let us know if there's no .csv files in path!
        print('Oops! No csv files in ' + path)
        raise OSError
    else:
        print('Found {} csv files in {}. Pass #1, raw data'.format(len(files),path))
        for _ in range(len(files)):
            sys.stdout.write('.')
        sys.stdout.write('\n')

    frames = [] # list of data frames we will get from processing the files
    for afile in files:
        sys.stdout.write('.')
        sys.stdout.flush()
        with open(afile,'r') as f:
            # we need to skip any previous analysis that's at the top of the
            # file and get to the raw data below it
            while True:
                currentFilePosition = f.tell()
                line = f.readline()
                if line == '': # empty line read if EOF
                    print('EOF without retrieving raw data: ' + afile)
                    break # get out of this loop so we can go on to next file
                cells = line.split(',') # comma seperated values (CSV)
                columns = tuple(filter( None, [el.strip().strip('\"') for el in cells])) #need tuple because in python3 filter is evaluated in lazy fasion
                # DEBUG print len(columns),': ', columns
                # the raw data has a 12 element long header line:
                # Line , Date , Time , Off-wrist status , ....
                if ( (len(columns)==12) and (columns[0] == 'Line') ):
                    break


            if line == '': #empty line read if EOF
                continue # go on to the next file

            # move the file pointer back to the beginning of the header line
            # so we can read it in as a header for the DataFrame
            f.seek(currentFilePosition)

            # generate unique identifier for this individual based on filename
            # assumes filename has format:
            # /path/to/file/UID_Month_Date_Year_Time_*.csv
            UID = uidprefix + afile.split('/')[-1].split('_')[0]

            # grab the data, ignore the first column which just has line numbers
            # stuff the two Date/Time columns into a single Date variable
            fileData = pd.read_csv(f, index_col=False, usecols=columns[1:],
                                       parse_dates={'DateTime': [0,1]})
            fileData['UID'] = UID

            frames.append(fileData)

    rawWatchData = pd.concat(frames) # make one big dataframe
    rawWatchData.index = rawWatchData['DateTime']
    del rawWatchData['DateTime']
#%%
    print('\nPass #2, data summary')
    for _ in range(len(files)):
        sys.stdout.write('.')
    sys.stdout.write('\n')

    frames = [] # list of data frames we will get from processing the files
    for afile in files:
        sys.stdout.write('.')
        sys.stdout.flush()
        with open(afile,'r') as f:
            # we need to skip to the summary statistics
            while True:
                summaryFilePosition = f.tell()
                line = f.readline()
                if line == '': #empty line read if EOF
                    print('EOF without retrieving summary data: ' + afile)
                    break # get out of this loop so we can go on to next file
                cells = line.split(',') # comma seperated values (CSV)
                columns = tuple(filter( None, [el.strip().strip('\"') for el in cells])) #need tuple because in python3 filter is evaluated in lazy fasion
                # print len(columns), columns[0]
                # the raw data has a 35 element long header line:
                # Interval Type , Interval #, Start Date, ....
                if ( (len(columns)==35) and (columns[0] == 'Interval Type') ):
                    break

            if line == '': #empty line read if EOF
                continue # go on to the next file

            # advance to find out how many lines the summary includes
            # since we don't care about excluded intervals and they
            # also don't have a full set of columns, we stop there
            nlines = 0
            toskip = [1] # we skip the line after the header, it has units
            while True:
                line = f.readline()
                if line == '': #empty line read if EOF
                    print('EOF without retrieving summary data: ' + afile)
                    break # get out of this loop so we can go on to next file
                cells = line.split(',') # comma seperated values (CSV)
                columns = tuple(filter( None, [el.strip().strip('\"') for el in cells])) #need tuple because in python3 filter is evaluated in lazy fasion
                nlines += 1

                if columns:
                    if columns[0].find('Summary'):
                        toskip.append(nlines)

                    if columns[0] == 'EXCLUDED':
                        break

            if line == '': #empty line read if EOF
                continue # go on to the next file

            # move the file pointer back to the beginning of the header line
            # so we can read it in as a header for the DataFrame
            f.seek(summaryFilePosition)

            # generate unique identifier for this individual based on filename
            # assumes filename has format:
            # /path/to/file/UID_Month_Date_Year_Time_*.csv
            UID = uidprefix + afile.split('/')[-1].split('_')[0]

            # grab the data, ignore the first column which just has line numbers
            # stuff the two Date/Time columns into a single Date variable
            fileData = pd.read_csv(f, index_col=False, skiprows=toskip,
                                       nrows=nlines, skip_blank_lines=True)
            fileData['UID'] = UID

            frames.append(fileData)

    if frames:
        summaryWatchData = pd.concat(frames)
    else:
        summaryWatchData = None
    #%%

    return (rawWatchData, summaryWatchData)


# Cell
class SALAFrame:
    """
    DataFrame-like storage for actiwatch data loaded either from a directory of csv files
    or an existing SALA or dataframe object.


        Attributes
        ----------
        data: pd.DataFrame or None
            Initialized as None, but can be set as a dataframe, which is expected to contain
            light and sleep information consistent with SALA formatting. It should only be
            pre-set to an existing dataframe when trying to migrate existing data to a SALA
            object.

        directory: dictionary or None
            Dictionary style pairing of grouping names serving as keys (e.g. baseline,
            intervention), with corresponding values as relative file paths storing csv
            files to be read as data.

        timezone: str
            Single timezone specified for all data within the object. A list of
            valid timezones can be obtained from pytz.all_timezones. Note that it is impossible
            for different timezones to be present (all data must be converted to a single timezone)

        latitude: float
            Latitude position for sunrise/sunset calculations.

        longitude: float
            Longitude position for sunrise/sunset calculations.

        Methods
        -------
        init(data=None, directory=None, timezone=None, latitude=None, longitude=None)
            Initialization with a pre-processed SALA-eqsue dataframe or raw data and file details
            for loading and processing data.

        get_raw_data_from_key(key, directory, grouping='Group')
            Loads and combines all raw data from multiple csv files within a specified file source
            based on a given key. Key indicates a grouping of multiple csvs.

        get_raw_data(directory, grouping='Group')
            Loads and combines all raw data from multiple csv files for all keys within
            a directory for a given directory of file sources.

        export(data)
            Exports the data within a SALA object to a parquet file format.

        process_data(raw_data, thresholds)
            Handles unprocessed combined raw data outputting first and last light times,
            and group identifiers for all specified light thresholds.

        sun_timings()
            Calculates sunset and sunrise timing information for currently stored SALA
            data, based on the timezone info within the stored data.

        do_everything()
            TO ADD AFTER TESTING OTHER NEW FUNCTIONS.

        process_sleep_data
            Processes sleep data for existing timing data, generating a summary dataframe
            based on the number of sleep periods within the data.
    """

    def __init__(self, latitude, longitude, timezone, data=None, directory = None):
        """
        Initializes a SALA object either from existing parsed timing data, or from a directory
        of csvs. Timezone information can be optionally included to allow for sunset, sunrise
        data to be added.

        #### Parameters

            timezone: str
                A valid timezone (a list of timezones can be obtained from pytz.all_timezones).

            latitude: float
                Latitude position for sunrise/sunset calculations. Northern latitudes
                should be positive values.

            longitude: float
                Longitude position for sunrise/sunset calculations. Eastern longitudes
                should be positive values.

            data: pd.DataFrame (optional)
                If not None, data should be a pre-processed SALA-format dataframe, expected to contain
                details on light and sleep information.

            directory: dictionary (optional)
                Dictionary of valid folder names to load actiwatch data from.
                Folders should have .csv files in them.
        """
        self._data = data
        self._directory = directory
        self._timezone = timezone
        self._latitude = latitude
        self._longitude = longitude

    @property
    def data(self):
        """Getter method for data."""
        return self._data

    @data.setter
    def data(self, value):
        """Setter method for data."""
        if type(value) != pd.DataFrame:
            raise TypeError("Error: Data must be of type pd.DataFrame")
        self._data = value

    @property
    def directory(self):
        """Getter method for directory."""
        return self._directory

    @directory.setter
    def directory(self, value):
        """Setter method for directory."""
        if type(value) != str:
            raise TypeError("Error: directory must be a valid string")
        self._directory = value

    @property
    def timezone(self):
        """Getter method for timezone."""
        return self._timezone

    @directory.setter
    def timezone(self, value):
        """Setter method for timezone."""
        if type(value) != str:
            raise TypeError("Error: timezone must be a valid string")
        self._timezone = value

    @property
    def latitude(self):
        """Getter method for latitude."""
        return self._latitude

    @directory.setter
    def latitude(self, value):
        """Setter method for latitude."""
        if not isinstance(value, (int, float, complex)):
            raise TypeError("Error: latitude must be a numeric")
        self._latitude = value

    @property
    def longitude(self):
        """Getter method for longitude."""
        return self._longitude

    @longitude.setter
    def longitude(self, value):
        """Setter method for longitude."""
        if not isinstance(value, (int, float, complex)):
            raise TypeError("Error: longitude must be a numeric")
        self._longitude = value

    def get_raw_data_from_key(self, key, directory = None, grouping = 'Group'):
        """Loads and combines raw actiwatch data from any csv files found in
           the specified directory matching a particular key within the directory.

            #### Parameters

            key: str

                The key to load actiwatch data from (for example, "v1").

            directory: dict

                Dictionary of valid folders to load actiwatch data from.
                Folders should have .csv files in them. If no dictionary
                is provided, it uses the one initialized as part of the SALA
                object.

            grouping: str

                Name of the generated column for specifying groupings, where
                the values will be the name of the key given. Default = 'Group'.

            #### Returns

            All of the raw unprocessed data within the directory matching a specified key.

    """
        if directory is None and self._directory is None:
            raise ValueError("Error: a valid source of data must be provided.")
        if directory is not None:
            self._directory = directory
        raw_data = load_actiwatch_data(self.directory[key], uidprefix = key)[0]
        raw_data[grouping] = key
        return raw_data

    def get_raw_data(self, outfile, directory = None, grouping = 'Group', export = True):
        """Loads and combines raw actiwatch data from any csv files found in
           the specified directory for all keys within the directory.

            #### Parameters

            outfile: str

                Directory to save to. (e.g. ../SALA/example_output/)

            directory: dict

                Dictionary of valid folders to load actiwatch data from.
                Folders should have .csv files in them. If no dictionary
                is provided, it uses the one initialized as part of the SALA
                object.

            grouping: str

                Name of the generated column for specifying groupings, where
                the values will be the name of the key given. Default = 'Group'.

            export: bool

                Whether or not to export combined raw data to a parquet file saved in the designated
                outfile location.

            #### Returns

            All of the raw unprocessed data within the directory for all keys as a single
            dataframe.

    """
        if directory is None and self._directory is None:
            raise ValueError("Error: a valid source of data must be provided.")
        if directory is not None:
            self._directory = directory
        raw_results = (
            Parallel(n_jobs=len(self._directory))(delayed(self.get_raw_data_from_key)(key, self._directory) for key in self._directory.keys())
                   )
        # save data to parquet file
        all_data = pd.concat(raw_results)

        if export:
            all_data.to_parquet(outfile + "raw.parquet", engine = 'fastparquet',
                                   compression = "gzip")

        return all_data

    def export(self, outfile, data=None):
        """
        Exports existing timing data to a parquet format.

        #### Parameters
            outfile: str

                Directory to save to. (e.g. ../SALA/example_output/)
            data: pd.DataFrame

            Desired dataframe for exporting.
        """

        if self.data is None and data is None:
            raise Exception("Error: no timing data available to export.")
        if data is None:
            data = self.data
        # putting date information in a parquet valid format
        data["Date"] = data["Date"].values.astype("datetime64[s]")
        data.to_parquet(f"{outfile}timing.parquet",
                               engine = "fastparquet", compression="gzip")


    def process_data(self,
                     raw_data,
                     thresholds):
        """Handles unprocessed combined raw data outputting first and last light times,
            and group identifiers for all specified light thresholds.

        #### Parameters

        raw_data: pd.DataFrame

            Combined dataframe of all raw data from desired directory. This can be
            accomplished by using the get_raw_data function within the SALA class.

        thresholds: list

            List of light thresholds for the watch data.

        #### Returns

            Processed timing data in a dataframe format, with specific identifier columns based
            on weekday and weekend/holiday groupings.
        """
        timing_results = (Parallel(n_jobs=len(thresholds))
        (delayed(firstAndLastLight)(raw_data, threshold) for threshold in thresholds)
                         )
        timing_data = pd.concat(timing_results)

        # loading federal holidays to classify dates as weekend/holiday
        cal = calendar()
        holidays = (
        cal.holidays(start = timing_data.Date.min(), end = timing_data.Date.max())
    )
        # retrieve day number (e.g. 0) from date index
        timing_data["DayofWeek"] = pd.DatetimeIndex(timing_data["Date"]).dayofweek
        days = ["Mon", "Tues", "Wed", "Thu", "Fri", "Sat", "Sun"]
        day_type = ["Weekday","Weekday","Weekday",
                "Weekday","Weekday","Weekend/Holiday","Weekend/Holiday"]

        # result should be a combination of Group identifier and the day of the week (e.g. Mon)
        timing_data["GroupDayofWeek"] = (timing_data["Group"] + np.array(days)[timing_data["DayofWeek"]])

        is_holiday = pd.to_datetime(timing_data["Date"]).isin(holidays)
        weekends = (timing_data["Group"] + "Weekend/Holiday")

         # result should be a combination of Group identifier and day type (e.g. Weekday)
        day_types = (timing_data["Group"] + np.array(day_type)[timing_data["DayofWeek"]])

        timing_data["GroupDayType"] = day_types.where(~is_holiday).combine_first(weekends.where(is_holiday))
        timing_data["Weekend/Holiday"] = ((timing_data["DayofWeek"] > 4) | is_holiday)

        self._data = timing_data
        timing_data["Watch period"] = pd.to_timedelta(timing_data["Watch period"])

        return timing_data

    def sun_timings(self):
        """Calculates sunrise and sunset timing information for data present in the
        SALA object.

        #### Returns

            Modified timing data with sunrise and sunset calculations
        """

        if self._latitude is None or self._longitude is None:
            raise ValueError("Error: Missing timezone, latitude, or longitude info.")
        # add location info for calculating astral data
        city = LocationInfo(timezone = self._timezone, latitude = self._latitude, longitude = self._longitude)
        self._data["Sunrise"] = self._data["Date"].apply( lambda x: sun.sunrise(city.observer,
                                                                           x,
                                                                           tzinfo = city.tzinfo))
        self._data["Sunset"] = self._data["Date"].apply( lambda x: sun.sunset(city.observer,
                                                                         x,
                                                                         tzinfo = city.tzinfo))
        return self._data


    def do_everything(self, outfile, thresholds, directory = None, grouping = "Group", export = True):
        """Handles the full SALA pipeline (excluding sleep period analysis), from processing and combining raw data
        to parsing and calculating processed data with sunrise and sunset information. First loads and compiles
        all existing raw data for every key within the given directory. Then processes all raw data, calculating
        additional information for all specified light thresholds. Also adds sunrise and sunset information.

        #### Parameters

        outfile: str

                Directory to save to. (e.g. ../SALA/example_output/)

        thresholds: list

            List of light thresholds for the watch data.

        directory: dict

            Dictionary of valid folders to load actiwatch data from.
            Folders should have .csv files in them. If no dictionary
            is provided, it uses the one initialized as part of the SALA
            object.

        grouping: str

            Name of the generated column for specifying groupings, where
            the values will be the name of the key given. Default = 'Group'.

        export: bool

            Whether or not to export processed timing data to a parquet file saved in the designated
            outfile location.

        #### Returns

            Processed timing data in a dataframe format, with specific identifier columns based
            on weekday and weekend/holiday groupings, and included sunrise and sunset calculations.
        """
        if directory == None:
            directory = self.directory

        raw_data = self.get_raw_data(outfile, directory, grouping)
        data = self.process_data(raw_data, thresholds)
        self.sun_timings()

        if export:
            self.export(data = self.data, outfile = outfile)

        return self._data


    def process_sleep(self, raw_data, sleep_split = "18:00", num_sleeps = 3):
        """Processes sleep data for existing timing data.

        #### Parameters

        raw_data: pd.DataFrame

            Combined dataframe of all raw data from desired directory. This can be
            accomplished by using the get_raw_data function within the SALA class.

        sleep_split: str

            Time to split the sleep day. Default is "18:00", which is 6:00PM.

        num_sleeps: int

            Cutoff for number of sleeps to display in first resulting frame.
            Default = 3, frame will store days with 3+ sleep instances

        #### Returns

            short_frame: pd.DataFrame

                Onset, offset, and duration for sleep periods on days with
                more than num_sleeps number of sleep periods

            timing_data: pd.DataFrame

                Modified timing data with included sleep information

        """
        sleepers = []
        sleep_onsets = []
        sleep_offsets = []
        sleep_durations = []
        sleep_onsetMSLMs = []
        sleep_offsetMSLMs = []

        timing_data = self._data
        for arow in timing_data.itertuples():
            UID = arow.UID
            DT = pd.to_datetime(arow.Date)
            TM = pd.to_datetime(DT + pd.Timedelta("1 day"))
            today = DT.strftime("%Y-%m-%d")

            nextday = TM.strftime("%Y-%m-%d")

            # taking raw timing data entry and splitting a "sleep day" at 6pm
            # under the assumption that people do not end their days that early
            day_split = raw_data.query("UID == @UID").loc[today +" " + sleep_split:nextday + " 18:00"]

            # REST-S = watch thinks user is asleep
            asleep = day_split[ day_split["Interval Status"] == "REST-S"].copy()

            # there may be more than one sleep period in a given day's data
            # new sleep period = when there is more than 1 hour between successive REST-S entries
            sleep_periods = []
            per = 0
            count = 0

            try:
                lt = asleep.index[0]
                for time in asleep.index:
                    # allow up to 1 hour of being awake in the middle of the night
                    if (time - lt > pd.Timedelta("1 hour")):
                        per += 1
                    lt = time
                    sleep_periods.append(per)
                asleep["Sleep period"] = sleep_periods
            except IndexError:
                asleep["Sleep period"] = [pd.to_datetime(0)]

            try:
            # calc sleep onsets/offsets/duration for each period of sleep in a person-day of data
                sleeps = asleep.reset_index().groupby("Sleep period").apply( lambda x: pd.DataFrame({
                         "Sleep onset": [x.DateTime.min()],
                         "Sleep offset": [x.DateTime.max()],
                         "Sleep duration": [x.DateTime.max() - x.DateTime.min()]
                         }, index = x.DateTime.dt.normalize() ))
            # if the value is = 0 -> np.int64 (not a DateTime)
            except AttributeError:
                sleeps = asleep.reset_index().groupby("Sleep period").apply( lambda x: pd.DataFrame({
                 "Sleep onset": [pd.to_datetime(DT)],
                 "Sleep offset": [pd.to_datetime(DT)],
                 "Sleep duration": [pd.to_timedelta(x.DateTime.max() - x.DateTime.min())]
                 }))
            sleeps = sleeps.drop_duplicates().sort_values(by="Sleep duration", ascending = False)
            onset = sleeps.iloc[0]['Sleep onset']
            offset = sleeps.iloc[0]['Sleep offset']
            dur =  sleeps.iloc[0]['Sleep duration']

            # if onset is actually a datetime
            if not isinstance(onset, np.int64):
                onMSLM = (onset - DT).total_seconds() / 60.0

            # if offset is actually a datetime
            if not isinstance(offset, np.int64):
                offMSLM = np.maximum((offset - TM).total_seconds() / 60.0, 0.0)

            sleep_onsets.append(onset)
            sleep_offsets.append(offset)
            sleep_durations.append(dur)
            sleep_onsetMSLMs.append(onMSLM)
            sleep_offsetMSLMs.append(offMSLM)
            sleep_count = sleeps.shape[0]

            # adding to short_frame
            if sleep_count >= num_sleeps:
                sleeps['UID'] = UID
                sleeps['DT'] = DT
                sleeps.reset_index(drop = True).set_index(['UID','DT'])
                sleepers.append(sleeps)
        try:
            short_frame = (
                           pd.concat(sleepers).reset_index().drop('DateTime',axis=1)
                           .set_index(['UID','DT']).drop_duplicates()
                           )
        except:
            print("Error: Could not concatenate multiple sleep instance data.")
            return timing_data
        timing_data["Sleep onset"] = sleep_onsets
        timing_data["Sleep offset"] = sleep_offsets
        timing_data["Sleep duration"] = sleep_durations
        timing_data["Sleep onset MSLM"] = sleep_onsetMSLMs
        timing_data["Sleep offset MSLM"] = sleep_offsetMSLMs

        self._data = timing_data

        return short_frame, timing_data

# Cell
def remove_first_day(data):
    """An example function that removes data
    from the first day of recording. Typically the first
    day has no light data for these watches (represented
    as 'NaT')
    """
    return data[(data["Last Light"].apply(np.isnat) == False)
               & (data["Date"] != data["Date"].min())]
