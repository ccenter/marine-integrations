
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
from mi.core.instrument.data_particle import DataParticle
from mi.core.instrument.data_particle import DataParticleKey
from mi.core.instrument.data_particle import CommonDataParticleType
from mi.core.instrument.chunker import StringChunker

# newline.
NEWLINE = '\r\n'

# default timeout.
TIMEOUT = 10

# This will decode n+1 chars for {n}
STATUS_REGEX = r'[:](\w[0-9A-Fa-f]{4})(\w[0-9A-Fa-f]{3}).*?\r\n'
STATUS_REGEX_MATCHER = re.compile(STATUS_REGEX)

RECORD_TYPE4_REGEX = r'[*](\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{3})(\w[0-9A-Fa-f]{7})+.*?\r\n'
RECORD_TYPE4_REGEX_MATCHER = re.compile(RECORD_TYPE4_REGEX)

CONFIG_REGEX = r'[C](\w[0-9A-Fa-f]{7})(\w[0-9A-Fa-f]{7})(\w[0-9A-Fa-f]{7})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{1})(\w[0-9A-Fa-f]{17})(\w[0-9A-Fa-f]{25})(\w[0-9A-Fa-f]{5})(\w[0-9A-Fa-f]{3})(\w[0-9A-Fa-f]{1}).*?\r\n'
CONFIG_REGEX_MATCHER = re.compile(CONFIG_REGEX)

ERROR_REGEX = r'\?\w[0-9A-Fa-f]{1}.*?\r\n'
ERROR_REGEX_MATCHER = re.compile(ERROR_REGEX)

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
#    RAW = CommonDataParticleType.RAW
    DEVICE_STATUS = 'device_status_parsed'
    STATUS_PARSED = 'status_parsed'
    STATUS_SWBUS_PARSED = 'status_sw_bus_parsed'
    CONFIG_PARSED = 'config_parsed'
    RECORD_PARSED = 'record_parsed'

class InstrumentCmds(BaseEnum):
    """
    Device specific commands
    Represents the commands the driver implements and the string that must be sent to the instrument to
    execute the command.
    """
    SET_CONFIGURATION = 'L5A'
    READ_CONFIGURATION = 'L'
    DISPLAY_STATUS = 'I'
    QUIT_SESSION = 'Q'
    READ_SAMPLE = 'R'

    
class ProtocolState(BaseEnum):
    """
    Instrument protocol states
    """
    UNKNOWN = DriverProtocolState.UNKNOWN
    COMMAND = DriverProtocolState.COMMAND
    AUTOSAMPLE = DriverProtocolState.AUTOSAMPLE
    DIRECT_ACCESS = DriverProtocolState.DIRECT_ACCESS
#    TEST = DriverProtocolState.TEST
#    CALIBRATE = DriverProtocolState.CALIBRATE

class ExportedInstrumentCommand(BaseEnum):
    READ_CONFIGURATION = "EXPORTED_INSTRUMENT_CMD_READ_CONFIGURATION"
    SET_CONFIGURATION = "EXPORTED_INSTRUMENT_CMD_SET_CONFIGURATION"

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
    ACQUIRE_SAMPLE = DriverEvent.ACQUIRE_SAMPLE
    START_AUTOSAMPLE = DriverEvent.START_AUTOSAMPLE
    STOP_AUTOSAMPLE = DriverEvent.STOP_AUTOSAMPLE
    ACQUIRE_STATUS = DriverEvent.ACQUIRE_STATUS
    EXECUTE_DIRECT = DriverEvent.EXECUTE_DIRECT
    FORCE_STATE = DriverEvent.FORCE_STATE
    START_DIRECT = DriverEvent.START_DIRECT
    STOP_DIRECT = DriverEvent.STOP_DIRECT

    SETSAMPLING = 'PROTOCOL_EVENT_SETSAMPLING'
    QUIT_SESSION = 'PROTOCOL_EVENT_QUIT_SESSION'
    INIT_LOGGING = 'PROTOCOL_EVENT_INIT_LOGGING'

    # instrument specific events
    READ_CONFIGURATION = ExportedInstrumentCommand.READ_CONFIGURATION
    SET_CONFIGURATION = ExportedInstrumentCommand.SET_CONFIGURATION
    
    CLOCK_SYNC = DriverEvent.CLOCK_SYNC

class Capability(BaseEnum):
    """
    Protocol events that should be exposed to users (subset of above).
    """
    ACQUIRE_SAMPLE = ProtocolEvent.ACQUIRE_SAMPLE
    START_AUTOSAMPLE = ProtocolEvent.START_AUTOSAMPLE
    STOP_AUTOSAMPLE = ProtocolEvent.STOP_AUTOSAMPLE
    CLOCK_SYNC = ProtocolEvent.CLOCK_SYNC
    ACQUIRE_STATUS  = ProtocolEvent.ACQUIRE_STATUS
    
    READ_CONFIGURATION = ProtocolEvent.READ_CONFIGURATION
    SET_CONFIGURATION = ProtocolEvent.SET_CONFIGURATION

class Parameter(DriverParameter):
    """
    Device specific parameters.
    """
    # DS
    TIMESTAMP = 'TIMESTAMP'
    
# Device prompts.
class Prompt(BaseEnum):
    """
    Device i/o prompts..
    """
    STATUS_COMMAND = 'I'
    BAD_COMMAND = '?'
    CONFIG_COMMAND = 'L'
    CONFIRMATION_PROMPT = 'proceed Y/N ?'
    
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
            cs = 0
            cs_num_bytes = record_length - 1
            k = 3
            for i in range(cs_num_bytes):
                j = int(self.raw_data[k:k+2],16)
                cs = (cs + j)
                k = k + 2
            cs = cs & 0xFF        
            
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
    CFG_PROGRAM_DATE = 'program_date'
    CFG_START_TIME_OFFSET = 'start_offset'
    CFG_RECORDING_TIME = 'recording_time'
    CFG_MODE = 'mode'
    CFG_TIMER_INTERVAL_0 = 'timer_interval_0'
    CFG_DRIVER_ID_0 = 'driver_id_0'
    CFG_PARAM_PTR_0 = 'param_ptr_0'
    CFG_TIMER_INTERVAL_1 = 'timer_interval_1'
    CFG_DRIVER_ID_1 = 'driver_id_1'
    CFG_PARAM_PTR_1 = 'param_ptr_1'
    CFG_TIMER_INTERVAL_2 = 'timer_interval_2'
    CFG_DRIVER_ID_2 = 'driver_id_2'
    CFG_PARAM_PTR_2 = 'param_ptr_2'
    CFG_TIMER_INTERVAL_3 = 'timer_interval_3'
    CFG_DRIVER_ID_3 = 'driver_id_3'
    CFG_PARAM_PTR_3 = 'param_ptr_3'
    CFG_TIMER_INTERVAL_4 = 'timer_interval_4'
    CFG_DRIVER_ID_4 = 'driver_id_4'
    CFG_PARAM_PTR_4 = 'param_ptr_4'
    CFG_CO2_SETTINGS = 'co2_settings'
    CFG_SERIAL_SETTINGS = 'serial_settings'
        
class SamiConfigDataParticle(DataParticle):
    """
    Routines for parsing raw data into a data particle structure. Override
    the building of values, and the rest should come along for free.
    """
    _data_particle_type = DataParticleType.CONFIG_PARSED

    def _build_parsed_values(self):
        # Restore the first character we removed for recognition.
        # TODO: Improve logic to not rely on 1st character of "C"
        raw_data = "C" + self.raw_data
		return _sami_parse_config( raw_data )
		
	def _sami_parse_config(self, raw_data)
        regex1 = CONFIG_REGEX_MATCHER
        match = regex1.match(raw_data)
        if not match:
            raise SampleException("No regex match of parsed config data: [%s]" % raw_data)

        program_date = None
        start_time_offset = None
        recording_time = None
        mode = None
        timer_interval = []
        driver_id = []
        param_ptr = []
        co2_settings = None
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
          
        idx = 5
        device_group = []
        for i in range(5):
            txt = match.group(idx)
            timer_interval.append( int(txt,16) )

            txt = match.group(idx+1)
            driver_id.append( int(txt,16) )
            
            txt = match.group(idx+2)
            param_ptr.append( int(txt,16) )
            idx = idx + 3

        txt = match.group(idx)
        idx = idx + 1
        co2_settings = txt
    
        txt = match.group(idx)
        idx = idx + 1
        serial_settings = txt
    
        #  print("duration1: " + m0.group(idx) )
        #  idx = idx + 1    
        #  print("duration2: " + m0.group(idx) )
        # idx = idx + 1    
        # print("Meaningless parameter: " + m0.group(idx) )
        # idx = idx + 1
    
        result = [{DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_PROGRAM_DATE,
                   DataParticleKey.VALUE: program_date},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_START_TIME_OFFSET,
                   DataParticleKey.VALUE: start_time_offset},                  
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_RECORDING_TIME,
                   DataParticleKey.VALUE: recording_time},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_MODE,
                   DataParticleKey.VALUE: mode},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_TIMER_INTERVAL_0,
                   DataParticleKey.VALUE: timer_interval[0]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_DRIVER_ID_0,
                   DataParticleKey.VALUE: driver_id[0]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_PARAM_PTR_0,
                   DataParticleKey.VALUE: param_ptr[0]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_TIMER_INTERVAL_1,
                   DataParticleKey.VALUE: timer_interval[1]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_DRIVER_ID_1,
                   DataParticleKey.VALUE: driver_id[1]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_PARAM_PTR_1,
                   DataParticleKey.VALUE: param_ptr[1]},     
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_TIMER_INTERVAL_2,
                   DataParticleKey.VALUE: timer_interval[2]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_DRIVER_ID_2,
                   DataParticleKey.VALUE: driver_id[2]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_PARAM_PTR_2,
                   DataParticleKey.VALUE: param_ptr[2]},              
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_TIMER_INTERVAL_3,
                   DataParticleKey.VALUE: timer_interval[3]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_DRIVER_ID_3,
                   DataParticleKey.VALUE: driver_id[3]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_PARAM_PTR_3,
                   DataParticleKey.VALUE: param_ptr[3]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_TIMER_INTERVAL_4,
                   DataParticleKey.VALUE: timer_interval[4]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_DRIVER_ID_4,
                   DataParticleKey.VALUE: driver_id[4]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_PARAM_PTR_4,
                   DataParticleKey.VALUE: param_ptr[4]},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_CO2_SETTINGS,
                   DataParticleKey.VALUE: co2_settings},
                  {DataParticleKey.VALUE_ID: SamiConfigDataParticleKey.CFG_SERIAL_SETTINGS,
                   DataParticleKey.VALUE: serial_settings}]
        return result

class SamiStatusSwBusDataParticleKey(BaseEnum):
    PUMP_ON = "pump_on"
    VALVE_ON = "valve_on"
    EXTERNAL_POWER_ON = "external_power_on"
    DEBUG_LED_ON = "debug_led_on"
    DEBUG_ECHO_ON = "debug_echo_on"
    
class SamiStatusSwBusDataParticle(DataParticle):
    """
    Routines for parsing raw data into a data particle structure. Override
    the building of values, and the rest should come along for free.
    """
    _data_particle_type = DataParticleType.STATUS_SWBUS_PARSED

    def _build_parsed_values(self):
        """
        Take something in the autosample format and split it into
        values with appropriate tags
        @throws SampleException If there is a problem with sample creation
        """
       
        # Only 8-bits of information are returned.
        txt = self.raw_data[0:2]
        status_word = int(txt,16)
        
        pump_on = (status_word & 0x01) == 0x01
        valve_on = (status_word & 0x02) == 0x02
        external_power_on = (status_word & 0x04) == 0x04
        
        debug_led_on = (status_word & 0x10) == 0        
        debug_echo_on = (status_word & 0x20) == 0
        
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
    _data_particle_type = DataParticleType.STATUS_PARSED

    def _build_parsed_values(self):
        """
        Take something in the autosample format and split it into
        values with appropriate tags
        @throws SampleException If there is a problem with sample creation
        """
        regex1 = STATUS_REGEX_MATCHER

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

    def get_resource_params(self):
        """
        Return list of device parameters available.
        """
        return Parameter.list()

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
        self._protocol_fsm.add_handler(ProtocolState.UNKNOWN, ProtocolEvent.EXIT, self._handler_unknown_exit)
        self._protocol_fsm.add_handler(ProtocolState.UNKNOWN, ProtocolEvent.DISCOVER, self._handler_unknown_discover)
#        self._protocol_fsm.add_handler(ProtocolState.UNKNOWN, ProtocolEvent.START_DIRECT, self._handler_command_start_direct)

        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.ENTER, self._handler_command_enter)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.EXIT, self._handler_command_exit)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.ACQUIRE_SAMPLE, self._handler_command_acquire_sample)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.START_DIRECT, self._handler_command_start_direct)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.GET, self._handler_command_autosample_test_get)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.SET, self._handler_command_set)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.SET_CONFIGURATION, self._handler_command_set_configuration)

        self._protocol_fsm.add_handler(ProtocolState.DIRECT_ACCESS, ProtocolEvent.ENTER, self._handler_direct_access_enter)
        self._protocol_fsm.add_handler(ProtocolState.DIRECT_ACCESS, ProtocolEvent.EXIT, self._handler_direct_access_exit)
        self._protocol_fsm.add_handler(ProtocolState.DIRECT_ACCESS, ProtocolEvent.STOP_DIRECT, self._handler_direct_access_stop_direct)
        self._protocol_fsm.add_handler(ProtocolState.DIRECT_ACCESS, ProtocolEvent.EXECUTE_DIRECT, self._handler_direct_access_execute_direct)

        # Construct the parameter dictionary containing device parameters,
        # current parameter values, and set formatting functions.
        self._build_param_dict()

        # Add build handlers for device commands.
        self._add_build_handler(InstrumentCmds.DISPLAY_STATUS,      self._build_simple_command)
        self._add_build_handler(InstrumentCmds.READ_CONFIGURATION,  self._build_simple_command)
        self._add_build_handler(InstrumentCmds.READ_SAMPLE,         self._build_simple_command)
        self._add_build_handler(InstrumentCmds.SET_CONFIGURATION,   self._build_set_configuration_command)
        
        # Add response handlers for device commands.
        self._add_response_handler(InstrumentCmds.DISPLAY_STATUS,    self._parse_ds_response)
        self._add_response_handler(InstrumentCmds.READ_CONFIGURATION,self._parse_cfg_response)
        self._add_response_handler(InstrumentCmds.READ_SAMPLE,       self._parse_rs_response)

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
        sieve_matchers = [STATUS_REGEX_MATCHER,
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
        Build handler for basic sbe26plus commands.
        @param cmd the simple sbe37 command to format.
        @retval The command to be sent to the device.
        """
        return cmd + NEWLINE

    def _build_param_dict(self):
        """
        Populate the parameter dictionary with parameters.
        For each parameter key, add match stirng, match lambda function,
        and value formatting function for set commands.
        """
        # Add parameter handlers to parameter dict.

    def _got_chunk(self, chunk):
        """
        The base class got_data has gotten a chunk from the chunker.  Pass it to extract_sample
        with the appropriate particle objects and REGEXes.
        """
        if(self._extract_sample(SamiRecordDataParticle, RECORD_TYPE4_REGEX_MATCHER, chunk)):
            log.debug("_got_chunk of Record Data = Passed good")
        elif(self._extract_sample(SamiStatusDataParticle, STATUS_REGEX_MATCHER, chunk)):
            log.debug("_got_chunk of Status = Passed good")
        elif(self._extract_sample(SamiConfigDataParticle, CONFIG_REGEX_MATCHER, chunk)):
            log.debug("_got_chunk of Config = Passed good")
        else:
            log.debug("_got_chunk = Failed")

    def _do_cmd_resp(self, cmd, *args, **kwargs):
        """
        Perform a command-response on the device.
        @param cmd The command to execute.
        @param args positional arguments to pass to the build handler.
        @param timeout=timeout optional command timeout.
        @retval resp_result The (possibly parsed) response result.
        @raises InstrumentTimeoutException if the response did not occur in time.
        @raises InstrumentProtocolException if command could not be built or if response
        was not recognized.
        """
        
        # Get timeout and initialize response.
        timeout = kwargs.get('timeout', 30)
        expected_prompt = kwargs.get('expected_prompt', InstrumentPrompts.Z_ACK)
                            
        # Clear line and prompt buffers for result.
        self._linebuf = ''
        self._promptbuf = ''

        # Get the build handler.
        build_handler = self._build_handlers.get(cmd, None)
        if build_handler:
            cmd_line = build_handler(cmd, *args, **kwargs)
        else:
            cmd_line = cmd

        # Send command.
        log.debug('_do_cmd_resp: %s(%s), timeout=%s, expected_prompt=%s (%s),' 
                  % (repr(cmd_line), repr(cmd_line.encode("hex")), timeout, expected_prompt, expected_prompt.encode("hex")))
        self._connection.send(cmd_line)

        # Wait for the prompt, prepare result and return, timeout exception
        (prompt, result) = self._get_response(timeout,
                                              expected_prompt=expected_prompt)
        resp_handler = self._response_handlers.get((self.get_current_state(), cmd), None) or \
            self._response_handlers.get(cmd, None)
        resp_result = None
        if resp_handler:
            resp_result = resp_handler(result, prompt)
        
        return resp_result

    def _filter_capabilities(self, events):
        """
        Return a list of currently available capabilities.
        """
        events_out = [x for x in events if Capability.has(x)]
        return events_out

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
        self._driver_event(DriverAsyncEvent.STATE_CHANGE)

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
		timeout = kwargs.get('timeout', TIMEOUT)
        return (ProtocolState.COMMAND, ResourceAgentState.IDLE)

        return (next_state, result)

    def _handler_unknown_exit(self, *args, **kwargs):
        """
        Exit unknown state.
        """
        log.debug("Testing _handler_unknown_exit")
        pass

    def _handler_unknown_discover(self, *args, **kwargs):
        """
        Discover current state
        @retval (next_state, result)
        """
        log.debug("Testing _handler_unknown_discover")
        return (ProtocolState.COMMAND, ResourceAgentState.IDLE)

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
        next_state = None
        next_agent_state = None
        result = None

        result = self._do_cmd_resp(InstrumentCmds.ACQUIRE_DATA, *args, **kwargs)
        
        return (next_state, (next_agent_state, result))
        @throws SampleException if a sample could not be extracted from result.
        """

        next_state = None
        next_agent_state = None
        result = None

        kwargs['timeout'] = 30 # samples can take a long time

        log.debug("Testing _handler_command_acquire_sample")

        result = self._do_cmd_resp(InstrumentCmds.TAKE_SAMPLE, *args, **kwargs)

        return (next_state, (next_agent_state, result))

    def _handler_command_set_configuration(self, *args, **kwargs):
        """
        """
        next_state = None
        next_agent_state = None
        result = None

        log.debug("Testing _handler_command_set_configuration")
        
        kwargs['timeout'] = 30 # samples can take a long time

        result = self._do_cmd_resp(InstrumentCmds.SET_CONFIGURATION, *args, **kwargs)

        return (next_state, (next_agent_state, result))

    def _build_set_configuration_command(self, cmd, *args, **kwargs):
        user_configuration = kwargs.get('user_configuration', None)
        log.debug("Testing _build_set_configuration_command")
        if not user_configuration:
            raise InstrumentParameterException('set_configuration command missing user_configuration parameter.')
        if not isinstance(user_configuration, str):
            raise InstrumentParameterException('set_configuration command requires a string user_configuration parameter.')
        self._dump_config(user_configuration)        
            
        cmd_line = cmd + user_configuration
        return cmd_line

    ################################
    # SET / SETSAMPLING
    ################################

    def _handler_command_set(self, *args, **kwargs):
        """
        Set parameter
        """
        next_state = None
        result = None
        log.debug("Testing _handler_command_Set")

        return (next_state, result)

    def _handler_command_exit(self, *args, **kwargs):
        """
        Exit command state.
        """
        log.debug("Testing _handler_command_exit")
        pass

    def _handler_command_start_direct(self):
        """
        Start direct access
        """
        next_state = ProtocolState.DIRECT_ACCESS
        next_agent_state = ResourceAgentState.DIRECT_ACCESS
        result = None
        log.debug("_handler_command_start_direct: entering DA mode")
        return (next_state, (next_agent_state, result))

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

    def _build_simple_command(self, cmd):
        """
        Build handler for basic sbe26plus commands.
        @param cmd the simple sbe37 command to format.
        @retval The command to be sent to the device.
        """
        return cmd + NEWLINE

    def _build_param_dict(self):
        """
        Populate the parameter dictionary with our device parameters.
        For each parameter key, add match string, match lambda function,
        and value formatting function for set commands.

        """
        # Add parameter handlers to parameter dict.

        # DS (Device Status)
        cfg_line_01 = CONFIG_REGEX
        
        #
        # Next 2 work together to pull 2 values out of a single line.
        #      
        self._param_dict.add(Parameter.TIMESTAMP,
            cfg_line_01,
            lambda match : string.upper(match.group(1)),
            self._string_to_int,
            multi_match=True)

    def _parse_config_response(self, response, prompt):
        """
        Response handler for configuration "L" command
        """
        if prompt != Prompt.COMMAND:
            raise InstrumentProtocolException('cfg command not recognized: %s.' % response)

        # return the Ds as text
        match = CONFIG_REGEX_MATCHER.search(response)
        result = {} # None

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

    def _parse_rs_response(self, response, prompt):
        """
        Response handler for rs (Read Sample) command.
        @param response command response string.
        @param prompt prompt following command response.
        @retval sample dictionary containig c, t, d values.
        @throws InstrumentProtocolException if ts command misunderstood.
        @throws InstrumentSampleException if response did not contain a sample
        """

        if prompt != Prompt.COMMAND:
            raise InstrumentProtocolException('Command R not recognized: %s', response)

        result = response

        log.debug("_parse_ts_response RETURNING RESULT=" + str(result))
        return result
    
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
    

