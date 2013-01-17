
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

from mi.core.log import get_logger ; log = get_logger()

from mi.core.common import BaseEnum
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
from mi.core.instrument.data_particle import DataParticle
from mi.core.instrument.data_particle import DataParticleKey
from mi.core.instrument.data_particle import CommonDataParticleType
from mi.core.instrument.chunker import StringChunker

# newline.
NEWLINE = '\r\n'

# default timeout.
TIMEOUT = 10

# This will decode n+1 chars for {n}
DEVICE_STATUS_REGEX = r'[:](\w[0-9A-Fa-f]{4})(\w[0-9A-Fa-f]{3}).*?\r\n'
DEVICE_STATUS_REGEX_MATCHER = re.compile(DEVICE_STATUS_REGEX)

RECORD_TYPE4_REGEX = r'[*](\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{3})(\w[0-9A-Fa-f]{7})+.*?\r\n'
RECORD_TYPE4_REGEX_MATCHER = re.compile(RECORD_TYPE4_REGEX)

CONFIG_REGEX_OLD = r'[C](\w[0-9A-Fa-f]{7})(\w[0-9A-Fa-f]{7})(\w[0-9A-Fa-f]{7})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{17})(\w[0-9A-Fa-f]{25})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{3})(\w[0-9A-Fa-f]{1}).*?\r\n'
CONFIG_REGEX = r'[C](\w[0-9A-Fa-f]{7})(\w[0-9A-Fa-f]{7})(\w[0-9A-Fa-f]{7})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{25})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{3})(\w[0-9A-Fa-f]{1}).*?\r\n'
CONFIG_REGEX_MATCHER = re.compile(CONFIG_REGEX)

ERROR_REGEX = r'\?\w[0-9A-Fa-f]{1}.*?\r\n'
ERROR_REGEX_MATCHER = re.compile(ERROR_REGEX)

IMMEDIATE_STATUS_REGEX = r'(\w[0-9A-Fa-f]{1})(w[0-9A-Fa-f]{1}).*?\r\n'
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
    AUTO_STATUS_ON = 'F'
    AUTO_STATUS_OFF = 'F5A'

class ProtocolState(BaseEnum):
    """
    Instrument protocol states
    """
    UNKNOWN = DriverProtocolState.UNKNOWN
    COMMAND = DriverProtocolState.COMMAND
    AUTOSAMPLE = DriverProtocolState.AUTOSAMPLE
    DIRECT_ACCESS = DriverProtocolState.DIRECT_ACCESS

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
    START_DIRECT     = DriverEvent.START_DIRECT
    STOP_DIRECT      = DriverEvent.STOP_DIRECT
    START_AUTOSAMPLE = DriverEvent.START_AUTOSAMPLE
    STOP_AUTOSAMPLE  = DriverEvent.STOP_AUTOSAMPLE   
    EXECUTE_DIRECT   = DriverEvent.EXECUTE_DIRECT

class Capability(BaseEnum):
    """
    Protocol events that should be exposed to users (subset of above).
    """
    START_AUTOSAMPLE = ProtocolEvent.START_AUTOSAMPLE
    STOP_AUTOSAMPLE  = ProtocolEvent.STOP_AUTOSAMPLE    
#    GET_CONFIGURATION = ProtocolEvent.GET

class Parameter(DriverParameter):
    """
    Device specific parameters.
    """   
    # Configuration Parameter Information.
    CFG_PROGRAM_DATE = 'program_date'   # TIMESTAMP = 'TIMESTAMP'
    
# Device prompts.
class Prompt(BaseEnum):
    """
    Device i/o prompts..
    """
    IMMEDIATE_STATUS_COMMAND = 'I'
    BAD_COMMAND = '?'
    GET_CONFIGURATION_COMMAND = 'L'
    DEVICE_STATUS_COMMAND = 'S'
    CONFIRMATION_PROMPT = 'proceed Y/N ?'
    
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
    Routines for parsing raw data into a data particle structure. Override
    the building of values, and the rest should come along for free.
    """
    # Record information received from instrument may be data or control.
    _data_particle_type = DataParticleType.RECORD_PARSED

    def _build_parsed_values(self):
        # Restore the first character we removed for recognition.
        regex1 = RECORD_TYPE4_REGEX_MATCHER
        
        match = regex1.match(self.raw_data)
        if not match:
            raise SampleException("No regex match of parsed Record Type4 data: [%s]" % self.raw_data)

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
    PROGRAM_DATE = 'program_date'
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
    BLANK_FLUSH_ON_START_DISABLE = "blank_flush_on_start_disable"
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
        raw_data = "C" + self.raw_data
        regex1 = CONFIG_REGEX_MATCHER

        match = regex1.match(raw_data)
        if not match:
            raise SampleException("No regex match of parsed config data: [%s]" % raw_data)

        program_date = None
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
		
        timer_interval = []
        driver_id = []
        param_ptr = []
                
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
        blank_flush_on_start_disable = None
        pump_pulse_post_measure = None
        cycle_data = None
        
        # Not used and hard-coded right now.
        serial_settings = None

        # Decode Time Stamp since Launch       
        txt = match.group(1)
        program_date = int(txt,16)

        txt = match.group(2)
        start_time_offset = int(txt,16)
 
        txt = match.group(3)
        recording_time = int(txt,16)

        txt = match.group(4)
        mode = int(txt,16);          
        pmi_sample_schedule  = ((mode & MODE_PMI_SAMPLE_SCHEDULE) == MODE_PMI_SAMPLE_SCHEDULE)
        sami_sample_schedule = ((mode & MODE_SAMI_SAMPLE_SCHEDULE) == MODE_SAMI_SAMPLE_SCHEDULE)
        slot1_follows_sami_sample  = ((mode & MODE_SLOT1_FOLLOWS_SAMI_SAMPLE)  == MODE_SLOT1_FOLLOWS_SAMI_SAMPLE)
        slot1_independent_schedule = ((mode & MODE_SLOT1_INDEPENDENT_SCHEDULE) == MODE_SLOT1_INDEPENDENT_SCHEDULE)
        slot2_follows_sami_sample  = ((mode & MODE_SLOT2_FOLLOWS_SAMI_SAMPLE)  == MODE_SLOT2_FOLLOWS_SAMI_SAMPLE)
        slot2_independent_schedule = ((mode & MODE_SLOT2_INDEPENDENT_SCHEDULE) == MODE_SLOT2_INDEPENDENT_SCHEDULE)
        slot3_follows_sami_sample  = ((mode & MODE_SLOT3_FOLLOWS_SAMI_SAMPLE)  == MODE_SLOT3_FOLLOWS_SAMI_SAMPLE)
        slot3_independent_schedule = ((mode & MODE_SLOT3_INDEPENDENT_SCHEDULE) == MODE_SLOT3_INDEPENDENT_SCHEDULE)

        idx = 5
        device_group = []
        for i in range(5):
            txt = match.group(idx)
            timer_interval.append( int(txt,16) )
            log.debug(" timer_interval = " + txt)

            txt = match.group(idx+1)
            driver_id.append( int(txt,16) )
            log.debug(" driver_id = " + txt)
            
            txt = match.group(idx+2)
            param_ptr.append( int(txt,16) )
            log.debug(" param_ptr = " + txt)
            idx = idx + 3

        # The next byte is the Global Configuration Switches.
        txt = match.group(idx)
        idx = idx + 1
        cfg_reg = int(txt,16)
        use_baud_rate_57600    = ((cfg_reg & CFG_GLOBAL_BAUD_RATE_57600) == CFG_GLOBAL_BAUD_RATE_57600)
        send_record_type_early = ((cfg_reg & CFG_GLOBAL_SEND_RECORD_TYPE_EARLY) == CFG_GLOBAL_SEND_RECORD_TYPE_EARLY)
        send_live_records      = ((cfg_reg & CFG_GLOBAL_SEND_LIVE_RECORDS) == CFG_GLOBAL_SEND_LIVE_RECORDS)
                
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
        blank_flush_on_start_disable = (bit_switch & 0x1) == 0x1
        pump_pulse_post_measure = (bit_switch & 0x2) == 0x2

        txt = match.group(idx)
        idx = idx + 1
        cycle_data = int(txt,16)
    
        log.debug("pump_pulse = " + str(hex(pump_pulse)))
        log.debug("pump_on_to_measure = " + str(hex(pump_on_to_measure)))
        log.debug("samples_per_measure = " + str(hex(samples_per_measure)))
        log.debug("cycles_between_blanks = " + str(hex(cycles_between_blanks)))
        log.debug("num_reagent_cycles = " + str(hex(num_reagent_cycles)))
        log.debug("num_blank_cycles = " + str(hex(num_blank_cycles)))
        log.debug("flush_pump_interval = " + str(hex(flush_pump_interval)))
        log.debug("bit_switch = " + str(hex(bit_switch)))                   
        log.debug("cycle_data = " + str(hex(cycle_data)))
        
        txt = match.group(idx)
        idx = idx + 1
        serial_settings = txt
    
        #  print("duration1: " + m0.group(idx) )
        #  idx = idx + 1    
        #  print("duration2: " + m0.group(idx) )
        # idx = idx + 1    
        # print("Meaningless parameter: " + m0.group(idx) )
        # idx = idx + 1
    
        result = [{DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.PROGRAM_DATE,
                   DataParticleKey.VALUE: program_date},
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
                   DataParticleKey.VALUE: timer_interval[0]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.DRIVER_ID_SAMI,
                   DataParticleKey.VALUE: driver_id[0]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.PARAM_PTR_SAMI,
                   DataParticleKey.VALUE: param_ptr[0]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.TIMER_INTERVAL_1,
                   DataParticleKey.VALUE: timer_interval[1]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.DRIVER_ID_1,
                   DataParticleKey.VALUE: driver_id[1]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.PARAM_PTR_1,
                   DataParticleKey.VALUE: param_ptr[1]},     
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.TIMER_INTERVAL_2,
                   DataParticleKey.VALUE: timer_interval[2]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.DRIVER_ID_2,
                   DataParticleKey.VALUE: driver_id[2]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.PARAM_PTR_2,
                   DataParticleKey.VALUE: param_ptr[2]},              
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.TIMER_INTERVAL_3,
                   DataParticleKey.VALUE: timer_interval[3]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.DRIVER_ID_3,
                   DataParticleKey.VALUE: driver_id[3]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.PARAM_PTR_3,
                   DataParticleKey.VALUE: param_ptr[3]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.TIMER_INTERVAL_PRESTART,
                   DataParticleKey.VALUE: timer_interval[4]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.DRIVER_ID_PRESTART,
                   DataParticleKey.VALUE: driver_id[4]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.PARAM_PTR_PRESTART,
                   DataParticleKey.VALUE: param_ptr[4]},
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
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.BLANK_FLUSH_ON_START_DISABLE,
                   DataParticleKey.VALUE: blank_flush_on_start_disable},
                 {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.PUMP_PULSE_POST_MEASURE,
                   DataParticleKey.VALUE: pump_pulse_post_measure},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CYCLE_DATA,
                   DataParticleKey.VALUE: cycle_data},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.SERIAL_SETTINGS,
                  DataParticleKey.VALUE: serial_settings}]
        return result

class SamiImmediateStatusDataParticleKey(BaseEnum):
    PUMP_ON = "pump_on"
    VALVE_ON = "valve_on"
    EXTERNAL_POWER_ON = "external_power_on"
    DEBUG_LED_ON = "debug_led_on"
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
        
        pump_on  = (status_word & 0x01) == 0x01
        valve_on = (status_word & 0x02) == 0x02
        external_power_on = (status_word & 0x04) == 0x04
        debug_led_on  = (status_word & 0x10) == 0        
        debug_echo_on = (status_word & 0x20) == 0

        
        result = [{DataParticleKey.VALUE_ID: SamiImmediateStatusDataParticleKey.PUMP_ON,
                   DataParticleKey.VALUE: pump_on},
                  {DataParticleKey.VALUE_ID: SamiImmediateStatusDataParticleKey.VALVE_ON,
                   DataParticleKey.VALUE: valve_on},
                  {DataParticleKey.VALUE_ID: SamiStatusDataParticleKey.EXTERNAL_POWER_ON,
                   DataParticleKey.VALUE: external_power_on},
                  {DataParticleKey.VALUE_ID: SamiStatusDataParticleKey.DEBUG_LED_ON,
                   DataParticleKey.VALUE: debug_led_on},
                  {DataParticleKey.VALUE_ID: SamiStatusDataParticleKey.DEBUG_ECHO_ON,
                   DataParticleKey.VALUE: debug_echo_on} ]
       
        return result
        
class SamiStatusDataParticleKey(BaseEnum):
    TIME_OFFSET = "time_offset"
    CLOCK_ACTIVE = "clock_active"
    RECORDING_ACTIVE = "recording_active"
    RECORD_END_ON_TIME = "record_end_on_time"
    RECORD_MEMORY_FULL = "record_memory_full"
    RECORD_END_ON_ERROR = "record_end_on_error"
    RECORDING_ACTIVE = "recording_active"
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
        Take something in the autosample format and split it into
        values with appropriate tags
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
        battery_error_fatal  = None
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
            
        except ValueError:
            raise SampleException("ValueError while decoding data: [%s]" %
                                  self.raw_data)

        try:
            # Decode Bit-fields.
            txt = match.group(2)
            status_word = int(txt,16)
            
        except IndexError:
            #These are optional. Quietly ignore if they dont occur.
            pass

        else:
            # Decode the status word.
            clock_active         = (status_word & 0x001) == 0x001      
            recording_active     = (status_word & 0x002) == 0x002
            record_end_on_time   = (status_word & 0x004) == 0x004
            record_memory_full   = (status_word & 0x008) == 0x008
            record_end_on_error  = (status_word & 0x010) == 0x010
            data_download_ok     = (status_word & 0x020) == 0x020
            flash_memory_open    = (status_word & 0x040) == 0x040
            battery_error_fatal  = (status_word & 0x080) == 0x080
            battery_low_measurement = (status_word & 0x100) == 0x100
            battery_low_bank     = (status_word & 0x200) == 0x200
            battery_low_external = (status_word & 0x400) == 0x400
    
            # Or bits together for External fault information (Bit-0 = Dev-1, Bit-1 = Dev-2)
            external_device_fault = 0x0
            if( (status_word & 0x0800) == 0x0800 ):
                external_device_fault = external_device_fault | 0x1
            if( (status_word & 0x1000) == 0x1000 ):
                external_device_fault = external_device_fault | 0x2
            if( (status_word & 0x2000) == 0x2000 ):
                external_device_fault = external_device_fault | 0x4
        
            flash_erased     = (status_word & 0x4000) == 0x4000
            power_on_invalid = (status_word & 0x8000) == 0x8000
                    
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
                       DataParticleKey.VALUE: battery_error_fatal},
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
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.START_DIRECT, self._handler_command_start_direct)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.START_AUTOSAMPLE, self._handler_command_start_autosample)

        self._protocol_fsm.add_handler(ProtocolState.AUTOSAMPLE, ProtocolEvent.ENTER, self._handler_autosample_enter)
        self._protocol_fsm.add_handler(ProtocolState.AUTOSAMPLE, ProtocolEvent.STOP_AUTOSAMPLE, self._handler_autosample_stop_autosample)

        self._protocol_fsm.add_handler(ProtocolState.DIRECT_ACCESS, ProtocolEvent.ENTER, self._handler_direct_access_enter)
        self._protocol_fsm.add_handler(ProtocolState.DIRECT_ACCESS, ProtocolEvent.EXIT, self._handler_direct_access_exit)
        self._protocol_fsm.add_handler(ProtocolState.DIRECT_ACCESS, ProtocolEvent.STOP_DIRECT, self._handler_direct_access_stop_direct)
        self._protocol_fsm.add_handler(ProtocolState.DIRECT_ACCESS, ProtocolEvent.EXECUTE_DIRECT, self._handler_direct_access_execute_direct)

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

    @staticmethod
    def sieve_function(raw_data):
        """
        The method that splits samples
        """
        sieve_matchers = [DEVICE_STATUS_REGEX_MATCHER,
                          RECORD_TYPE4_REGEX_MATCHER,
                          CONFIG_REGEX_MATCHER,
                          ERROR_REGEX_MATCHER]

        return_list = []

        # log.debug("CJC raw_data: %s" % raw_data )

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
        user_configuration = kwargs.get('user_configuration', None)
        log.debug("Testing _build_config_command")

        if not user_configuration:
            raise InstrumentParameterException('_build_config_command command missing user_configuration parameter.')
        if not isinstance(user_configuration, str):
            raise InstrumentParameterException('_build_config_command command requires a string user_configuration parameter.')
        self._dump_config(user_configuration)        
            
        cmd_line = cmd + user_configuration
        return cmd_line
    
    def _build_param_dict(self):
        """
        Populate the parameter dictionary with parameters.
        For each parameter key, add match stirng, match lambda function,
        and value formatting function for set commands.
        """
        # Add parameter handlers to parameter dict.
        cfg_line_01 = CONFIG_REGEX
        
        #
        # Next 2 work together to pull 2 values out of a single line.
        #      
        # These parameters are pulled out of the "L" Command.       
        self._param_dict.add(Parameter.CFG_PROGRAM_DATE, 
            cfg_line_01,
            lambda match : match.group(1),                  # Input
            self._int32_to_string,                          # Output, note needs to be 7
            visibility=ParameterDictVisibility.READ_ONLY)
        
    def _got_chunk(self, chunk):
        """
        The base class got_data has gotten a chunk from the chunker.  Pass it to extract_sample
        with the appropriate particle objects and REGEXes.
        """
        if(self._extract_sample(SamiRecordDataParticle, RECORD_TYPE4_REGEX_MATCHER, chunk)):
            log.debug("_got_chunk of Record Data = Passed good")
        elif(self._extract_sample(SamiStatusDataParticle, DEVICE_STATUS_REGEX_MATCHER, chunk)):
            log.debug("_got_chunk of Status = Passed good")
        elif(self._extract_sample(SamiConfigDataParticle, CONFIG_REGEX_MATCHER, chunk)):
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
        config = self._protocol_fsm.on_event(ProtocolEvent.GET, [Parameter.CFG_PROGRAM_DATE], **kwargs)
        assert (isinstance(config, dict))
        assert (config.has_key(Parameter.CFG_PROGRAM_DATE))
        
        # Make sure we get these
        # TODO: endless loops seem like really bad idea
        while config[Parameter.CFG_PROGRAM_DATE] == InstErrorCode.HARDWARE_ERROR:
            config[Parameter.CFG_PROGRAM_DATE] = self._protocol_fsm.on_event(ProtocolEvent.GET, [Parameter.CFG_PROGRAM_DATE])
  
        return config
    
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
        next_state = None
        next_agent_state = None
        result = None

        # Update configuration parameters and send.
        self._do_cmd_resp(InstrumentCmds.SOFT_BREAK_SECOND_HALF,
                          expected_prompt = InstrumentPrompts.CONFIRMATION, *args, **kwargs)
        
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
        #self._update_params()

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

    def _handler_command_get(self, params=None, *args, **kwargs):
        """
        """
        next_state = None
        result = None

        log.debug("Testing _handler_command_get")

        # All parameters that can be set by the instrument.  Explicitly
        # excludes parameters from the instrument header.
        if (params == DriverParameter.ALL):
            params = [Parameter.CFG_PROGRAM_DATE]
            
        if ((params == None) or (not isinstance(params, list))):
            raise InstrumentParameterException()
        
        result_vals = {}
        for param in params:
            if not Parameter.has(param):
                raise InstrumentParameterException()
            result_vals[param] = self._param_dict.get(param) 

        result = result_vals

        log.debug("Get finished, next: %s, result: %s", next_state, result) 
        return (next_state, result)
    
    def _handler_command_set(self, params, *args, **kwargs):
        """
        """
        next_state = None
        next_agent_state = None
        result = None

        log.debug("Testing _handler_command_set_configuration")
        
        kwargs['timeout'] = 30 # samples can take a long time
		# Run trick for Configuration Update in instrument.
        result = self._do_cmd_resp(InstrumentCmds.SET_CONFIGURATION, *args, **kwargs)
		# In 30 seconds should receive message>
		# Build configuration string and send - this can be done in the build handler.???

        return (next_state, (next_agent_state, result))

    def _handler_command_start_direct(self):
        """
        Start direct access
        """
        next_state = ProtocolState.DIRECT_ACCESS
        next_agent_state = ResourceAgentState.DIRECT_ACCESS
        result = None
        log.debug("_handler_command_start_direct: entering DA mode")
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
    ########################################################################

    def _handler_command_start_direct(self, *args, **kwargs):
        """
        """

        next_state = None
        result = None

        next_state = ProtocolState.DIRECT_ACCESS
        next_agent_state = ResourceAgentState.DIRECT_ACCESS

        return (next_state, (next_agent_state, result))

    def _handler_direct_access_enter(self, *args, **kwargs):
        """
        Enter direct access state.
        """
        # Tell driver superclass to send a state change event.
        # Superclass will query the state.
        self._driver_event(DriverAsyncEvent.STATE_CHANGE)

        self._sent_cmds = []


    def _handler_direct_access_execute_direct(self, data):
        """
        """
        next_state = None
        result = None
        next_agent_state = None

        self._do_cmd_direct(data)

        # add sent command to list for 'echo' filtering in callback
        self._sent_cmds.append(data)

        return (next_state, (next_agent_state, result))

    def _handler_direct_access_stop_direct(self):
        """
        @throw InstrumentProtocolException on invalid command
        """
        next_state = None
        result = None

        next_state = ProtocolState.COMMAND
        next_agent_state = ResourceAgentState.COMMAND

        return (next_state, (next_agent_state, result))

    def _handler_direct_access_exit(self, *args, **kwargs):
        """
        Exit direct access state.
        """
        pass

    ########################################################################
    # Private helpers.
    ########################################################################

    def _parse_config_response(self, response, prompt):
        """
        Response handler for configuration "L" command
        """
        if prompt != Prompt.COMMAND:
            raise InstrumentProtocolException('cfg command not recognized: %s.' % response)

        # return the Ds as text
        match = CONFIG_REGEX_MATCHER.search(response)
        result = None

        if match:
            result = match.group(1)

        return result
    
    def _parse_ds_response(self, response, prompt):
        """
        Response handler for ds command
        """
        if prompt != Prompt.COMMAND:
            raise InstrumentProtocolException('ds command not recognized: %s.' % response)

        # return the Ds as text
        match = STATUS_REGEX_MATCHER.search(response)
        result = None

        if match:
            result = match.group(1)

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

    def _parse_S_response(self, response, prompt):
        """
        Response handler for Device Status command
        """
        if prompt != Prompt.COMMAND:
            raise InstrumentProtocolException('Command S not recognized: %s.' % response)

        # return the Ds as text
        result = response

        if match:
            result = match.group(1)

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

        result = self._do_cmd_resp(InstrumentCmds.TAKE_SAMPLE, *args, **kwargs)

        log.debug("_parse_R_response RETURNING RESULT=" + str(result))
        return result
    
    ########################################################################
    # Static Helpers.
    ########################################################################
    def _wakeup(self, timeout):
        """There is no wakeup sequence for this instrument"""
        pass
    
    ########################################################################
    # Static helpers to format set commands.
    ########################################################################
    @staticmethod
    def _string_to_string(v):
        return v
    
    @staticmethod
    def _string_to_int(v):
        r = int(v,16)
        return r
    
    @staticmethod
    def _string_to_string(v):
        return v

    # Tools for configuration.
    @staticmethod
    def _digit_to_ascii(digit):
        c = ord('0')
        if( digit <= 9 ):
            c = c + digit
        else:
            c = digit - 10 + ord('A')
        return(chr(c))

    @staticmethod
    def _int8_to_string(value):
        if not isinstance(value,int):
            raise InstrumentParameterException('Value %s is not an int-8' % str(value))
        else:
            msg = _digit_to_ascii( (value & 0x000000F0) >> 4 )
            msg = msg + _digit_to_ascii( (value & 0x0000000F) )
            return(msg)

    @staticmethod
    def _int24_to_string(value):
        if not isinstance(value,int):
            raise InstrumentParameterException('Value %s is not an int-24' % str(value))
        else:
            msg = _digit_to_ascii( (value & 0x00F00000) >> 20 )
            msg = msg + _digit_to_ascii( (value & 0x000F0000) >> 16 )
            msg = msg + _digit_to_ascii( (value & 0x0000F000) >> 12 )
            msg = msg + _digit_to_ascii( (value & 0x00000F00) >> 8 )
            msg = msg + _digit_to_ascii( (value & 0x000000F0) >> 4 )
            msg = msg + _digit_to_ascii( (value & 0x0000000F) )
            return(msg)

    @staticmethod
    def _int32_to_string(value):
        if not isinstance(value,int):
            raise InstrumentParameterException('Value %s is not an int-32' % str(value))
        else:
            log.debug("Inside _int32_to_string() " + int(value))
            msg = _digit_to_ascii( (value & 0xF0000000) >> 28 )
            msg = msg + _digit_to_ascii( (value & 0x0F000000) >> 24 )
            msg = msg + _digit_to_ascii( (value & 0x00F00000) >> 20 )
            msg = msg + _digit_to_ascii( (value & 0x000F0000) >> 16 )
            msg = msg + _digit_to_ascii( (value & 0x0000F000) >> 12 )
            msg = msg + _digit_to_ascii( (value & 0x00000F00) >> 8 )
            msg = msg + _digit_to_ascii( (value & 0x000000F0) >> 4 )
            msg = msg + _digit_to_ascii( (value & 0x0000000F) )
            return(msg)
        
    @staticmethod
    def _bit_to_string(self, value, field):
        if not isinstance(value,int):
            raise InstrumentParameterException('Value %s is not an bit' % str(value))
        else:
            ibit = (field << 1)
            tmp = (value & ibit) == ibit
            msg = _digit_to_ascii( tmp )
            return(msg)

    @staticmethod      
    def _bit0_to_string(self, value):
        msg = _bit_to_string(value, 0)
        return(msg)
    @staticmethod
    def _bit1_to_string(self, value):
        msg = _bit_to_string(value, 1)
        return(msg)
    @staticmethod
    def _bit2_to_string(self, value):
        msg = _bit_to_string(value, 2)
        return(msg)
    @staticmethod
    def _bit3_to_string(self, value):
        msg = _bit_to_string(value, 3)
        return(msg)
    @staticmethod
    def _bit4_to_string(self, value):
        msg = _bit_to_string(value, 4)
        return(msg)
    @staticmethod
    def _bit5_to_string(self, value):
        msg = _bit_to_string(value, 5)
        return(msg)
    @staticmethod
    def _bit6_to_string(self, value):
        msg = _bit_to_string(value, 6)
        return(msg)
    @staticmethod
    def _bit7_to_string(self, value):
        msg = _bit_to_string(value, 7)
        return(msg)
    @staticmethod
    def _bit8_to_string(self, value):
        msg = _bit_to_string(value, 8)
        return(msg)
    @staticmethod
    def _bit9_to_string(self, value):
        msg = _bit_to_string(value, 9)
        return(msg)
    @staticmethod
    def _bit10_to_string(self, value):
        msg = _bit_to_string(value, 10)
        return(msg)
    @staticmethod
    def _bit11_to_string(self, value):
        msg = _bit_to_string(value, 11)
        return(msg)
    @staticmethod
    def _bit12_to_string(self, value):
        msg = _bit_to_string(value, 12)
        return(msg)
    @staticmethod
    def _bit13_to_string(self, value):
        msg = _bit_to_string(value, 13)
        return(msg)
    @staticmethod
    def _bit14_to_string(self, value):
        msg = _bit_to_string(value, 14)
        return(msg)
    @staticmethod
    def _bit15_to_string(self, value):
        msg = _bit_to_string(value, 15)
        return(msg)
        

    

