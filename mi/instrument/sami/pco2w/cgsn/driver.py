
"""
@package mi.instrument.sami.pco2w.cgsn.driver
@file marine-integrations/mi/instrument/sami/pco2w/cgsn/driver.py
@author Chris Center
@brief Driver for the cgsn
Release notes:

Initial release of the Sami PCO2 driver
  : = Instrument Status Word (Long)
  ? = Instrument Error Return Code (i.e. ?02)
  * = Record (please check)
"""

__author__ = 'Chris Center'
__license__ = 'Apache 2.0'

import re
import string
import time
import datetime
import calendar
import sys      # Exceptions

from mi.core.log import get_logger ; log = get_logger()

from mi.core.common import BaseEnum
from mi.core.time import get_timestamp
from mi.core.time import get_timestamp_delayed
from mi.core.instrument.instrument_protocol import CommandResponseInstrumentProtocol
from mi.core.instrument.instrument_fsm import InstrumentFSM
from mi.core.instrument.instrument_driver import SingleConnectionInstrumentDriver
from mi.core.instrument.instrument_driver import DriverEvent
from mi.core.instrument.instrument_driver import DriverAsyncEvent
from mi.core.instrument.instrument_driver import DriverProtocolState
from mi.core.instrument.instrument_driver import DriverParameter
from mi.core.instrument.instrument_driver import ResourceAgentState
from mi.core.exceptions import InstrumentParameterException
from mi.core.instrument.protocol_param_dict import ParameterDictVisibility
from mi.core.instrument.protocol_param_dict import FunctionParamDictVal
from mi.core.instrument.data_particle import DataParticle
from mi.core.instrument.data_particle import DataParticleKey
from mi.core.instrument.data_particle import CommonDataParticleType
from mi.core.instrument.chunker import StringChunker

# Globals
raw_stream_received = False
parsed_stream_received = False

# Program Constants.
NEWLINE = '\r\n'
NSECONDS_1904_TO_1970 = 2082844800
TIMEOUT = 10        # Default Timeout.

# This will decode n+1 chars for {n}
# DEVICE_STATUS_REGEX = r'[:](\w[0-9A-Fa-f]{7})(\w[0-9A-Fa-f]{3})(\w[0-9A-Fa-f])+.*?\r\n'
DEVICE_STATUS_REGEX = r'[:](\w[0-9A-Fa-f]{7})(\w[0-9A-Fa-f]{3})(\w[0-9A-Fa-f])(\w[0-9A-Fa-f])'
DEVICE_STATUS_REGEX_MATCHER = re.compile(DEVICE_STATUS_REGEX)

# RECORD_TYPE4_REGEX = r'[*](\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{3})(\w[0-9A-Fa-f]{7})+.*?\r\n'
RECORD_TYPE4_REGEX = r'[*](\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{3})(\w[0-9A-Fa-f]{7})+.*?\r\n'
RECORD_TYPE4_REGEX_MATCHER = re.compile(RECORD_TYPE4_REGEX)

# CJC: Not sure why we need a NL in testing but not in real life ?
CONFIG_REGEX_NL = r'[C](\w[0-9A-Fa-f]{6})(\w[0-9A-Fa-f]{7})(\w[0-9A-Fa-f]{7})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{25})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{3})(\w[0-9A-Fa-f]{1}).*?\r\n'
CONFIG_REGEX    = r'[C](\w[0-9A-Fa-f]{6})(\w[0-9A-Fa-f]{7})(\w[0-9A-Fa-f]{7})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{25})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{3})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f])'

CONFIG_REGEX_NL_MATCHER = re.compile(CONFIG_REGEX_NL)
CONFIG_REGEX_MATCHER = re.compile(CONFIG_REGEX)

ERROR_REGEX = r'\?\w[0-9A-Fa-f]{1}'
ERROR_REGEX_MATCHER = re.compile(ERROR_REGEX)

IMMEDIATE_STATUS_REGEX = r'(\w[0-9A-Fa-f]{1})(w[0-9A-Fa-f]{1})+.*?\r\n'
IMMEDIATE_STATUS_REGEX_MATCHER = re.compile(IMMEDIATE_STATUS_REGEX)

# Record information received from instrument may be data or control.
# Record types are Control or Data.
RECORD_DATA_PH    = 0xA
RECORD_DATA_SAMI_CO2 = 0x4
RECORD_DATA_BLANK = 0x5

RECORD_CTRL_LAUNCH = 0x80  # Launch - The program started executing, possibly waiting for measurement
RECORD_CTRL_START  = 0x81  # Start - The measurement sequence has started.
RECORD_CTRL_SHUTDOWN = 0x83 # Good Shutdown.
RECORD_CTRL_RTS_ENABLE = 0x85  # RTS Handshake is on.

###
#    Driver Constant Definitions
###

class ScheduledJob(BaseEnum):
    ACQUIRE_STATUS = 'acquire_status'
    CLOCK_SYNC = 'clock_sync'
    
class DataParticleType(BaseEnum):
    RAW = CommonDataParticleType.RAW
    DEVICE_STATUS_PARSED = 'device_status_parsed'
    IMMEDIATE_STATUS_PARSED = 'immediate_status_parsed'
    CONFIG_PARSED = 'config_parsed'
    RECORD_PARSED = 'record_parsed'

class InstrumentCmds(BaseEnum):
    """
    Device specific commands
    Represents the commands the driver implements and the string that must be sent to the instrument to
    execute the command.
    """
    SET_CONFIGURATION = 'L5A'
    GET_CONFIGURATION = 'L'
    IMMEDIATE_STATUS = 'I'
    QUIT_SESSION = 'Q'
    TAKE_SAMPLE = 'R'
    DEVICE_STATUS = 'S'
    AUTO_STATUS_ON = 'F'           # Automatic Status Update (Ping) at 1Hz.
    AUTO_STATUS_OFF = 'F5A'        # Turn Off 1Hz status updates.

class ProtocolState(BaseEnum):
    """
    Instrument protocol states
    """
    UNKNOWN = DriverProtocolState.UNKNOWN
    COMMAND = DriverProtocolState.COMMAND
    AUTOSAMPLE = DriverProtocolState.AUTOSAMPLE

class ProtocolEvent(BaseEnum):
    """
    Protocol events
    Extends protocol events to the set defined in the base class.
    """
    ENTER = DriverEvent.ENTER
    EXIT = DriverEvent.EXIT
    GET = DriverEvent.GET
    SET = DriverEvent.SET
    DISCOVER = DriverEvent.DISCOVER

    ### Common driver commands, should these be promoted?  What if the command isn't supported?
    START_AUTOSAMPLE = DriverEvent.START_AUTOSAMPLE
    STOP_AUTOSAMPLE  = DriverEvent.STOP_AUTOSAMPLE
    
    ACQUIRE_SAMPLE   = DriverEvent.ACQUIRE_SAMPLE
    ACQUIRE_STATUS   = DriverEvent.ACQUIRE_STATUS
    ACQUIRE_CONFIGURATION = "PROTOCOL_EVENT_ACQUIRE_CONFIGURATION"
    CLOCK_SYNC       = DriverEvent.CLOCK_SYNC
    
    # Different event because we don't want to expose this as a capability
    SCHEDULED_CLOCK_SYNC = 'PROTOCOL_EVENT_SCHEDULED_CLOCK_SYNC'

class Capability(BaseEnum):
    """
    Protocol events that should be exposed to users (subset of above).
    """
    START_AUTOSAMPLE = ProtocolEvent.START_AUTOSAMPLE
    STOP_AUTOSAMPLE  = ProtocolEvent.STOP_AUTOSAMPLE    
    ACQUIRE_SAMPLE   = ProtocolEvent.ACQUIRE_SAMPLE
    ACQUIRE_STATUS   = ProtocolEvent.ACQUIRE_STATUS
    ACQUIRE_CONFIGURATION = ProtocolEvent.ACQUIRE_CONFIGURATION
    CLOCK_SYNC       = ProtocolEvent.CLOCK_SYNC

class Parameter(DriverParameter):
    """
    Device specific parameters.
    """   
    # Configuration Parameter Information.
    # Note that the key names match the sami_cache names.
    PUMP_PULSE = 'PUMP_PULSE',
    PUMP_ON_TO_MEASURE = 'PUMP_ON_TO_MEASURE',
    NUM_SAMPLES_PER_MEASURE = 'NUM_SAMPLES_PER_MEASURE',
    NUM_CYCLES_BETWEEN_BLANKS = 'NUM_CYCLES_BETWEEN_BLANKS',
    NUM_REAGENT_CYCLES = 'NUM_REAGENT_CYCLES',
    NUM_BLANK_CYCLES = 'NUM_BLANK_CYCLES',
    FLUSH_PUMP_INTERVAL_SEC = 'FLUSH_PUMP_INTERVAL_SEC',
    STARTUP_BLANK_FLUSH_ENABLE = 'STARTUP_BLANK_FLUSH_ENABLE',
    PUMP_PULSE_POST_MEASURE_ENABLE = 'PUMP_PULSE_POST_MEASURE_ENABLE' # bool,
    NUM_EXTRA_PUMP_CYCLES = 'NUM_EXTRA_PUMP_CYCLES',
    DEVICE_DATE_TIME = 'DEVICE_DATE_TIME'   # Bill Note: DS_DEVICE_DATE_TIME
    
# Device prompts.
class Prompt(BaseEnum):
    """
    Device i/o prompts..
    """
    COMMAND = ""
    BAD_COMMAND = "?"
    
# Keep a cache dictionary for IOS exposed parameters that are actually assembled
# from a few different commands.
sami_cache_dict = {
   'PUMP_PULSE' : 16,
   'PUMP_ON_TO_MEASURE' : 32,
   'NUM_SAMPLES_PER_MEASURE' : 0xFF,
   'NUM_CYCLES_BETWEEN_BLANKS' : 168,
   'NUM_REAGENT_CYCLES' : 24,
   'NUM_BLANK_CYCLES' : 28,
   'FLUSH_PUMP_INTERVAL_SEC' : 0x01,
   'STARTUP_BLANK_FLUSH_ENABLE' : 0x1,
   'PUMP_PULSE_POST_MEASURE_ENABLE' : 0x1,
   'NUM_EXTRA_PUMP_CYCLES' : 56,
   'DEVICE_DATE_TIME' : "1234"}

# Common utilities.    
def calc_crc(s, num_points):
    cs = 0
    k = 0
    for i in range(num_points):
#        print("I= " + str(i) + " " + s[k:k+2] )
        value = int(s[k:k+2],16)  # 2-chars per data point
        cs = cs + value
        k = k + 2
    cs = cs & 0xFF        
    return(cs)

# Convert a time string into Epoc Seconds.
def convert_timestamp_to_sec(time_str):
    '''
    Convert a time string of the format dd-mm-yyyy hr:mn:sec to seconds since 1970.
    '''
    sec = 0;
    print("s = " + time_str)
    timestamp_regex = re.compile(r"(\d\d)-(\d\d)-(\d\d\d\d) (\d\d):(\d\d):(\d\d)")
    match = timestamp_regex.match(time_str)
    if( match ):
        dd = match.group(1)
        mm = match.group(2)
        yy = match.group(3)
        hr = match.group(4)
        mn = match.group(5)
        ss = match.group(6)
        
        # month_mapping: a mapping for 3 letter months to integers
        d1 = datetime.datetime(int(yy), int(mm), int(dd), int(hr), int(mn), int(ss))
        d1_tuple = d1.timetuple()
        secondsF = calendar.timegm(d1_tuple)
        sec = int(secondsF)
        print("d1 = " + str(d1) + " " + str(hex(sec)) )
    return(sec)

# Modify the time accessor to get Epoc.
def get_timestamp_delayed_sec():
    s = get_timestamp_delayed('%d-%m-%Y %H:%M:%S %Z')
    tsec = convert_timestamp_to_sec(s)
    return(tsec)

def get_timestamp_sec():
    s = get_timestamp('%d-%m-%Y %H:%M:%S %Z')
    tsec = convert_timestamp_to_sec(s)       
#    print("Today: ", time.asctime( time.gmtime(tsec) ))
    return(tsec)

###############################################################################
# Data Particles
################################################################################
class SamiRecordDataParticleKey(BaseEnum):
    UNIQUE_ID = 'unique_id'
    RECORD_LENGTH = 'record_length'
    RECORD_TYPE = 'record_type'
    RECORD_TIME = 'record_time'
    LIGHT_MEASUREMENT = 'light_measurement'
    VOLTAGE_BATTERY = 'voltage_battery'
    THERMISTER_RAW = 'thermister_raw'
    CHECKSUM = 'checksum'

class SamiRecordDataParticle(DataParticle):
    """
    This is for raw Sami PCO2W samples.
	Routines for parsing raw data into a data particle structure. Override
    the building of values, and the rest should come along for free.
    """
    # Record information received from instrument may be data or control.
    _data_particle_type = DataParticleType.RECORD_PARSED

    def _build_parsed_values(self):
        # Restore the first character we removed for recognition.
        regex1 = RECORD_TYPE4_REGEX_MATCHER
        log.debug("Got chunk of record!!!")
        
        match = regex1.match(self.raw_data)
        if not match:
            raise SampleException("No regex match of parsed Record Type4 data: [%s]" % self.raw_data)

        result = self._build_particle(match)
        log.debug("SamiRecordDataParticle = %s" %result)
        return(result)
    
    def _build_particle(self, match):
        unique_id = None
        record_length = None        
        record_time = None
        record_type = None
        pt_light_measurements = []
        voltage_battery = None
        thermister_raw = None
        checksum = None

        # Decode Time Stamp since Launch       
        txt = match.group(1)
        unique_id = int(txt,16)
        
        txt = match.group(2)
        record_length = int(txt,16)

        txt = match.group(3)    
        record_type = int(txt, 16)

        txt = match.group(4)    
        record_time = int(txt, 16)

        # Record Type #4,#5 have a length of 39 bytes, time & trailing checksum.
        if( (record_type == RECORD_DATA_PH) | \
            (record_type == RECORD_DATA_SAMI_CO2) | \
            (record_type == RECORD_DATA_BLANK) ):
            
            # Compute now many 8-bit data bytes we have.
            data_length = record_length
            data_length = data_length - 6  # Adjust for type, 4-bytes of time.
            data_length = data_length - 5  # Adjust for battery, thermister, cs
            num_measurements = data_length / 2  # 2-bytes per record.
        
            # Start extracting measurements from this string position
            idx = 15
            for i in range(num_measurements):
                txt = self.raw_data[idx:idx+4]
                val = int(txt, 16)
                pt_light_measurements.append(val)
                idx = idx + 4;            
                
            txt = self.raw_data[idx:idx+3]
            voltage_battery = int(txt, 16)
            idx = idx + 4
            
            txt = self.raw_data[idx:idx+3]
            thermister_raw = int(txt, 16) 
            idx = idx + 4
    
            txt = self.raw_data[idx:idx+2]
            checksum = int(txt, 16)
            # Compute the checksum now that we have the record length.
            # Skip over the ID character and the 1st byte (+3)
            # Compute the checksum for the entire record & compare with data.
            num_bytes = (record_length - 1)
            num_char = 2 * num_bytes
            cs = calc_crc( self.raw_data[3:3+num_char], num_bytes)
            log.debug("Record Checksup = " + str(hex(checksum)) + " versus " + str(hex(cs)))
            
        result = [{DataParticleKey.VALUE_ID: SamiRecordDataParticleKey.UNIQUE_ID,
                   DataParticleKey.VALUE: unique_id},
                  {DataParticleKey.VALUE_ID: SamiRecordDataParticleKey.RECORD_LENGTH,
                   DataParticleKey.VALUE: record_length},                  
                  {DataParticleKey.VALUE_ID: SamiRecordDataParticleKey.RECORD_TYPE,
                   DataParticleKey.VALUE: record_type},
                  {DataParticleKey.VALUE_ID: SamiRecordDataParticleKey.RECORD_TIME,
                   DataParticleKey.VALUE: record_time},
                  {DataParticleKey.VALUE_ID: SamiRecordDataParticleKey.VOLTAGE_BATTERY,
                   DataParticleKey.VALUE: voltage_battery},
                  {DataParticleKey.VALUE_ID: SamiRecordDataParticleKey.THERMISTER_RAW,
                   DataParticleKey.VALUE: thermister_raw},
                  {DataParticleKey.VALUE_ID: SamiRecordDataParticleKey.CHECKSUM,
                   DataParticleKey.VALUE: checksum},
                  {DataParticleKey.VALUE_ID: SamiRecordDataParticleKey.LIGHT_MEASUREMENT,
                   DataParticleKey.VALUE: pt_light_measurements}]
        
        return result
    
class SamiConfigDataParticleKey(BaseEnum):
    PROGRAM_DATE_TIME = 'program_date_time'
    START_TIME_OFFSET = 'start_offset'
    RECORDING_TIME = 'recording_time'
	# Mode Bits.
    PMI_SAMPLE_SCHEDULE = 'pmi_sample_schedule'
    SAMI_SAMPLE_SCHEDULE = 'sami_sample_schedule'
    SLOT1_FOLLOWS_SAMI_SCHEDULE = 'slot1_follows_sami_sample'
    SLOT1_INDEPENDENT_SCHEDULE  = 'slot1_independent_schedule'
    SLOT2_FOLLOWS_SAMI_SCHEDULE = 'slot2_follows_sami_sample'
    SLOT2_INDEPENDENT_SCHEDULE  = 'slot2_independent_schedule'
    SLOT3_FOLLOWS_SAMI_SCHEDULE = 'slot3_follows_sami_sample'
    SLOT3_INDEPENDENT_SCHEDULE  = 'slot3_independent_schedule'
	
    # Timer,Device,Pointer Triples
    TIMER_INTERVAL_SAMI = 'timer_interval_sami'
    DRIVER_ID_SAMI = 'driver_id_sami'
    PARAM_PTR_SAMI = 'param_ptr_sami'
    TIMER_INTERVAL_1 = 'timer_interval_1'
    DRIVER_ID_1 = 'driver_id_1'
    PARAM_PTR_1 = 'param_ptr_1'
    TIMER_INTERVAL_2 = 'timer_interval_2'
    DRIVER_ID_2 = 'driver_id_2'
    PARAM_PTR_2 = 'param_ptr_2'
    TIMER_INTERVAL_3 = 'timer_interval_3'
    DRIVER_ID_3 = 'driver_id_3'
    PARAM_PTR_3 = 'param_ptr_3'
    TIMER_INTERVAL_PRESTART = 'timer_interval_prestart'
    DRIVER_ID_PRESTART = 'driver_id_prestart'
    PARAM_PTR_PRESTART = 'param_ptr_prestart'
    
    # Global Configuration Settings Register for PCO2    
    USE_BAUD_RATE_57600 = "use_baud_rate_57600"
    SEND_RECORD_TYPE_EARLY = "send_record_type_early"
    SEND_LIVE_RECORDS = "send_live_records"

	# CO2 Settings
    PMI_SAMPLE_SCHEDULE = "pmi_sample_schedule"    
    SAMI_SAMPLE_SCHEDULE = "sami_sample_schedule"
    SLOT1_FOLLOWS_SAMI_SAMPLE  = "slot1_follows_sami_sample"
    SLOT1_INDEPENDENT_SCHEDULE = "slot1_independent_schedule"
    SLOT2_FOLLOWS_SAMI_SAMPLE  = "slot2_follows_sami_sample"
    SLOT2_INDEPENDENT_SCHEDULE = "slot2_independent_schedule"
    SLOT3_FOLLOWS_SAMI_SAMPLE  = "slot3_follows_sami_sample"
    SLOT3_INDEPENDENT_SCHEDULE = "slot3_independent_schedule"

    # PCO2 Pump Driver
    PUMP_PULSE = "pump_pulse"
    PUMP_ON_TO_MEAURSURE = "pump_on_to_measure"
    SAMPLES_PER_MEASURE = "samples_per_measure"
    CYCLES_BETWEEN_BLANKS = "cycles_between_blanks"
    NUM_REAGENT_CYCLES = "num_reagent_cycles"
    NUM_BLANK_CYCLES = "num_blank_cycles"
    FLUSH_PUMP_INTERVAL = "flush_pump_interval"
    BLANK_FLUSH_ON_START_ENABLE = "blank_flush_on_start_enable"
    PUMP_PULSE_POST_MEASURE = "pump_pulse_post_measure"
    CYCLE_DATA = "cycle_data"
    CHECKSUM = "checksum"
    
    # Not currently decoded
    SERIAL_SETTINGS = 'serial_settings'
        
class SamiConfigDataParticle(DataParticle):
    """
    Routines for parsing raw data into a data particle structure. Override
    the building of values, and the rest should come along for free.
    """
    _data_particle_type = DataParticleType.CONFIG_PARSED
    _config_crc = None  # Last downloaded configuration CRC value.

    def _build_parsed_values(self):
        log.debug(">>>>>>>>>>>>>>>>>>>> SamiConfigDataParticle Build Parsed Config Values ")
        # Restore the first character we removed for recognition.
        # TODO: Improve logic to not rely on 1st character of "C"

		# Mode Data Bit Definitions.
        MODE_PMI_SAMPLE_SCHEDULE = 0x01           # Prestart Schedule Enabled.
        MODE_SAMI_SAMPLE_SCHEDULE = 0x02          # Sami Schedule Enabled
        MODE_SLOT1_FOLLOWS_SAMI_SAMPLE  = 0x04    # External Device-1
        MODE_SLOT1_INDEPENDENT_SCHEDULE = 0x08
        MODE_SLOT2_FOLLOWS_SAMI_SAMPLE  = 0x10    # External Device-2
        MODE_SLOT2_INDEPENDENT_SCHEDULE = 0x20    
        MODE_SLOT3_FOLLOWS_SAMI_SAMPLE  = 0x40     # External Device-3
        MODE_SLOT3_INDEPENDENT_SCHEDULE = 0x80
        
		# Global Configuration Data Bits Definitions.  
        CFG_GLOBAL_BAUD_RATE_57600 = 0x1
        CFG_GLOBAL_SEND_RECORD_TYPE_EARLY = 0x2
        CFG_GLOBAL_SEND_LIVE_RECORDS = 0x4
        
        # Restore the first character that was used as an indentifier.
        # CJC: This id is not very unique!
        raw_data = self.raw_data
        regex1 = CONFIG_REGEX_MATCHER

        match = regex1.match(raw_data)
        if not match:
            raise SampleException("No regex match of parsed config data: [%s]" % raw_data)

        program_date_time = None
        start_time_offset = None
        recording_time = None

		# Mode Bits
        pmi_sample_schedule = None
        sami_sample_schedule = None
        slot1_follows_sami_sample  = None
        slot1_independent_schedule = None
        slot2_follows_sami_sample  = None
        slot2_independent_schedule = None
        slot3_follows_sami_sample  = None
        slot3_independent_schedule = None
		
        timer_interval_list = []
        driver_id_list = []
        param_ptr_list = []
                
		# Global Configuration Register
        use_baud_rate_57600 = None  # 57600 / 9600
        send_record_type_early = None
        send_live_records = None

		# CO2 Settings.
        pump_pulse = None
        pump_on_to_measure = None
        samples_per_measure = None
        cycles_between_blanks = None
        num_reagent_cycles = None    
        num_blank_cycles = None
        flush_pump_interval = None
        bit_switch = None
        blank_flush_on_start_enable = None
        pump_pulse_post_measure = None
        cycle_data = None
        
        # Not used and hard-coded right now.
        serial_settings = None

        # Decode Time Stamp since Launch       
        txt = match.group(1)
        txt = "C" + txt   # Add back in Match character.
        try:
            program_date_time = int(txt,16)
        except Exception, e:
            raise SampleException("ValueError decoding Config DriverID %d: [%s] [%s]" % (i,txt,str(e)))

        txt = match.group(2)
        start_time_offset = int(txt,16)
 
        txt = match.group(3)
        recording_time = int(txt,16)

        self.contents[SamiConfigDataParticleKey.PROGRAM_DATE_TIME] = program_date_time
        self.contents[SamiConfigDataParticleKey.START_TIME_OFFSET] = start_time_offset
        self.contents[SamiConfigDataParticleKey.RECORDING_TIME] = recording_time  # Time from start to stop.
   
        # Decode the Mode Bits.
        txt = match.group(4)
        mode = int(txt,16);          
        pmi_sample_schedule  = bool(mode & MODE_PMI_SAMPLE_SCHEDULE)
        sami_sample_schedule = bool(mode & MODE_SAMI_SAMPLE_SCHEDULE)
        slot1_follows_sami_sample  = bool(mode & MODE_SLOT1_FOLLOWS_SAMI_SAMPLE)
        slot1_independent_schedule = bool(mode & MODE_SLOT1_INDEPENDENT_SCHEDULE)
        slot2_follows_sami_sample  = bool(mode & MODE_SLOT2_FOLLOWS_SAMI_SAMPLE)
        slot2_independent_schedule = bool(mode & MODE_SLOT2_INDEPENDENT_SCHEDULE)
        slot3_follows_sami_sample  = bool(mode & MODE_SLOT3_FOLLOWS_SAMI_SAMPLE)
        slot3_independent_schedule = bool(mode & MODE_SLOT3_INDEPENDENT_SCHEDULE)

        # Update Data Dictionary.
        self.contents[SamiConfigDataParticleKey.PMI_SAMPLE_SCHEDULE] = pmi_sample_schedule
        self.contents[SamiConfigDataParticleKey.SAMI_SAMPLE_SCHEDULE] = sami_sample_schedule
        self.contents[SamiConfigDataParticleKey.SLOT1_FOLLOWS_SAMI_SCHEDULE] = slot1_follows_sami_sample
        self.contents[SamiConfigDataParticleKey.SLOT1_INDEPENDENT_SCHEDULE]  = slot1_independent_schedule
        self.contents[SamiConfigDataParticleKey.SLOT2_FOLLOWS_SAMI_SCHEDULE] = slot2_follows_sami_sample
        self.contents[SamiConfigDataParticleKey.SLOT2_INDEPENDENT_SCHEDULE]  = slot2_independent_schedule
        self.contents[SamiConfigDataParticleKey.SLOT3_FOLLOWS_SAMI_SCHEDULE] = slot3_follows_sami_sample
        self.contents[SamiConfigDataParticleKey.SLOT3_INDEPENDENT_SCHEDULE]  = slot3_independent_schedule

        # Loop through the 5 groups of device information.
        timer_interval = None
        driver_id = None
        param_ptr = None
        
        idx = 5
        device_group = []
        for i in range(5):
            #
            # Decode Timer
            txt = match.group(idx)
            try:
                timer_interval = int(txt,16)
            except Exception, e:
                raise SampleException("ValueError decoding Config Timer %d: [%s] [%s]" % (i,txt,str(e)))
				
            timer_interval_list.append( timer_interval )
            log.debug(" timer_interval = " + txt)
            #
            # Decode Driver ID
            txt = match.group(idx+1)
            try:
                driver_id = int(txt,16)
            except Exception, e:
                raise SampleException("ValueError decoding Config DriverID %d: [%s] [%s]" % (i,txt,str(e)))
				
            driver_id_list.append( driver_id )
            log.debug(" driver_id = " + txt)
            
            #
            # Decode Parameter Pointer
            txt = match.group(idx+2)
            try:
				param_ptr = int(txt,16)
            except Exception, e:
				raise SampleException("ValueError decoding Config ParamPtr %d: [%s] [%s]" % (i,txt,str(e)))
            param_ptr_list.append( param_ptr )
            log.debug(" param_ptr = " + txt)
            idx = idx + 3
            
            # Timer,Device,Pointer Triples
            if( i == 0):
                self.contents[SamiConfigDataParticleKey.TIMER_INTERVAL_SAMI] = timer_interval;
                self.contents[SamiConfigDataParticleKey.DRIVER_ID_SAMI] = driver_id;
                self.contents[SamiConfigDataParticleKey.PARAM_PTR_SAMI] = param_ptr;
        # end for
                
        """
        TIMER_INTERVAL_1 = 'timer_interval_1'
        DRIVER_ID_1 = 'driver_id_1'
        PARAM_PTR_1 = 'param_ptr_1'
        TIMER_INTERVAL_2 = 'timer_interval_2'
        DRIVER_ID_2 = 'driver_id_2'
        PARAM_PTR_2 = 'param_ptr_2'
        TIMER_INTERVAL_3 = 'timer_interval_3'
        DRIVER_ID_3 = 'driver_id_3'
        PARAM_PTR_3 = 'param_ptr_3'
        TIMER_INTERVAL_PRESTART = 'timer_interval_prestart'
        DRIVER_ID_PRESTART = 'driver_id_prestart'
        PARAM_PTR_PRESTART = 'param_ptr_prestart'
        """
    
        # The next byte is the Global Configuration Switches.
        txt = match.group(idx)
        idx = idx + 1
        cfg_reg = int(txt,16)
        use_baud_rate_57600    = bool(cfg_reg & CFG_GLOBAL_BAUD_RATE_57600)
        send_record_type_early = bool(cfg_reg & CFG_GLOBAL_SEND_RECORD_TYPE_EARLY)
        send_live_records      = bool(cfg_reg & CFG_GLOBAL_SEND_LIVE_RECORDS)
        
        self.contents[SamiConfigDataParticleKey.USE_BAUD_RATE_57600]    = use_baud_rate_57600
        self.contents[SamiConfigDataParticleKey.SEND_RECORD_TYPE_EARLY] = send_record_type_early
        self.contents[SamiConfigDataParticleKey.SEND_LIVE_RECORDS]      = send_live_records

        # Decode the PCO2 Configruation Parameters
        txt = match.group(idx)
        idx = idx + 1
        pump_pulse = int(txt,16)

        txt = match.group(idx)
        idx = idx + 1
        pump_on_to_measure = int(txt,16)

        txt = match.group(idx)
        idx = idx + 1
        samples_per_measure = int(txt,16)

        txt = match.group(idx)
        idx = idx + 1
        cycles_between_blanks = int(txt,16)

        txt = match.group(idx)
        idx = idx + 1
        num_reagent_cycles = int(txt,16)
		
        txt = match.group(idx)
        idx = idx + 1
        num_blank_cycles = int(txt,16)

        txt = match.group(idx)
        idx = idx + 1
        flush_pump_interval = int(txt,16)

        txt = match.group(idx)
        idx = idx + 1
        bit_switch = int(txt,16)
        blank_flush_on_start_enable = (bool(bit_switch & 0x1) == False)  # Logic Inverted.
        pump_pulse_post_measure = bool(bit_switch & 0x2)

        txt = match.group(idx)
        idx = idx + 1
        cycle_data = int(txt,16)
    
        # PCO2 Pump Driver
        self.contents[SamiConfigDataParticleKey.PUMP_PULSE] = pump_pulse
        self.contents[SamiConfigDataParticleKey.PUMP_ON_TO_MEAURSURE] = pump_on_to_measure
        self.contents[SamiConfigDataParticleKey.SAMPLES_PER_MEASURE] = samples_per_measure
        self.contents[SamiConfigDataParticleKey.CYCLES_BETWEEN_BLANKS] = cycles_between_blanks
        self.contents[SamiConfigDataParticleKey.NUM_REAGENT_CYCLES] = num_reagent_cycles
        self.contents[SamiConfigDataParticleKey.NUM_BLANK_CYCLES] = num_blank_cycles
        self.contents[SamiConfigDataParticleKey.FLUSH_PUMP_INTERVAL] = flush_pump_interval
        self.contents[SamiConfigDataParticleKey.BLANK_FLUSH_ON_START_ENABLE] = blank_flush_on_start_enable
        self.contents[SamiConfigDataParticleKey.PUMP_PULSE_POST_MEASURE] = pump_pulse_post_measure
        self.contents[SamiConfigDataParticleKey.CYCLE_DATA] = cycle_data
#       self.contents[SamiConfigDataParticleKey.CHECKSUM] = "checksum"

        '''
        log.debug("pump_pulse = " + str(hex(pump_pulse)))
        log.debug("pump_on_to_measure = " + str(hex(pump_on_to_measure)))
        log.debug("samples_per_measure = " + str(hex(samples_per_measure)))
        log.debug("cycles_between_blanks = " + str(hex(cycles_between_blanks)))
        log.debug("num_reagent_cycles = " + str(hex(num_reagent_cycles)))
        log.debug("num_blank_cycles = " + str(hex(num_blank_cycles)))
        log.debug("flush_pump_interval = " + str(hex(flush_pump_interval)))
        log.debug("bit_switch = " + str(hex(bit_switch)))                   
        log.debug("cycle_data = " + str(hex(cycle_data)))
        '''                      

        # Globalize these parameters.
        sami_cache_dict[Parameter.PUMP_PULSE] = pump_pulse;
        sami_cache_dict[Parameter.PUMP_ON_TO_MEASURE] = pump_on_to_measure;
        sami_cache_dict[Parameter.NUM_SAMPLES_PER_MEASURE] = samples_per_measure;
        sami_cache_dict[Parameter.NUM_CYCLES_BETWEEN_BLANKS] = cycles_between_blanks;
        sami_cache_dict[Parameter.NUM_REAGENT_CYCLES] = num_reagent_cycles;
        sami_cache_dict[Parameter.NUM_BLANK_CYCLES] = num_blank_cycles;
        sami_cache_dict[Parameter.FLUSH_PUMP_INTERVAL_SEC] = flush_pump_interval;
        sami_cache_dict[Parameter.STARTUP_BLANK_FLUSH_ENABLE] = blank_flush_on_start_enable
        sami_cache_dict[Parameter.PUMP_PULSE_POST_MEASURE_ENABLE] = pump_pulse_post_measure;
        sami_cache_dict[Parameter.NUM_EXTRA_PUMP_CYCLES] = cycle_data;
        
        # Serial settings is next match.        
        txt = match.group(idx)
        idx = idx + 1
        serial_settings = txt
        
        """
        # These parameters are not currently used.
        log.debug("duration1: " + m0.group(idx) )
        idx = idx + 1    
        log.debug("duration2: " + m0.group(idx) )
        idx = idx + 1    
        log.debug("Meaningless parameter: " + m0.group(idx) )
        idx = idx + 1
        """
        # Return the results as a list.
        result = [{DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.PROGRAM_DATE_TIME,
                   DataParticleKey.VALUE: program_date_time},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.START_TIME_OFFSET,
                   DataParticleKey.VALUE: start_time_offset},                  
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.RECORDING_TIME,
                   DataParticleKey.VALUE: recording_time},				   
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.PMI_SAMPLE_SCHEDULE,
                   DataParticleKey.VALUE: pmi_sample_schedule},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.SAMI_SAMPLE_SCHEDULE,
                   DataParticleKey.VALUE: sami_sample_schedule},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.SLOT1_FOLLOWS_SAMI_SCHEDULE,
                   DataParticleKey.VALUE: slot1_follows_sami_sample},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.SLOT1_INDEPENDENT_SCHEDULE,
                   DataParticleKey.VALUE: slot1_independent_schedule},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.SLOT2_FOLLOWS_SAMI_SCHEDULE,
                   DataParticleKey.VALUE: slot2_follows_sami_sample},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.SLOT2_INDEPENDENT_SCHEDULE,
                   DataParticleKey.VALUE: slot2_independent_schedule},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.SLOT3_FOLLOWS_SAMI_SCHEDULE,
                   DataParticleKey.VALUE: slot3_follows_sami_sample},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.SLOT3_INDEPENDENT_SCHEDULE,
                   DataParticleKey.VALUE: slot3_independent_schedule},
                  
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.TIMER_INTERVAL_SAMI,
                   DataParticleKey.VALUE: timer_interval_list[0]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.DRIVER_ID_SAMI,
                   DataParticleKey.VALUE: driver_id_list[0]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.PARAM_PTR_SAMI,
                   DataParticleKey.VALUE: param_ptr_list[0]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.TIMER_INTERVAL_1,
                   DataParticleKey.VALUE: timer_interval_list[1]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.DRIVER_ID_1,
                   DataParticleKey.VALUE: driver_id_list[1]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.PARAM_PTR_1,
                   DataParticleKey.VALUE: param_ptr_list[1]},     
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.TIMER_INTERVAL_2,
                   DataParticleKey.VALUE: timer_interval_list[2]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.DRIVER_ID_2,
                   DataParticleKey.VALUE: driver_id_list[2]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.PARAM_PTR_2,
                   DataParticleKey.VALUE: param_ptr_list[2]},              
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.TIMER_INTERVAL_3,
                   DataParticleKey.VALUE: timer_interval_list[3]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.DRIVER_ID_3,
                   DataParticleKey.VALUE: driver_id_list[3]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.PARAM_PTR_3,
                   DataParticleKey.VALUE: param_ptr_list[3]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.TIMER_INTERVAL_PRESTART,
                   DataParticleKey.VALUE: timer_interval_list[4]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.DRIVER_ID_PRESTART,
                   DataParticleKey.VALUE: driver_id_list[4]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.PARAM_PTR_PRESTART,
                   DataParticleKey.VALUE: param_ptr_list[4]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.USE_BAUD_RATE_57600,
                   DataParticleKey.VALUE: use_baud_rate_57600},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.SEND_RECORD_TYPE_EARLY,
                   DataParticleKey.VALUE: send_record_type_early},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.SEND_LIVE_RECORDS,
                   DataParticleKey.VALUE: send_live_records},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.PUMP_PULSE,
                   DataParticleKey.VALUE: pump_pulse},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.PUMP_ON_TO_MEAURSURE,
                  DataParticleKey.VALUE: pump_on_to_measure},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.SAMPLES_PER_MEASURE,
                   DataParticleKey.VALUE: samples_per_measure},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CYCLES_BETWEEN_BLANKS,
                  DataParticleKey.VALUE: cycles_between_blanks},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.NUM_REAGENT_CYCLES,
                  DataParticleKey.VALUE: num_reagent_cycles},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.NUM_BLANK_CYCLES,
                   DataParticleKey.VALUE: num_blank_cycles},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.FLUSH_PUMP_INTERVAL,
                  DataParticleKey.VALUE: flush_pump_interval},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.BLANK_FLUSH_ON_START_ENABLE,
                   DataParticleKey.VALUE: blank_flush_on_start_enable},
                 {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.PUMP_PULSE_POST_MEASURE,
                   DataParticleKey.VALUE: pump_pulse_post_measure},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CYCLE_DATA,
                   DataParticleKey.VALUE: cycle_data},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.SERIAL_SETTINGS,
                  DataParticleKey.VALUE: serial_settings}]
        return result

class SamiImmediateStatusDataParticleKey(BaseEnum):
    PUMP_ON = "pump_on",
    VALVE_ON = "valve_on",
    EXTERNAL_POWER_ON = "external_power_on",
    DEBUG_LED_ON = "debug_led_on",
    DEBUG_ECHO_ON = "debug_echo_on"
    
class SamiImmediateStatusDataParticle(DataParticle):
    """
    Routines for parsing raw data into a data particle structure. Override
    the building of values, and the rest should come along for free.
    """
    _data_particle_type = DataParticleType.IMMEDIATE_STATUS_PARSED

    def _build_parsed_values(self):
        """
        Take something in the autosample format and split it into
        values with appropriate tags
        @throws SampleException If there is a problem with sample creation
        """
        regex1 = IMMEDIATE_STATUS_REGEX_MATCHER

        match = regex1.match(self.raw_data)
        if not match:
            raise SampleException("No regex match of parsed status data: [%s]" % self.raw_data)
        
        pump_on = None
        valve_on = None
        external_power_on = None
        debug_led_on = None
        debug_echo_on = None
        
        txt = match.group(1)
        status_word = int(txt,16)
        log.debug("status_word = " + str(hex(status_word)))
        
        pump_on  = bool(status_word & 0x01)
        valve_on = bool(status_word & 0x02)
        external_power_on = bool(status_word & 0x04)
        debug_led_on  = bool(status_word & 0x10)     
        debug_echo_on = bool(status_word & 0x20)
        
        # Jump in and update the parameter dictionary here!        
        param = Parameter.PUMP_ON_TO_MEASURE;
        param['value'] = pump_on;
        
        result = [{DataParticleKey.VALUE_ID: SamiImmediateStatusDataParticleKey.PUMP_ON,
                   DataParticleKey.VALUE: pump_on},
                  {DataParticleKey.VALUE_ID: SamiImmediateStatusDataParticleKey.VALVE_ON,
                   DataParticleKey.VALUE: valve_on},
                  {DataParticleKey.VALUE_ID: SamiImmediateStatusDataParticleKey.EXTERNAL_POWER_ON,
                   DataParticleKey.VALUE: external_power_on},
                  {DataParticleKey.VALUE_ID: SamiImmediateStatusDataParticleKey.DEBUG_LED_ON,
                   DataParticleKey.VALUE: debug_led_on},
                  {DataParticleKey.VALUE_ID: SamiImmediateStatusDataParticleKey.DEBUG_ECHO_ON,
                   DataParticleKey.VALUE: debug_echo_on} ]
       
        return result
        
class SamiStatusDataParticleKey(BaseEnum):
    TIME_OFFSET = "time_offset"
    CLOCK_ACTIVE = "clock_active"
    RECORDING_ACTIVE = "recording_active"
    RECORD_END_ON_TIME = "record_end_on_time"
    RECORD_MEMORY_FULL = "record_memory_full"
    RECORD_END_ON_ERROR = "record_end_on_error"
    DATA_DOWNLOAD_OK = "data_download_ok"
    FLASH_MEMORY_OPEN = "flash_memory_open"
    BATTERY_FATAL_ERROR = "battery_fatal_error"
    BATTERY_LOW_MEASUREMENT = "battery_low_measurement"
    BATTERY_LOW_BANK = "battery_low_bank"
    BATTERY_LOW_EXTERNAL = "battery_low_external"
    EXTERNAL_DEVICE_FAULT = "external_device_fault"
    FLASH_ERASED = "flash_erased"
    POWER_ON_INVALID = "power_on_invalid"

class SamiStatusDataParticle(DataParticle):
    """
    Routines for parsing raw data into a data particle structure. Override
    the building of values, and the rest should come along for free.
    """
    _data_particle_type = DataParticleType.DEVICE_STATUS_PARSED

    def _build_parsed_values(self):
        """
        The Device Status information is instrument read-only data.
        @throws SampleException If there is a problem with sample creation
        """
        regex1 = DEVICE_STATUS_REGEX_MATCHER

        match = regex1.match(self.raw_data)
        if not match:
            raise SampleException("No regex match of parsed status data: [%s]" % self.raw_data)
    
        # initialize
        time_offset          = None
        clock_active         = None   
        recording_active     = None
        record_end_on_time   = None
        record_memory_full   = None
        record_end_on_error  = None
        record_data_download_ok = None
        record_flash_open    = None
        battery_fatal_error  = None
        battery_low_measurement = None
        battery_low_bank     = None
        battery_low_external = None
        external_device_fault = None     
        flash_erased     = None
        power_on_invalid = None

        try:
            # Decode Time Stamp since Launch
            txt = match.group(1)
            time_offset = int(txt,16)
            log.debug("time_offset = " + str(hex(time_offset)))
            
        except ValueError:
            raise SampleException("ValueError while decoding data: [%s]" %
                                  self.raw_data)

        try:
            # Decode Bit-fields.
            txt = match.group(2)
            status_word = int(txt,16)
            log.debug(" status word = " + str(hex(status_word)))
            
        except IndexError:
            #These are optional. Quietly ignore if they dont occur.
            pass

        else:
            # Decode the status word.
            clock_active         = bool(status_word & 0x001)      
            recording_active     = bool(status_word & 0x002)
            record_end_on_time   = bool(status_word & 0x004)
            record_memory_full   = bool(status_word & 0x008)
            record_end_on_error  = bool(status_word & 0x010)
            data_download_ok     = bool(status_word & 0x020)
            flash_memory_open    = bool(status_word & 0x040)
            battery_fatal_error  = bool(status_word & 0x080)
            battery_low_measurement = bool(status_word & 0x100)
            battery_low_bank     = bool(status_word & 0x200)
            battery_low_external = bool(status_word & 0x400)
            
            log.debug("clock_active " + str(clock_active))
            log.debug("recording_active " + str(recording_active))
            log.debug("record_end_on_time " + str(record_end_on_time))
            log.debug("record_memory_full " + str(record_memory_full))
            log.debug("record_end_on_error " + str(record_end_on_error))
            log.debug("data_download_ok " + str(data_download_ok))
            log.debug("flash_memory_open " + str(flash_memory_open))
            log.debug("battery_fatal_error " + str(battery_fatal_error))
            log.debug("battery_low_measurement " + str(battery_low_measurement))
            
            # Or bits together for External fault information (Bit-0 = Dev-1, Bit-1 = Dev-2)
            external_device_fault = 0x0
            if( bool(status_word & 0x0800) == True ):
                external_device_fault = external_device_fault | 0x1
            if( bool(status_word & 0x1000) == True ):
                external_device_fault = external_device_fault | 0x2
            if( bool(status_word & 0x2000) == True ):
                external_device_fault = external_device_fault | 0x4
        
            flash_erased     = bool(status_word & 0x4000)
            power_on_invalid = bool(status_word & 0x8000)
            
            result = [{DataParticleKey.VALUE_ID: SamiStatusDataParticleKey.TIME_OFFSET,
                       DataParticleKey.VALUE: time_offset},
                      {DataParticleKey.VALUE_ID: SamiStatusDataParticleKey.CLOCK_ACTIVE,
                       DataParticleKey.VALUE: clock_active},
                      {DataParticleKey.VALUE_ID: SamiStatusDataParticleKey.RECORDING_ACTIVE,
                       DataParticleKey.VALUE: recording_active},
                      {DataParticleKey.VALUE_ID: SamiStatusDataParticleKey.RECORD_END_ON_TIME,
                       DataParticleKey.VALUE: record_end_on_time},
                      {DataParticleKey.VALUE_ID: SamiStatusDataParticleKey.RECORD_MEMORY_FULL,
                       DataParticleKey.VALUE: record_memory_full},
                      {DataParticleKey.VALUE_ID: SamiStatusDataParticleKey.RECORD_END_ON_ERROR,
                       DataParticleKey.VALUE: record_end_on_error},
                      {DataParticleKey.VALUE_ID: SamiStatusDataParticleKey.DATA_DOWNLOAD_OK,
                       DataParticleKey.VALUE: data_download_ok},
                      {DataParticleKey.VALUE_ID: SamiStatusDataParticleKey.FLASH_MEMORY_OPEN,
                       DataParticleKey.VALUE: flash_memory_open},
                      {DataParticleKey.VALUE_ID: SamiStatusDataParticleKey.BATTERY_FATAL_ERROR,
                       DataParticleKey.VALUE: battery_fatal_error},
                      {DataParticleKey.VALUE_ID: SamiStatusDataParticleKey.BATTERY_LOW_MEASUREMENT,
                       DataParticleKey.VALUE: battery_low_measurement},
                      {DataParticleKey.VALUE_ID: SamiStatusDataParticleKey.BATTERY_LOW_BANK,
                       DataParticleKey.VALUE: battery_low_bank},
                      {DataParticleKey.VALUE_ID: SamiStatusDataParticleKey.BATTERY_LOW_EXTERNAL,
                       DataParticleKey.VALUE: battery_low_external},
                      {DataParticleKey.VALUE_ID: SamiStatusDataParticleKey.EXTERNAL_DEVICE_FAULT,
                       DataParticleKey.VALUE: external_device_fault},
                      {DataParticleKey.VALUE_ID: SamiStatusDataParticleKey.FLASH_ERASED,
                       DataParticleKey.VALUE: flash_erased},
                      {DataParticleKey.VALUE_ID: SamiStatusDataParticleKey.POWER_ON_INVALID,
                       DataParticleKey.VALUE: power_on_invalid} ]                
        return result

###############################################################################
# Driver
###############################################################################

class InstrumentDriver(SingleConnectionInstrumentDriver):
    """
    InstrumentDriver subclass
    Subclasses SingleConnectionInstrumentDriver with connection state
    machine.
    """
    def __init__(self, evt_callback):
        """
        Driver constructor.
        @param evt_callback Driver process event callback.
        """
        #Construct superclass.
        SingleConnectionInstrumentDriver.__init__(self, evt_callback)

    ########################################################################
    # Superclass overrides for resource query.
    ########################################################################

#    def get_resource_params(self):
#        """
#        Return list of device parameters available.
#        """
#        return Parameter.list()

    ########################################################################
    # Protocol builder.
    ########################################################################

    def _build_protocol(self):
        """
        Construct the driver protocol state machine.
        """
        self._protocol = Protocol(Prompt, NEWLINE, self._driver_event)


###########################################################################
# Protocol
###########################################################################

class Protocol(CommandResponseInstrumentProtocol):
    """
    Instrument protocol class
    Subclasses CommandResponseInstrumentProtocol
    """
    # Provide Cache value access
    global sami_cache_dict  # external
    
    # Create a configuration string when the values are built.
    sami_configuration_str = ""
    
    def __init__(self, prompts, newline, driver_event):
        """
        Protocol constructor.
        @param prompts A BaseEnum class containing instrument prompts.
        @param newline The newline.
        @param driver_event Driver process event callback.
        """
        # Construct protocol superclass.
        CommandResponseInstrumentProtocol.__init__(self, prompts, newline, driver_event)

        # Build protocol state machine.
        self._protocol_fsm = InstrumentFSM(ProtocolState, ProtocolEvent,
                            ProtocolEvent.ENTER, ProtocolEvent.EXIT)

        # Add event handlers for protocol state machine.
        self._protocol_fsm.add_handler(ProtocolState.UNKNOWN, ProtocolEvent.ENTER, self._handler_unknown_enter)
        self._protocol_fsm.add_handler(ProtocolState.UNKNOWN, ProtocolEvent.DISCOVER, self._handler_unknown_discover)

        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.ENTER, self._handler_command_enter)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.GET, self._handler_command_get)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.SET, self._handler_command_set)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.START_AUTOSAMPLE, self._handler_command_start_autosample)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.ACQUIRE_SAMPLE,   self._handler_command_acquire_sample)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.ACQUIRE_STATUS,   self._handler_command_acquire_status)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.ACQUIRE_CONFIGURATION,self._handler_command_acquire_configuration)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.CLOCK_SYNC,       self._handler_command_clock_sync)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.SCHEDULED_CLOCK_SYNC,self._handler_command_clock_sync)

        self._protocol_fsm.add_handler(ProtocolState.AUTOSAMPLE, ProtocolEvent.ENTER, self._handler_autosample_enter)
        self._protocol_fsm.add_handler(ProtocolState.AUTOSAMPLE, ProtocolEvent.ACQUIRE_STATUS,  self._handler_command_acquire_status)
        self._protocol_fsm.add_handler(ProtocolState.AUTOSAMPLE, ProtocolEvent.STOP_AUTOSAMPLE, self._handler_autosample_stop_autosample)
        self._protocol_fsm.add_handler(ProtocolState.AUTOSAMPLE, ProtocolEvent.SCHEDULED_CLOCK_SYNC,self._handler_command_clock_sync)

        # Construct the parameter dictionary containing device parameters,
        # current parameter values, and set formatting functions.
        self._build_param_dict()

        # Add build handlers for device commands.
        self._add_build_handler(InstrumentCmds.AUTO_STATUS_OFF,     self._build_simple_command)
        self._add_build_handler(InstrumentCmds.DEVICE_STATUS,       self._build_simple_command)
        self._add_build_handler(InstrumentCmds.IMMEDIATE_STATUS,    self._build_simple_command)
        self._add_build_handler(InstrumentCmds.TAKE_SAMPLE,         self._build_simple_command)
        self._add_build_handler(InstrumentCmds.GET_CONFIGURATION,   self._build_simple_command)
        self._add_build_handler(InstrumentCmds.SET_CONFIGURATION,   self._build_config_command)
        
        # Add response handlers for device commands.
        self._add_response_handler(InstrumentCmds.DEVICE_STATUS,     self._parse_S_response)
        self._add_response_handler(InstrumentCmds.IMMEDIATE_STATUS,  self._parse_I_response)
        self._add_response_handler(InstrumentCmds.TAKE_SAMPLE,       self._parse_R_response)
        self._add_response_handler(InstrumentCmds.GET_CONFIGURATION, self._parse_config_response)
        self._add_response_handler(InstrumentCmds.SET_CONFIGURATION, self._parse_config_response)

        # Add sample handlers.
        # State state machine in UNKNOWN state.
        self._protocol_fsm.start(ProtocolState.UNKNOWN)

        # commands sent sent to device to be filtered in responses for telnet DA
        self._sent_cmds = []

        self._chunker = StringChunker(Protocol.sieve_function)

        self._add_scheduler_event(ScheduledJob.ACQUIRE_STATUS, ProtocolEvent.ACQUIRE_STATUS)
        self._add_scheduler_event(ScheduledJob.CLOCK_SYNC, ProtocolEvent.SCHEDULED_CLOCK_SYNC)
        
    @staticmethod
    def sieve_function(raw_data):
        """
        The method that splits samples
        """
        sieve_matchers = [RECORD_TYPE4_REGEX_MATCHER,
                          DEVICE_STATUS_REGEX_MATCHER,
                          CONFIG_REGEX_MATCHER]

        return_list = []

        log.debug("CJC raw_data: %s" % raw_data )

        for matcher in sieve_matchers:
            for match in matcher.finditer(raw_data):
                log.debug("Match Found ****")
                return_list.append((match.start(), match.end()))

        return return_list

    ########################################################################
    # Private helpers.
    ########################################################################
    def _build_simple_command(self, cmd):
        """
        Build handler for basic SAMI commands.
        @param cmd the simple sbe37 command to format.
        @retval The command to be sent to the device.
        """
        return cmd + NEWLINE

    def _build_config_command(self, cmd, *args, **kwargs):
        log.debug("Testing _build_config_command")
        return cmd + NEWLINE
        return cmd_line
    
    def _build_param_dict(self):
        """
        Populate the parameter dictionary with parameters.
        For each parameter key, add match stirng, match lambda function,
        and value formatting function for set commands.
        """
        # Here we will index to the values in the "fixed string".
        # Pointer to the 1st SAMI Driver 4/5 Parameter String.
        param_index = 78  # TBD: Verify.
            
        # Add parameter handlers to parameter dict.
        self._param_dict.add(Parameter.PUMP_PULSE,
            r'^(.{%s})(.{2}).*' % str(param_index),   # Fixed offset.
            lambda match : self._string_to_int(match.group(2)),
            lambda x : self._int8_to_string(value=x,pos=param_index),
            default_value = 16)
        
#        self._param_dict.add_paramdictval( 
#            FunctionParamDictVal( Parameter.PUMP_PULSE,
#                                  self._decode_bit_0,
#                                  lambda x : str(x),
#                                  direct_access=True,
#                                  startup_param=True,
#                                  value=1,
#                                  visibility=ParameterDictVisibility.READ_WRITE)
#                                )
        
        self._param_dict.add(Parameter.PUMP_ON_TO_MEASURE,
            r'^(.{%s})(.{2}).*' % str(param_index+2),   # Fixed offset.
            lambda match : self._string_to_int(match.group(2)),
            lambda x : self._int8_to_string(value=x,pos=param_index+2),                          # Output, note needs to be 7
            default_value = 32)
        
        self._param_dict.add(Parameter.NUM_SAMPLES_PER_MEASURE,
            r'^(.{%s})(.{2}).*' % str(param_index+4),   # Fixed offset.
            lambda match : self._string_to_int(match.group(2)),
            lambda x : self._int8_to_string(value=x,pos=param_index+4),                          # Output, note needs to be 7
            default_value = 255)
        
        self._param_dict.add(Parameter.NUM_CYCLES_BETWEEN_BLANKS,
            r'^(.{%s})(.{2}).*' % str(param_index+6),   # Fixed offset.
            lambda match : self._string_to_int(match.group(2)),
            lambda x : self._int8_to_string(value=x,pos=param_index+6),                          # Output, note needs to be 7
            default_value = 168)
                   
        self._param_dict.add(Parameter.NUM_REAGENT_CYCLES,
            r'^(.{%s})(.{2}).*' % str(param_index+8),   # Fixed offset.
            lambda match : self._string_to_int(match.group(2)),
            lambda x : self._int8_to_string(value=x,pos=param_index+8),                          # Output, note needs to be 7
            default_value = 24)
                   
        self._param_dict.add(Parameter.NUM_BLANK_CYCLES,
            r'^(.{%s})(.{2}).*' % str(param_index+10),   # Fixed offset.
            lambda match : self._string_to_int(match.group(2)),
            lambda x : self._int8_to_string(value=x,pos=param_index+10),                          # Output, note needs to be 7
            default_value = 28)

        self._param_dict.add(Parameter.FLUSH_PUMP_INTERVAL_SEC,
            r'^(.{%s})(.{2}).*' % str(param_index+12),   # Fixed offset.
            lambda match : self._string_to_int(match.group(2)),
            lambda x : self._int8_to_string(value=x,pos=param_index+12),                          # Output, note needs to be 7
            default_value = 1)

        """
        self._param_dict.add(Parameter.STARTUP_BLANK_FLUSH_ENABLE,
            CONFIG_REGEX,
            lambda st : sami_cache_dict[Parameter.STARTUP_BLANK_FLUSH_ENABLE],
            self._int32_to_string,                          # Output, note needs to be 7
            value = sami_cache_dict[Parameter.STARTUP_BLANK_FLUSH_ENABLE],
            default_value = False)
            
        self._param_dict.add(Parameter.PUMP_PULSE_POST_MEASURE_ENABLE,
            CONFIG_REGEX,
            lambda st : sami_cache_dict[Parameter.PUMP_PULSE_POST_MEASURE_ENABLE],
            self._int32_to_string,                          # Output, note needs to be 7
            value = sami_cache_dict[Parameter.PUMP_PULSE_POST_MEASURE_ENABLE],
            default_value = False)
        """
                
        self._param_dict.add_paramdictval( 
            FunctionParamDictVal( Parameter.STARTUP_BLANK_FLUSH_ENABLE,
                                  self._decode_switch_bit_0,
                                  lambda x : str(x),
                                  direct_access=True,
                                  startup_param=False,
                                  value=True,
                                  visibility=ParameterDictVisibility.READ_WRITE )
                                         )
        
        self._param_dict.add_paramdictval(
            FunctionParamDictVal( Parameter.PUMP_PULSE_POST_MEASURE_ENABLE,
                                  self._decode_switch_bit_1,
                                  lambda x : str(x),
                                  direct_access=True,
                                  startup_param=False,
                                  value=False,
                                  visibility=ParameterDictVisibility.READ_WRITE )
                                         )
        
        self._param_dict.add(Parameter.NUM_EXTRA_PUMP_CYCLES,
            r'^(.{%s})(.{2}).*' % str(param_index+16),   # Fixed offset.
            lambda match : self._string_to_int(match.group(2)),
            lambda x : self._int8_to_string(value=x,pos=param_index+16),                          # Output, note needs to be 7
            default_value = 56)
        
        pd = self._param_dict.get_config()
        log.debug("&&&&&&&&&&&&& _build_param_dict: _param_dict: %s" % pd)
#        log.debug("^^^^^^^^^^^^^  at same time the adcpt_cache_dict is %s" % adcpt_cache_dict)
        
    def _got_chunk(self, chunk, timestamp):
        """
        The base class got_data has gotten a chunk from the chunker.  Pass it to extract_sample
        with the appropriate parcle objects and REGEXes.
        """
        if(self._extract_sample(SamiRecordDataParticle, RECORD_TYPE4_REGEX_MATCHER, chunk, timestamp)):
            log.debug("_got_chunk of Record Data = Passed good")
        elif(self._extract_sample(SamiStatusDataParticle, DEVICE_STATUS_REGEX_MATCHER, chunk, timestamp)):
            log.debug("_got_chunk of Status = Passed good")
        elif(self._extract_sample(SamiConfigDataParticle, CONFIG_REGEX_MATCHER, chunk, timestamp)):
            log.debug("_got_chunk of Config = Passed good")
        else:
            log.debug("_got_chunk = Failed")

    def _filter_capabilities(self, events):
        """
        Return a list of currently available capabilities.
        """
        events_out = [x for x in events if Capability.has(x)]
        return events_out
    
    def get_config(self, *args, **kwargs):
        """ Get the entire configuration for the instrument
        
        @param params The parameters and values to set
        @retval None if nothing was done, otherwise result of FSM event handle
        Should be a dict of parameters and values
        @throws InstrumentProtocolException On invalid parameter
        """
        pd = self._param_dict.get_config()
        log.debug("&&&&&&&&&&&&& _build_param_dict: _param_dict: %s" % pd)
#        log.debug("^^^^^^^^^^^^^  at same time the adcpt_cache_dict is %s" % adcpt_cache_dict)

        result = self._do_cmd_resp(InstrumentCmds.GET_CONFIGURATION, *args, **kwargs)
        if not result:
            log.debug("*** no result!")
        log.debug("********** HEre 2")

        return pd  # CJC This is wrong.
        
    ########################################################################
    # Unknown handlers.
    ########################################################################

    def _handler_unknown_enter(self, *args, **kwargs):
        """
        Enter unknown state.
        """
        # Tell driver superclass to send a state change event.
        # Superclass will query the state.
        log.debug("Testing _handler_unknown_enter")
       
        next_state = None
        result = None
                                
        # Initialize the Sami Configuration String for the first time.
        sami_configuration_str = ""
        for i in range(0,232):
            sami_configuration_str += "0"
            
        # Tell driver superclass to send a state change event.
        # Superclass will query the state.
        self._driver_event(DriverAsyncEvent.STATE_CHANGE)
        return(result, next_state)


    def _handler_unknown_discover(self, *args, **kwargs):
        """
        Discover current state; can be COMMAND or AUTOSAMPLE.
        @retval (next_state, result), (ProtocolState.COMMAND or
        State.AUTOSAMPLE, None) if successful.
        @throws InstrumentTimeoutException if the device cannot be woken.
        @throws InstrumentStateException if the device response does not correspond to
        an expected state.
        """
        log.debug("Testing _handler_unknown_discover")
        next_state = None
        next_agent_state = None
                   
        # This is where we will figure out what state we are in.
        self._sami_do_cmd_device_status()
        
        next_state = ProtocolState.COMMAND
        next_agent_state = ResourceAgentState.IDLE
                
        return ( next_state, next_agent_state )

    ########################################################################
    # Autosample handlers.
    ########################################################################
    def _handler_autosample_enter(self, *args, **kwargs):
        """
        Enter autosample state.
        """
		# We are now in AutoSample state when we get here.
        # Tell driver superclass to send a state change event.
        # Superclass will query the state.
        next_state = None
        next_agent_state = None
        return( next_state, next_agent_state)
		
    def _handler_autosample_stop_autosample(self, *args, **kwargs):
        """
        Stop autosample and switch back to command mode.
        @retval (next_state, result) tuple, (SBE37ProtocolState.COMMAND,
        None) if successful.
        @throws InstrumentTimeoutException if device cannot be woken for command.
        @throws InstrumentProtocolException if command misunderstood or
        incorrect prompt received.
        """
        log.debug("in hander_autosample_stop_autosample")
        next_state = None
        next_agent_state = None
        result = None

        # Update configuration parameters and send.
        self._do_cmd_resp(InstrumentCmds.IMMEDIATE_STATUS,
                          expected_prompt = Prompt.COMMAND, *args, **kwargs)
        
        next_state = ProtocolState.COMMAND
        next_agent_state = ResourceAgentState.COMMAND

        return (next_state, (next_agent_state, result))

    ########################################################################
    # Command handlers.
    ########################################################################

    def _handler_command_enter(self, *args, **kwargs):
        """
        Enter command state.
        @throws InstrumentTimeoutException if the device cannot be woken.
        @throws InstrumentProtocolException if the update commands and not recognized.
        """
        # Command device to update parameters and send a config change event.
        log.debug("*** IN _handler_command_enter(), updating params")
        self._update_params()

        # Tell driver superclass to send a state change event.
        # Superclass will query the state.
        self._driver_event(DriverAsyncEvent.STATE_CHANGE)

    def _handler_command_acquire_sample(self, *args, **kwargs):
        """
        Acquire sample from device.
        @retval (next_state, result) tuple, (None, sample dict).
        @throws InstrumentTimeoutException if device cannot be woken for command.
        @throws InstrumentProtocolException if command could not be built or misunderstood.
        @throws SampleException if a sample could not be extracted from result.
        """

        log.debug("Testing _handler_command_acquire_sample")
        next_state = None
        next_agent_state = None
        result = None

        kwargs['timeout'] = 30 # samples can take a long time

		# Acquire one sample and return the result.
        result = self._do_cmd_resp(InstrumentCmds.TAKE_SAMPLE, *args, **kwargs)

        return (next_state, (next_agent_state, result))

    def _handler_command_acquire_status(self, *args, **kwargs):
        """
        Acquire sample from device.
        @retval (next_state, result) tuple, (None, sample dict).
        @throws InstrumentTimeoutException if device cannot be woken for command.
        @throws InstrumentProtocolException if command could not be built or misunderstood.
        @throws SampleException if a sample could not be extracted from result.
        """

        log.debug("Testing _handler_command_acquire_status")
        next_state = None
        next_agent_state = None
        result = None

        kwargs['timeout'] = 30 # samples can take a long time

        # Acquire one sample and return the result.
        result = self._do_cmd_resp(InstrumentCmds.DEVICE_STATUS, *args, **kwargs)

        return (next_state, (next_agent_state, result))
    
    def _handler_command_acquire_configuration(self, *args, **kwargs):
        """
        Acquire sample from device.
        @retval (next_state, result) tuple, (None, sample dict).
        @throws InstrumentTimeoutException if device cannot be woken for command.
        @throws InstrumentProtocolException if command could not be built or misunderstood.
        @throws SampleException if a sample could not be extracted from result.
        """

        log.debug("Testing _handler_command_acquire_configuration")
        next_state = None
        next_agent_state = None
        result = None

        kwargs['timeout'] = 30 # samples can take a long time

        # Acquire one sample and return the result.
        result = self._do_cmd_resp(InstrumentCmds.GET_CONFIGURATION, *args, **kwargs)

        return (next_state, (next_agent_state, result))

    def _handler_command_get(self, *args, **kwargs):
        """
        Get parameter
        """
        log.debug("^^^^^^^^^^^^^^^^^^ FSM_TRACKER: in _handler_command_get")        
        next_state = ProtocolState.COMMAND
        result = None

        self._build_param_dict()     #make sure data is up-to-date

        # Retrieve the required parameter, raise if not present.
        try:
            params = args[0]

        except IndexError:
            raise InstrumentParameterException('Get command requires a parameter list or tuple.')

        # If all params requested, retrieve config.
        if params == DriverParameter.ALL or DriverParameter.ALL in params:
            result = self._param_dict.get_config()

        # If not all params, confirm a list or tuple of params to retrieve.
        # Raise if not a list or tuple.
        # Retireve each key in the list, raise if any are invalid.

        else:
            if not isinstance(params, (list, tuple)):
                raise InstrumentParameterException('Get argument not a list or tuple.')
            result = {}
            for key in params:
                val = self._param_dict.get(key)
                log.debug("KEY = " + str(key) + " VALUE = " + str(val))
                result[key] = val

        return (next_state, result)
           
    def _get_from_cache(self, param):
        '''
        Parameters read from the instrument header generated are cached in the
        protocol.  These currently are firmware, serial number, and instrument
        type. Currently I assume that the header has already been displayed
        by the instrument already.  If we can't live with that assumption
        we should augment this method.
        @param param: name of the parameter.  None if value not cached.
        @return: Stored value
        '''
        if(param == Parameter.PUMP_PULSE):
            val = sami_cache_dict[Parameter.PUMP_PULSE]
        elif(param == Parameter.PUMP_ON_TO_MEASURE):
            val = sami_cache_dict[Parameter.PUMP_ON_TO_MEASURE]
        elif(param == Parameter.NUM_SAMPLES_PER_MEASURE):
            val = sami_cache_dict['NUM_SAMPLES_PER_MEASURE']
        elif(param == Parameter.NUM_CYCLES_BETWEEN_BLANKS):
            val = sami_cache_dict['NUM_CYCLES_BETWEEN_BLANKS']
        elif(param == Parameter.NUM_REAGENT_CYCLES):
            val = sami_cache_dict['NUM_REAGENT_CYCLES']
        elif(param == Parameter.NUM_BLANK_CYCLES):
            val = sami_cache_dict['NUM_BLANK_CYCLES']
        elif(param == Parameter.FLUSH_PUMP_INTERVAL_SEC):
            val = sami_cache_dict['FLUSH_PUMP_INTERVAL_SEC']
        elif(param == Parameter.STARTUP_BLANK_FLUSH_ENABLE):
            val = sami_cache_dict['STARTUP_BLANK_FLUSH_ENABLE']
        elif(param == Parameter.FLUSH_PUMP_INTERVAL_SEC):
            val = sami_cache_dict['FLUSH_PUMP_INTERVAL_SEC']
        elif(param == Parameter.PUMP_PULSE_POST_MEASURE_ENABLE):
            val = sami_cache_dict['PUMP_PULSE_POST_MEASURE_ENABLE']
        elif(param == Parameter.NUM_EXTRA_PUMP_CYCLES):
            val = sami_cache_dict['NUM_EXTRA_PUMP_CYCLES']
        else:
            log.debug("got nothing!!!!!!!!!!!!!!!!!")
        return val
    
    def _handler_command_set(self, params, *args, **kwargs):
        """
        """
        next_state = None
        next_agent_state = None
        result = None
        result_vals = {}

        log.debug("Testing _handler_command_set_configuration")

        # Get the current configuration parameters to see if we need to change.                
        log.debug("********** HEre 1")
               
        if ((params == None) or (not isinstance(params, dict))):
            raise InstrumentParameterException()
        
        name_values = params
        for key in name_values.keys():
            if not Parameter.has(key):
                raise InstrumentParameterException()
            try:
                str_val = self._param_dict.format(key, name_values[key])
                log.debug("str_value ========= " + str_val)
            except KeyError:
                raise InstrumentParameterException()
            
            ## result_vals[key] = self._do_cmd_resp(Command.SET, key, str_val,
            ##                                     expected_prompt=Prompt.COMMAND,
            ##                                     write_delay=self.write_delay)
            
            # Populate with actual value instead of success flag
            ## if result_vals[key]:
            ##    result_vals[key] = name_values[key]
                
        self._update_params()

        """
         working last.
        for param in params:
            if not Parameter.has(param):
                raise InstrumentParameterException()
            else:
                tmp = self._get_from_cache(param)
                result_vals[param] = tmp
                log.debug("param from cache = " + str(tmp))

        result = result_vals
        """
#        kwargs['timeout'] = 30 # samples can take a long time
		# Run trick for Configuration Update in instrument.
        result = self._do_cmd_resp(InstrumentCmds.GET_CONFIGURATION, *args, **kwargs)
        if not result:
            log.debug("*** no result!")
        log.debug("********** HEre 2")
		# In 30 seconds should receive message>
		# Build configuration string and send - this can be done in the build handler.???

        return (next_state, (next_agent_state, result))

    def _handler_command_start_autosample(self):
        """
        Start autosample
        """
        log.debug("_handler_command_start_autosample:")
        next_state = None
        next_agent_state = None
        result = None

        # self._do_cmd_no_response(Command.GoGo)
        next_state = ProtocolState.AUTOSAMPLE
        next_agent_state = ResourceAgentState.STREAMING
        
        return (next_state, (next_agent_state, result))
        
    def _handler_command_clock_sync(self, *args, **kwargs):
        """
        execute a clock_sync by checking the current time.
        """
        next_state = None
        next_agent_state = None
        result = None
        # self._do_cmd_device_status();
        # Decode current time from device status.
        # compare time against sync time.
        # if <> by some delta then we must resend configuration to update time.
#       str_time = get_timestamp_delayed("%M %S %d %H %y %m")
        timestamp_sec = get_timestamp_sec(True)
        str_val = self._param_dict.format(Parameter.DEVICE_DATE_TIME, timestamp_sec)
        self._do_cmd_resp(InstrumentCmds.SET_REAL_TIME_CLOCK, byte_time, **kwargs)

        return (next_state, (next_agent_state, result))
    
    ########################################################################
    # Autosample handlers.
    ########################################################################
    def _handler_command_autosample_test_get(self, *args, **kwargs):
        """
        Get device parameters from the parameter dict.
        @param args[0] list of parameters to retrieve, or DriverParameter.ALL.
        @throws InstrumentParameterException if missing or invalid parameter.
        """
        next_state = None
        result = None

        # Retrieve the required parameter, raise if not present.
        try:
            params = args[0]

        except IndexError:
            raise InstrumentParameterException('Get command requires a parameter list or tuple.')

        # If all params requested, retrieve config.
        if params == DriverParameter.ALL or DriverParameter.ALL in params:
            result = self._param_dict.get_config()

        # If not all params, confirm a list or tuple of params to retrieve.
        # Raise if not a list or tuple.
        # Retireve each key in the list, raise if any are invalid.

        else:
            if not isinstance(params, (list, tuple)):
                raise InstrumentParameterException('Get argument not a list or tuple.')
            result = {}
            for key in params:
                val = self._param_dict.get(key)
                result[key] = val

        return (next_state, result)

    ########################################################################
    # Direct access handlers.
    # Not Used - Assuming Command Line is Sufficient.
    ########################################################################

    ########################################################################
    # Startup parameter handlers
    ########################################################################
    def apply_startup_params(self):
        """
        Apply all startup parameters.  First we check the instrument to see
        if we need to set the parameters.  If they are they are set
        correctly then we don't do anything.

        If we need to set parameters then we might need to transition to
        command first.  Then we will transition back when complete.

        @todo: This feels odd.  It feels like some of this logic should
               be handled by the state machine.  It's a pattern that we
               may want to review.  I say this because this command
               needs to be run from autosample or command mode.
        @raise: InstrumentProtocolException if not in command or streaming
        """
        # Let's give it a try in unknown state
        log.debug("*********** CURRENT STATE: %s" % self.get_current_state())
        if (self.get_current_state() != ProtocolState.COMMAND and
            self.get_current_state() != ProtocolState.AUTOSAMPLE):
            raise InstrumentProtocolException("Not in command or autosample state. Unable to apply startup params")

        # If we are in streaming mode and our configuration on the
        # instrument matches what we think it should be then we
        # don't need to do anything.
        if(not self._instrument_config_dirty()):
            return True

        error = None

        try:
            self._apply_params()

        # Catch all error so we can put ourself back into
        # streaming.  Then rethrow the error
        except Exception as e:
            error = e

        finally:
            # Switch back to streaming
            if(logging):
                self._start_logging()

        if(error):
            raise error

    def _apply_params(self):
        """
        apply startup parameters to the instrument.
        @raise: InstrumentProtocolException if in wrong mode.
        """
        log.debug("*********** _apply_params()")
        config = self.get_startup_config()
        self._set_params(config)

    def _instrument_config_dirty(self):
        """
        Read the startup config and compare that to what the instrument
        is configured too.  If they differ then return True
        @return: True if the startup config doesn't match the instrument
        @raise: InstrumentParameterException
        """
        log.debug(">>>>>>>>>>>>>>>> _instrument_config_dirty()")
        # Refresh the param dict cache
        self._do_cmd_resp(InstrumentCmds.GET_CONFIGURATION)

        startup_params = self._param_dict.get_startup_list()
        log.debug("Startup Parameters: %s" % startup_params)

        for param in startup_params:
            if not Parameter.has(param):
                raise InstrumentParameterException()

            if (self._param_dict.get(param) != self._param_dict.get_config_value(param)):
                log.debug("DIRTY: %s %s != %s" % (param, self._param_dict.get(param), self._param_dict.get_config_value(param)))
                return True

        log.debug("Clean instrument config")
        return False
    
    ########################################################################
    # Private helpers.
    ########################################################################
    def _is_logging(self, timeout=TIMEOUT):
        """
        Poll the instrument to see if we are in logging mode.  Return True
        if we are, False if not, or None if we couldn't tell.
        @param: timeout - Command timeout
        @return: True - instrument logging, False - not logging,
                 None - unknown logging state
        """
        # The device status has a flag to indicate if we're recording.
        self._do_cmd_resp(InstrumentCmds.DEVICE_STATUS,timeout=timeout)
        pd = self._param_dict.get_config()
        log.debug("Logging? %s" % pd.get(SamiStatusDataParticleKey.RECORDING_ACTIVE))
        return pd.get(SamiStatusDataParticleKey.RECORDING_ACTIVE)
    
    def _convert_sami_time_to_sec(self, s):
        """
        Test: CAB39E84 = Time of programming (GMT) Oct 6, 2011 18:05:56 (total seconds from 1/1/1904)
        """
        tsec = int(s,16)
        if( tsec > NSECONDS_1904_TO_1970 ):
            tsec = tsec - NSECONDS_1904_TO_1970
        timestamp = time.gmtime(tsec)   # Convert to tuple for easy decoding.
        log.debug(" sami_string_to_time " + str(hex(tsec)) )
        return(timestamp)

    def _decode_device_status_word(self, status):
        clock_active         = bool(status & 0x001)      
        recording_active     = bool(status & 0x002)
        record_end_on_time   = bool(status & 0x004)
        record_memory_full   = bool(status & 0x008)
        record_end_on_error  = bool(status & 0x010)
        record_data_download_ok = bool(status & 0x020)
        record_flash_open    = bool(status & 0x040)
        battery_error_fatal  = bool(status & 0x080)
        battery_low_measurement = bool(status & 0x100)
        battery_low_bank     = bool(status & 0x200)
        battery_low_external = bool(status & 0x400)
        
        external_device_fault = 0x0
        if( (status & 0x0800) == 0x0800 ):
            external_device_fault = external_device_fault | 0x1
        if( (status & 0x1000) == 0x1000 ):
            external_device_fault = external_device_fault | 0x2
        if( (status & 0x2000) == 0x2000 ):
            external_device_fault = external_device_fault | 0x4
            
        flash_erased     = bool(status & 0x4000)
        power_on_invalid = bool(status & 0x8000)
    
        log.debug("status_flags = " + str(hex(status)) )
        log.debug("clk_active = " + str(clock_active))
        log.debug("recording_active = " + str(recording_active))
        log.debug("record_end_on_time = " + str(record_end_on_time))
        log.debug("record_memory_full = " + str(record_memory_full))
        log.debug("record_end_on_error = " + str(record_end_on_error))
        log.debug("record_data_download_ok = " + str(record_data_download_ok))
        log.debug("record_flash_open = " + str(record_flash_open))
        log.debug("battery_error_fatal = " + str(battery_error_fatal))
        log.debug("battery_low_measurement = " + str(battery_low_measurement))
        log.debug("battery_low_bank = " + str(battery_low_bank))
        log.debug("battery_low_external = " + str(battery_low_external))
        log.debug("external_device_fault = " + str(external_device_fault))
        log.debug("flash_erased = " + str(flash_erased))
        log.debug("power_on_invalid = " + str(power_on_invalid))
    
    def _sami_update_device_status(self, s):
        r = False
        p = DEVICE_STATUS_REGEX_MATCHER    
        m0 = p.match(s)  
        if( m0 ):
            # Time in seconds sionce last L command (cleared 
            txt = m0.group(1)       
            seconds = int(txt,16)
            m, s = divmod(seconds, 60)
            h, m = divmod(m, 60)
            d, h = divmod(h, 24)
            log.debug("%d %d:%02d:%02d" % (d, h, m, s) )
            # Extract Status nibbles as hexi
            # Next word is status information.
            txt = m0.group(2)
            status = int(txt,16)
            self._decode_device_status_word(status)
            r = True
        return(r)
        
    def _sami_update_config(self, s):
        r = False
        log.debug("config_str = " + s)

        time_of_program = None  # Total Seconds from 1/1/1904
        mode = None
        timer_interval_sami = None
        driver_id_sami = None
        param_ptr_sami = None
                    
        # Configuration string decoding
        p = CONFIG_REGEX_NL_MATCHER
        m0 = p.match(s)
        if( not m0 ):
            log.debug("try for no NL")
            p = CONFIG_REGEX_MATCHER
            m0 = p.match(s)
            
        if( m0 ):
            txt = m0.group(1)
            txt = "C" + txt          # Restore "C" removed during match ID.
            # CJC: For some crazy reason we are getting a CC character in the start. This is very bad.
            log.debug("PgmDate: " + txt )
            seconds = self._convert_sami_time_to_sec( txt )
            log.debug('time of program = ' + str(seconds) + " " + time.asctime(seconds) )
            time_of_program = seconds;

            # Time to Start        
            txt = m0.group(2)
            log.debug("group2 = " + txt)
            seconds = int(txt,16)
            m, s = divmod(seconds, 60)
            h, m = divmod(m, 60)
            d, h = divmod(h, 24)
            log.debug("TimeTill Start Time: %d %d:%02d:%02d" % (d, h, m, s) )
            # Time Till Stop.
            txt = m0.group(3)
            log.debug("group3 = " + txt)
            seconds = int(txt,16)
            m, s = divmod(seconds, 60)
            h, m = divmod(m, 60)
            d, h = divmod(h, 24)
            log.debug("TimeTill Stop Time: %d %d:%02d:%02d" % (d, h, m, s) )
        
            txt = m0.group(4)
            mode = int(txt,16)
            log.debug("Mode: " + txt + " " + str(hex(mode)) )
                  
            idx = 5
            for i in range(0,5):
                log.debug("idx = " + str(i) )
                t1 = m0.group(idx)
                log.debug("sami_interval: " + m0.group(idx) + " " + str(int(t1,16)) )
                t2 = m0.group(idx+1)
                log.debug("sami_driver_id: " + m0.group(idx+1) + " " + str(int(t2,16)) )
                t3 = m0.group(idx+2)
                log.debug("sami_param_ptr: " + m0.group(idx+2) + " " + str(int(t3,16)) )
                idx = idx + 3
                
                if( i == 0 ):
                    # SAMI Interval Information
                    timer_interval_sami = int(t1,16)
                    driver_id_sami = int(t2,16)
                    param_ptr_sami = int(t3,16)
                    # Verify                    
                    if( param_ptr_sami != 1):
                        log.debug("Invalid SAMI Pointer to Params " + str(hex(param_ptr_sami)))
                        # r = False
                        # return(r)
                
            pco2_driver_params = m0.group(idx)
            log.debug("Global Config: " + m0.group(idx) )
            idx = idx + 1
               
        #    print("CO2 Param: " + m0.group(idx) )
            log.debug("idx = " + str(idx))
            txt = m0.group(idx)
            idx = idx + 1
            tmp = int(txt,16)
#            self._set_from_value(Parameter.PUMP_PULSE, tmp) # int(txt,16))
            sami_cache_dict[Parameter.PUMP_PULSE] = tmp
            log.debug("Pump Pulse: " + txt + " " + str( hex(tmp) ))
            
            txt = m0.group(idx)
            idx = idx + 1
            tmp = int(txt,16)
#            self._set_from_value(Parameter.PUMP_ON_TO_MEASURE, tmp)
            sami_cache_dict[Parameter.PUMP_ON_TO_MEASURE] = tmp
            log.debug("Pump On To Measure: " + txt + " " + str( hex(tmp) ))
            
            txt = m0.group(idx)
            idx = idx + 1
            tmp = int(txt,16)
#            self._set_from_value(Parameter.NUM_SAMPLES_PER_MEASURE, tmp)
            sami_cache_dict[Parameter.NUM_SAMPLES_PER_MEASURE] = tmp
            log.debug("Samples Per Measure: " + txt + " " + str( hex(tmp)) )
            
            txt = m0.group(idx)
            idx = idx + 1
            tmp = int(txt,16)
#            self._set_from_value(Parameter.NUM_CYCLES_BETWEEN_BLANKS, txt)
            sami_cache_dict[Parameter.NUM_CYCLES_BETWEEN_BLANKS] = tmp

            log.debug("Cycles Between Blanks: " + txt + " " + str( hex(tmp)) )
            
            txt = m0.group(idx)
            idx = idx + 1
            tmp = int(txt,16)
#            self._set_from_value(Parameter.NUM_REAGENT_CYCLES, txt)
            sami_cache_dict[Parameter.NUM_REAGENT_CYCLES] = tmp
            log.debug("Num Reagent Cycles: " + txt + " " + str( hex(tmp)) )

            txt = m0.group(idx)
            idx = idx + 1
            tmp = int(txt,16)
#            self._set_from_value(Parameter.NUM_BLANK_CYCLES, txt)
            sami_cache_dict[Parameter.NUM_BLANK_CYCLES] = tmp
            log.debug("Num Blank Cycles: " + txt + " " + str(hex(tmp)) )

            txt = m0.group(idx)
            idx = idx + 1     
            tmp = int(txt,16)       
#            self._set_from_value(Parameter.FLUSH_PUMP_INTERVAL_SEC, txt)
            sami_cache_dict[Parameter.FLUSH_PUMP_INTERVAL_SEC] = tmp
            log.debug("Flush Pump Interval: " + txt + " " + str( hex(tmp)) )
            txt = m0.group(idx)
            idx = idx + 1            
            bit_switch = int(txt,16)
            log.debug("Bit Switch: " + txt + " " + str( hex(int(txt,16)) ))
            # Enable logic inverted.
            enable = 1
            if( bool(bit_switch & 0x1) == True):
                enable = 0
#            self._set_from_value(Parameter.STARTUP_BLANK_FLUSH_ENABLE, str(enable))
            sami_cache_dict[Parameter.STARTUP_BLANK_FLUSH_ENABLE] = enable

            enable = 0
            if( bool(bit_switch & 0x2) == True):
                enable = 1
#            self._set_from_value(Parameter.PUMP_PULSE_POST_MEASURE_ENABLE, str(enable))
            sami_cache_dict[Parameter.PUMP_PULSE_POST_MEASURE_ENABLE] = enable
            
            txt = m0.group(idx)
            idx = idx + 1      
            tmp = int(txt,16)      
#            self._set_from_value(Parameter.NUM_EXTRA_PUMP_CYCLES, txt)
            sami_cache_dict[Parameter.NUM_EXTRA_PUMP_CYCLES] = tmp
            log.debug("Num Extra Pump Cycles: " + txt + " " + str( hex(tmp) ))
            
            log.debug("idx = " + str(idx))
            log.debug("Ser Param: " + m0.group(idx) )
            idx = idx + 1
            
            log.debug("duration1: " + m0.group(idx) )
            idx = idx + 1
            
            log.debug("duration2: " + m0.group(idx) )
            idx = idx + 1
            
            log.debug("Meaningless parameter: " + m0.group(idx) )
            idx = idx + 1
            
            # Update here.
            r = True
        else:
            log.debug("*(((((((((( SAMI Configuration Match Failure: " + s)
        return(r)
        
    def _set_from_value(self, name, val):
        pd= self._param_dict.get_config()
        log.debug("  ** pd = " + str(pd[name]));
        self._param_dict.set(name, val)
        
    def _sami_do_cmd_config(self):
        r = False
        str_cmd = "%s" %(InstrumentCmds.GET_CONFIGURATION) + NEWLINE
        self._do_cmd_direct(str_cmd)
        time.sleep(0.5)
        (prompt,result) = self._get_response(timeout=10)

        if( result != ""):
            log.debug("process result.................")
            if( self._sami_update_config( result ) == True ):
                self._param_dict.update_many(result)
                r = True
        else:
            log.debug("*** _sami_do_cmd_config config ==== " + result)
        return(r)
    
    def _sami_do_cmd_device_status(self):
        str_cmd = "%s" % (InstrumentCmds.DEVICE_STATUS) + NEWLINE
        self._do_cmd_direct(str_cmd)
        time.sleep(0.5)
        (prompt,result) = self._get_response(timeout=10)

        if( result != ""):
            log.debug("process result.................")
            if( self._sami_update_device_status( result ) == True ):
                self._param_dict.update(result)
        else:
            log.debug("*** _sami_do_cmd_device_status status ==== " + result)
            
    def _parse_config_response(self, response, prompt):
        """
        Response handler for configuration "L" command
        """
        log.debug("******* _parse_config_response....... ")
        log.debug("Response: " + response)
        result = None
        
        if prompt != Prompt.COMMAND:
            raise InstrumentProtocolException('cfg command not recognized: %s.' % response)

        # return the Ds as text
#        match = CONFIG_REGEX_MATCHER.search(response)
        match = CONFIG_REGEX_MATCHER.match(response)
        if match:
#            SamiConfigDataParticleKey.update(response)
            result = match.group(1)
            log.debug("     *** CONFIG match found " + result)
            # Command device to update parameters and send a config change event.
            self._update_params(timeout=3)
        else:
            # If typical command sequence fails then perform a direct command.
            log.debug("   config match is no " + response)
            self._sami_do_cmd_config()
            
        return result
    
    def _parse_I_response(self, response, prompt):
        """
        Response handler for Device Status command
        """
        result = None
        
        if prompt != Prompt.COMMAND:
            raise InstrumentProtocolException('Command I not recognized: %s.' % response)
        
        # return the Ds as text
        result = response
        return result

    def _parse_S_response(self, response, prompt): #(self, cmd, *args, **kwargs):
        """
        Response handler for Device Status command
        """
        if prompt != Prompt.COMMAND:
            raise InstrumentProtocolException('Command S not recognized: %s.' % response)

        # return the Ds as text
        log.debug("Match parse_S_response....")
        result = response
        
        match = DEVICE_STATUS_REGEX_MATCHER.search(response)
        if match:
            result = match.group(1)
            log.debug("_parse_S match = ==== " + str(result))

        return result

    def _parse_R_response(self, response, prompt):
        """
        Response handler for R command.
        @param response command response string.
        @param prompt prompt following command response.
        @retval sample dictionary containig c, t, d values.
        @throws InstrumentProtocolException if ts command misunderstood.
        @throws InstrumentSampleException if response did not contain a sample
        """
        next_state = None
        next_agent_state = None
        result = None

        if prompt != Prompt.COMMAND:
            raise InstrumentProtocolException('Command R not recognized: %s', response)

        # Extract the sample.
        log.debug(">>>>>>>>>>> Decode R response please = " + response)

        log.debug("_parse_R_response RETURNING RESULT=" + str(result))
        return result
    
    ########################################################################
    # Static Helpers.
    ########################################################################
    def _wakeup(self, timeout):
        """There is no wakeup sequence for this instrument"""
        pass
    
    def _update_params(self, *args, **kwargs):
        """Fetch the parameters from the device, and update the param dict.
        
        @param args Unused
        @param kwargs Takes timeout value
        @throws InstrumentProtocolException
        @throws InstrumentTimeoutException
        """
        log.debug("Updating parameter dict")
        # Get all the key values.
        old_config = self._param_dict.get_config()
           
        # Issue display commands and parse results.
        if( self._sami_do_cmd_config() == False ):
            log.debug(" Failed mission to read configuration. ")
        else:
            new_config = self._param_dict.get_config()

            # Get new param dict config. If it differs from the old config,
            # tell driver superclass to publish a config change event.
            if (new_config != old_config):
                log.debug("_update_params - ConfigChange")
                self._driver_event(DriverAsyncEvent.CONFIG_CHANGE)
            else:
                log.debug("No configuration change")
    # End _update_params()
    
    ########################################################################
    # Static helpers to format set commands.
    ########################################################################
    @staticmethod
    def _decode_switch_bit_0(input):
        log.debug("decode_switch_bit_0 - Invert logic " + input)
        base_index = 70 + 14
        s = input[base_index:(base_index+2)]
        val = int(s,16)
        r = (bool(val & 0x1) == False)
        return( r)
    
    @staticmethod
    def _decode_switch_bit_1(input):
        log.debug("decode_switch_bit_0 - Invert logic " + input)
        base_index = 70 + 14
        s = input[base_index:(base_index+2)]
        val = int(s,16)
        r = bool(val & 0x2)
        return( r)
    
    @staticmethod
    def _string_to_string(v):
        return v
    
    @staticmethod
    def _decode_bit_0(v):
        r  = ((v & 0x1) == 0x1)
        return r

    @staticmethod
    def _string_to_int(v):
        log.debug("_string_to_int " + v)
        r = int(v,16)
        return r
    
    @staticmethod
    def _string_to_string(v):
        return v

    # Tools for configuration.
    @staticmethod
    def _int8_to_string(value, pos=0):
        """
        Convert 8-bit value to a 2-character string at position (pos)
        @param timeout: how long to wait for a prompt
        @return: True if successful
        @raise: InstrumentTimeoutException if prompt isn't seen
        @raise: InstrumentProtocolException failed to stop logging
        """
        if not isinstance(value,int):
            raise InstrumentParameterException('Value %s is not an int-8' % str(value))
        if value > 255:
            raise InstrumentParameterException('Value %s is not an int-8' % str(value))
        else:
            msg = '{:02x}'.format(value)
            sami_configuration_str[pos:pos+2] = msg
            print("sami_string is now " + sami_configuration_str)
            return(msg)

    @staticmethod
    def _int24_to_string(value):
        if not isinstance(value,int):
            raise InstrumentParameterException('Value %s is not an int-24' % str(value))
        else:
            msg = '{:06x}'.format(value)
            return(msg)

    @staticmethod
    def _int32_to_string(value):
        log.debug("*********************************************** _int32_to_string   ")
        if not isinstance(value,int):
            raise InstrumentParameterException('Value %s is not an int-32' % str(value))
        else:
#            log.debug("Inside _int32_to_string() 1 " + value)
            log.debug("Inside _int32_to_string() 2 " + str(value))
            msg = '{:08x}'.format(value)
            return(msg)
        
    # Convert a time string into Epoc Seconds.
    def convert_timestamp_to_sec(time_str):
        '''
        Convert a time string of the format dd-mm-yyyy hr:mn:sec to seconds since 1970.
        '''
        sec = 0;
        print("s = " + time_str)
        timestamp_regex = re.compile(r"(\d\d)-(\d\d)-(\d\d\d\d) (\d\d):(\d\d):(\d\d)")
        match = timestamp_regex.match(time_str)
        if( match ):
            dd = match.group(1)
            mm = match.group(2)
            yy = match.group(3)
            hr = match.group(4)
            mn = match.group(5)
            ss = match.group(6)
            
            # month_mapping: a mapping for 3 letter months to integers
            d1 = datetime.datetime(int(yy), int(mm), int(dd), int(hr), int(mn), int(ss))
            print("d1 = " + str(d1) )
            d1_tuple = d1.timetuple()
            secondsF = calendar.timegm(d1_tuple)
            sec = int(secondsF)
        return(sec)
        

    

