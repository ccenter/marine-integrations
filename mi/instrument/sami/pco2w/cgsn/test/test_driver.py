"""
@package mi.instrument.sami.w.cgsn.test.test_driver
@file marine-integrations/mi/instrument/sami/w/cgsn/driver.py
@author Chris Center
@brief Test cases for InstrumentDriver

USAGE:
 Make tests verbose and provide stdout4
   * From the IDK
       $ bin/test_driver
       $ bin/test_driver -u [-t testname]
       $ bin/test_driver -i [-t testname]
       $ bin/test_driver -q [-t testname]

   * From pyon
       $ bin/nosetests -s -v .../mi/instrument/seabird/sbe16plus_v2/ooicore
       $ bin/nosetests -s -v .../mi/instrument/seabird/sbe16plus_v2/ooicore -a UNIT
       $ bin/nosetests -s -v .../mi/instrument/seabird/sbe16plus_v2/ooicore -a INT
       $ bin/nosetests -s -v .../mi/instrument/seabird/sbe16plus_v2/ooicore -a QUAL
"""

__author__ = 'Chris Center'
__license__ = 'Apache 2.0'

import unittest
import json

from nose.plugins.attrib import attr
from mock import Mock

from gevent import monkey; monkey.patch_all()
import gevent
import time
import re

from mi.core.common import BaseEnum
from mi.core.log import get_logger ; log = get_logger()
from nose.plugins.attrib import attr

# MI imports.
from mi.idk.unit_test import InstrumentDriverTestCase
from mi.idk.unit_test import InstrumentDriverUnitTestCase
from mi.idk.unit_test import InstrumentDriverIntegrationTestCase
from mi.idk.unit_test import InstrumentDriverQualificationTestCase
from mi.idk.unit_test import DriverTestMixin
from mi.idk.unit_test import ParameterTestConfigKey
from mi.idk.unit_test import AgentCapabilityType

from interface.objects import AgentCommand

from mi.core.instrument.logger_client import LoggerClient
from mi.core.instrument.port_agent_client import PortAgentPacket
from mi.core.instrument.chunker import StringChunker

from mi.core.instrument.instrument_driver import DriverAsyncEvent
from mi.core.instrument.instrument_driver import DriverConnectionState
from mi.core.instrument.instrument_driver import DriverProtocolState
from mi.core.instrument.instrument_driver import DriverParameter

from ion.agents.instrument.instrument_agent import InstrumentAgentState
from ion.agents.instrument.direct_access.direct_access_server import DirectAccessTypes

from mi.instrument.sami.pco2w.cgsn.driver import InstrumentDriver
from mi.instrument.sami.pco2w.cgsn.driver import DataParticleType
from mi.instrument.sami.pco2w.cgsn.driver import ProtocolState
from mi.instrument.sami.pco2w.cgsn.driver import ProtocolEvent
from mi.instrument.sami.pco2w.cgsn.driver import ScheduledJob
from mi.instrument.sami.pco2w.cgsn.driver import Capability
from mi.instrument.sami.pco2w.cgsn.driver import Parameter
from mi.instrument.sami.pco2w.cgsn.driver import Prompt
from mi.instrument.sami.pco2w.cgsn.driver import Protocol
from mi.instrument.sami.pco2w.cgsn.driver import NEWLINE
from mi.instrument.sami.pco2w.cgsn.driver import InstrumentCmds
from mi.instrument.sami.pco2w.cgsn.driver import get_timestamp_delayed_sec  # Modifid 

# Data Particles
from mi.instrument.sami.pco2w.cgsn.driver import SamiImmediateStatusDataParticle
from mi.instrument.sami.pco2w.cgsn.driver import SamiImmediateStatusDataParticleKey
from mi.instrument.sami.pco2w.cgsn.driver import SamiDataRecordParticle
from mi.instrument.sami.pco2w.cgsn.driver import SamiDataRecordParticleKey
from mi.instrument.sami.pco2w.cgsn.driver import SamiStatusDataParticle
from mi.instrument.sami.pco2w.cgsn.driver import SamiStatusDataParticleKey
from mi.instrument.sami.pco2w.cgsn.driver import SamiConfigDataParticle
from mi.instrument.sami.pco2w.cgsn.driver import SamiConfigDataParticleKey

from mi.core.exceptions import InstrumentProtocolException
from mi.core.exceptions import InstrumentDataException
from mi.core.exceptions import InstrumentCommandException
from mi.core.exceptions import InstrumentStateException
from mi.core.exceptions import InstrumentParameterException

from mi.core.instrument.data_particle import DataParticleKey, DataParticleValue

###
#   Driver parameters for the tests
###
# Create some short names for the parameter test config
STARTUP = ParameterTestConfigKey.STARTUP

# SAMI Test Strings
SAMPLE_IMMEDIATE_STATUS_DATA = "10"
SAMPLE_ERROR_DATA = "?03" + NEWLINE
# This records is from the PCO2W_Record_Format.pdf file.
SAMPLE_DATA_RECORD_1  = "*5B2704C8EF9FC90FE606400FE8063C0FE30674640B1B1F0FE6065A0FE9067F0FE306A60CDE0FFF3B"
SAMPLE_DATA_RECORD_2  = "*7E2705CBACEE7F007D007D0B2A00BF080500E00187034A008200790B2D00BE080600DE0C1406C98C"
SAMPLE_CONTROL_RECORD = "*5B2780C8EF9FC90FE606400FE8063C0FE30674640B1B1F0FE6065A0FE9067F0FE306A60CDE0FFF3B"

# Regular Status.
#SAMPLE_DEVICE_STATUS_DATA = ":000029ED40"  + NEWLINE
SAMPLE_DEVICE_STATUS_DATA = ":003F91BE00000000" # :003F91BE0000000000000000000000F7" + NEWLINE
SAMPLE_DEVICE_STATUS_DATA_BAD = "000029ED40"  + NEWLINE
# SAMPLE_CONFIG_DATA = "CAB39E84000000F401E13380570007080401000258030A0002580017000258011A003840001C1020FFA8181C010038100101202564000433383335000200010200020000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000" + NEWLINE
# This sample configuration is from the PCO2W_Low_Level_SAMI_Use document.
SAMPLE_CONFIG_DATA_1 = "CAB39E84000000F401E13380570007080401000258030A0002580017000258011A003840001C071020FFA8181C010038100101202564000433383335000200010200000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"


# Other actual data captures of Sami Status Data.
# :000EDCAE0000000000000000000000F70000F7
# :000EDCB30000000000000000000000F70000F7
# :000EDCB80000000000000000000000F70000F7
# :000EDCBD0000000000000000000000F70000F7
# :000EDCC20000000000000000000000F70000F7
# :000EDCC70000000000000000000000F70000F7
# :000EDCCC0000000000000000000000F70000F7
# :000EDCD10000000000000000000000F70000F7
# :000EDCD60000000000000000000000F70000F7

InstrumentDriverTestCase.initialize(
    driver_module='mi.instrument.sami.pco2w.cgsn.driver',
    driver_class="InstrumentDriver",

    instrument_agent_resource_id = 'E3SIRI',
    instrument_agent_name = 'sami_pco2w_cgsn',
    instrument_agent_packet_config = DataParticleType(),

    driver_startup_config = {}
)

#################################### RULES ####################################
#                                                                             #
# Common capabilities in the base class                                       #
#                                                                             #
# Instrument specific stuff in the derived class                              #
#                                                                             #
# Generator spits out either stubs or comments describing test this here,     #
# test that there.                                                            #
#                                                                             #
# Qualification tests are driven through the instrument_agent                 #
#                                                                             #
###############################################################################

###
#   Driver constant definitions
###

###############################################################################
#                           DATA PARTICLE TEST MIXIN                          #
#     Defines a set of assert methods used for data particle verification     #
#                                                                             #
#  In python mixin classes are classes designed such that they wouldn't be    #
#  able to stand on their own, but are inherited by other classes generally   #
#  using multiple inheritance.                                                #
#                                                                             #
# This class defines a configuration structure for testing and common assert  #
# methods for validating data particles.
###############################################################################
class DataParticleMixin(DriverTestMixin):
    '''
    Mixin class used for storing data particle constance and common data assertion methods.
    '''
    # Create some short names for the parameter test config
    TYPE      = ParameterTestConfigKey.TYPE
    READONLY  = ParameterTestConfigKey.READONLY
    STARTUP   = ParameterTestConfigKey.STARTUP
    DA        = ParameterTestConfigKey.DIRECT_ACCESS
    VALUE     = ParameterTestConfigKey.VALUE
    REQUIRED  = ParameterTestConfigKey.REQUIRED
    DEFAULT   = ParameterTestConfigKey.DEFAULT
    ###
    #  Parameter and Type Definitions
    ##
    _driver_parameters = {
        # parameters - contains all setsampling parameters
        Parameter.PUMP_PULSE :                  { TYPE: int, READONLY: True , DA: False, DEFAULT: 16,   VALUE: 1, REQUIRED: True },
        Parameter.PUMP_ON_TO_MEASURE :          { TYPE: int, READONLY: True , DA: False, DEFAULT: 32,   VALUE: 32, REQUIRED: True },
        Parameter.NUM_SAMPLES_PER_MEASURE :     { TYPE: int, READONLY: True , DA: False, DEFAULT: 255,  VALUE: 3, REQUIRED: True },
        Parameter.NUM_CYCLES_BETWEEN_BLANKS:    { TYPE: int, READONLY: False, DA: True,  DEFAULT: 168,  VALUE: 4, REQUIRED: True },
        Parameter.NUM_REAGENT_CYCLES :          { TYPE: int, READONLY: True , DA: False, DEFAULT: 24,   VALUE: 5, REQUIRED: True },
        Parameter.NUM_BLANK_CYCLES :            { TYPE: int, READONLY: True , DA: False, DEFAULT: 28,   VALUE: 6, REQUIRED: True },
        Parameter.FLUSH_PUMP_INTERVAL_SEC :     { TYPE: int, READONLY: True , DA: False, DEFAULT: 1,    VALUE: 7, REQUIRED: True },
        Parameter.STARTUP_BLANK_FLUSH_ENABLE:   { TYPE: bool,READONLY: False, DA: True,  DEFAULT: False,VALUE: False, REQUIRED: True },
        Parameter.PUMP_PULSE_POST_MEASURE_ENABLE:{TYPE: bool,READONLY: True , DA: True,  DEFAULT: False,VALUE: False, REQUIRED: True },
        Parameter.NUM_EXTRA_PUMP_CYCLES :       { TYPE: int, READONLY: True , DA: True,  DEFAULT: 56,   VALUE: 8, REQUIRED: True },
        Parameter.DEVICE_DATE_TIME :            { TYPE: int, READONLY: True , DA: True,  DEFAULT:0xCAB39E84, VALUE:0xCAB39E84, REQUIRED: True}
    }

    # Test results that get decoded from the string sent to the chunker.
    _data_record_parameters = {   
        SamiDataRecordParticleKey.UNIQUE_ID:        { TYPE: int, READONLY: False, DA: False, DEFAULT: 0x0, VALUE: 91, REQUIRED: True},
        SamiDataRecordParticleKey.RECORD_LENGTH:    { TYPE: int, READONLY: False, DA: False, DEFAULT: 0x0, VALUE: 39, REQUIRED: True},
        SamiDataRecordParticleKey.RECORD_TYPE:      { TYPE: int, READONLY: False, DA: False, DEFAULT: 0x0, VALUE: 4,  REQUIRED: True},
        SamiDataRecordParticleKey.RECORD_TIME:      { TYPE: int, READONLY: False, DA: False, DEFAULT: 0x0, VALUE: 0xC8EF9FC9, REQUIRED: True},
        SamiDataRecordParticleKey.VOLTAGE_BATTERY:  { TYPE: int, READONLY: False, DA: False, DEFAULT: 0x0, VALUE: 205, REQUIRED: True },
        SamiDataRecordParticleKey.THERMISTER_RAW:   { TYPE: int, READONLY: False, DA: False, DEFAULT: 0x0, VALUE: 255, REQUIRED: True },
        SamiDataRecordParticleKey.CHECKSUM:         { TYPE: int, READONLY: False, DA: False, DEFAULT: 0x0, VALUE: 0x3B, REQUIRED: True},
        SamiDataRecordParticleKey.LIGHT_MEASUREMENT:{ TYPE: list,READONLY: False, DA: False }
    }
    
    _control_record_parameters = {   
        SamiDataRecordParticleKey.UNIQUE_ID:        { TYPE: int, READONLY: False, DA: False, DEFAULT: 0x0, VALUE: 91, REQUIRED: True},
        SamiDataRecordParticleKey.RECORD_LENGTH:    { TYPE: int, READONLY: False, DA: False, DEFAULT: 0x0, VALUE: 39, REQUIRED: True},
        SamiDataRecordParticleKey.RECORD_TYPE:      { TYPE: int, READONLY: False, DA: False, DEFAULT: 0x0, VALUE: 0x80,  REQUIRED: True},
        SamiDataRecordParticleKey.RECORD_TIME:      { TYPE: int, READONLY: False, DA: False, DEFAULT: 0x0, VALUE: 0xC8EF9FC9, REQUIRED: True},
        SamiDataRecordParticleKey.CHECKSUM:         { TYPE: int, READONLY: False, DA: False, DEFAULT: 0x0, VALUE: 0x3B, REQUIRED: True},
    }
   
    # Test results that get decoded from the string sent to the chunker.
    _device_status_parameters = {
        SamiStatusDataParticleKey.TIME_OFFSET:          { TYPE: int,  VALUE: 0x3F91BE, REQUIRED: True},  # 48 5:14:38
        SamiStatusDataParticleKey.CLOCK_ACTIVE:         { TYPE: bool, VALUE: False, REQUIRED: True},
        SamiStatusDataParticleKey.RECORDING_ACTIVE:     { TYPE: bool, VALUE: False, REQUIRED: True },
        SamiStatusDataParticleKey.RECORD_END_ON_TIME:   { TYPE: bool, VALUE: False, REQUIRED: True },
        SamiStatusDataParticleKey.RECORD_MEMORY_FULL:   { TYPE: bool, VALUE: False, REQUIRED: True },
        SamiStatusDataParticleKey.RECORD_END_ON_ERROR:  { TYPE: bool, VALUE: False, REQUIRED: True },
        SamiStatusDataParticleKey.DATA_DOWNLOAD_OK:     { TYPE: bool, VALUE: False, REQUIRED: True },
        SamiStatusDataParticleKey.FLASH_MEMORY_OPEN:    { TYPE: bool, VALUE: False, REQUIRED: True },
        SamiStatusDataParticleKey.BATTERY_FATAL_ERROR:  { TYPE: bool, VALUE: False, REQUIRED: True },
        SamiStatusDataParticleKey.BATTERY_LOW_MEASUREMENT:{TYPE:bool, VALUE: False, REQUIRED: True },
        SamiStatusDataParticleKey.BATTERY_LOW_BANK:     { TYPE: bool, VALUE: False, REQUIRED: True },
        SamiStatusDataParticleKey.BATTERY_LOW_EXTERNAL: { TYPE: bool, VALUE: False, REQUIRED: True },
        SamiStatusDataParticleKey.EXTERNAL_DEVICE_FAULT:{ TYPE: int,  VALUE: 0x0,   REQUIRED: True },
        SamiStatusDataParticleKey.FLASH_ERASED:         { TYPE: bool, VALUE: False, REQUIRED: True },
        SamiStatusDataParticleKey.POWER_ON_INVALID:     { TYPE: bool, VALUE: False, REQUIRED: True }
    }
    
    # Test for Immediate Status.
    _immediate_status_parameters = {
        SamiImmediateStatusDataParticleKey.PUMP_ON:          { TYPE: bool, VALUE: True , REQUIRED: True },
        SamiImmediateStatusDataParticleKey.VALVE_ON:         { TYPE: bool, VALUE: False, REQUIRED: True },      
        SamiImmediateStatusDataParticleKey.EXTERNAL_POWER_ON:{ TYPE: bool, VALUE: False, REQUIRED: True },
        SamiImmediateStatusDataParticleKey.DEBUG_LED_ON:     { TYPE: bool, VALUE: False, REQUIRED: True },
        SamiImmediateStatusDataParticleKey.DEBUG_ECHO_ON:    { TYPE: bool, VALUE: False, REQUIRED: True }
    }
   
    # Test Results that get decoded from the Configuration
    _config_parameters = {
        SamiConfigDataParticleKey.PROGRAM_DATE_TIME:{ TYPE: int, VALUE: 0xCAB39E84, REQUIRED: True}, # 3400769156 = 0xCAB39E84
        SamiConfigDataParticleKey.START_TIME_OFFSET:{ TYPE: int, VALUE: 244, REQUIRED: True},
        SamiConfigDataParticleKey.RECORDING_TIME:   { TYPE: int, VALUE: 31536000, REQUIRED: True},
        
        SamiConfigDataParticleKey.PMI_SAMPLE_SCHEDULE         : { TYPE: bool, VALUE: True,  REQUIRED: True },
        SamiConfigDataParticleKey.SAMI_SAMPLE_SCHEDULE        : { TYPE: bool, VALUE: True,  REQUIRED: True },
        SamiConfigDataParticleKey.SLOT1_FOLLOWS_SAMI_SCHEDULE : { TYPE: bool, VALUE: True,  REQUIRED: True },
        SamiConfigDataParticleKey.SLOT1_INDEPENDENT_SCHEDULE  : { TYPE: bool, VALUE: False, REQUIRED: True },
        SamiConfigDataParticleKey.SLOT2_FOLLOWS_SAMI_SCHEDULE : { TYPE: bool, VALUE: True,  REQUIRED: True },
        SamiConfigDataParticleKey.SLOT2_INDEPENDENT_SCHEDULE  : { TYPE: bool, VALUE: False, REQUIRED: True },
        SamiConfigDataParticleKey.SLOT3_FOLLOWS_SAMI_SCHEDULE : { TYPE: bool, VALUE: True,  REQUIRED: True },
        SamiConfigDataParticleKey.SLOT3_INDEPENDENT_SCHEDULE  : { TYPE: bool, VALUE: False, REQUIRED: True },

        SamiConfigDataParticleKey.TIMER_INTERVAL_SAMI:{ TYPE: int, VALUE: 1800, REQUIRED: True },
        SamiConfigDataParticleKey.DRIVER_ID_SAMI:     { TYPE: int, VALUE: 4,  REQUIRED: True },
        SamiConfigDataParticleKey.PARAM_PTR_SAMI:     { TYPE: int, VALUE: 1,  REQUIRED: True },
        SamiConfigDataParticleKey.TIMER_INTERVAL_1:   { TYPE: int, VALUE: 600,REQUIRED: True },
        SamiConfigDataParticleKey.DRIVER_ID_1:        { TYPE: int, VALUE: 3,  REQUIRED: True },
        SamiConfigDataParticleKey.PARAM_PTR_1:        { TYPE: int, VALUE: 10, REQUIRED: True },
        SamiConfigDataParticleKey.TIMER_INTERVAL_2:   { TYPE: int, VALUE: 600,REQUIRED: True },
        SamiConfigDataParticleKey.DRIVER_ID_2:        { TYPE: int, VALUE: 0,  REQUIRED: True },
        SamiConfigDataParticleKey.PARAM_PTR_2:        { TYPE: int, VALUE: 23, REQUIRED: True },    
        SamiConfigDataParticleKey.TIMER_INTERVAL_3:   { TYPE: int, VALUE: 600,REQUIRED: True },
        SamiConfigDataParticleKey.DRIVER_ID_3:        { TYPE: int, VALUE: 1,  REQUIRED: True },
        SamiConfigDataParticleKey.PARAM_PTR_3:        { TYPE: int, VALUE: 26, REQUIRED: True },
        SamiConfigDataParticleKey.TIMER_INTERVAL_PRESTART: { TYPE: int, VALUE: 14400, REQUIRED: True },
        SamiConfigDataParticleKey.DRIVER_ID_PRESTART: { TYPE: int, VALUE: 0, REQUIRED: True },
        SamiConfigDataParticleKey.PARAM_PTR_PRESTART: { TYPE: int, VALUE: 28, REQUIRED: True },
        
        SamiConfigDataParticleKey.USE_BAUD_RATE_57600:    { TYPE: bool, VALUE: True, REQUIRED: True },
        SamiConfigDataParticleKey.SEND_RECORD_TYPE_EARLY: { TYPE: bool, VALUE: True, REQUIRED: True },
        SamiConfigDataParticleKey.SEND_LIVE_RECORDS:      { TYPE: bool, VALUE: True, REQUIRED: True },
        
        SamiConfigDataParticleKey.PUMP_PULSE:             { TYPE: int, VALUE: 0x10, REQUIRED: True },
        SamiConfigDataParticleKey.PUMP_ON_TO_MEAURSURE:   { TYPE: int, VALUE: 0x20, REQUIRED: True },
        SamiConfigDataParticleKey.SAMPLES_PER_MEASURE:    { TYPE: int, VALUE: 0xFF, REQUIRED: True },
        SamiConfigDataParticleKey.CYCLES_BETWEEN_BLANKS:  { TYPE: int, VALUE: 0xA8, REQUIRED: True },
        SamiConfigDataParticleKey.NUM_REAGENT_CYCLES:     { TYPE: int, VALUE: 0x18, REQUIRED: True },
        SamiConfigDataParticleKey.NUM_BLANK_CYCLES:       { TYPE: int, VALUE: 0x1C, REQUIRED: True },
        SamiConfigDataParticleKey.FLUSH_PUMP_INTERVAL:    { TYPE: int, VALUE: 0x1,  REQUIRED: True },
        SamiConfigDataParticleKey.BLANK_FLUSH_ON_START_ENABLE:   { TYPE: bool, VALUE: True, REQUIRED: True },
        SamiConfigDataParticleKey.PUMP_PULSE_POST_MEASURE:{ TYPE: bool, VALUE: False, REQUIRED: True },
        SamiConfigDataParticleKey.CYCLE_DATA:             { TYPE: int,  VALUE: 0x38, REQUIRED: True },                         
        SamiConfigDataParticleKey.SERIAL_SETTINGS:        { TYPE: unicode, VALUE: u'10010120256400043338333500', REQUIRED: True }
    }
    
    ###
    #   Driver Parameter Methods
    ###
    def assert_driver_parameters(self, current_parameters, verify_values = False):
        """
        Verify that all driver parameters are correct and potentially verify values.
        @param current_parameters: driver parameters read from the driver instance
        @param verify_values: should we verify values against definition?
        """
        self.assert_parameters(current_parameters, self._driver_parameters, verify_values)

    ###
    def assert_sample_data_particle(self, data_particle):
        '''
        Verify a particle is a know particle to this driver and verify the particle is
        correct
        @param data_particle: Data particle of unkown type produced by the driver
        '''
        if (isinstance(data_particle, SamiDataRecordParticle)):
            self.assert_particle_data_record(data_particle)
            
        elif (isinstance(data_particle, SamiStatusDataParticle)):
            self.assert_particle_device_status(data_particle)
        
        elif (isinstance(data_particle, SamiConfigDataParticle)):
            self.assert_particle_config_status(data_particle)
           
        else:
            log.error("Unknown Particle Detected: %s" % data_particle)
            self.assertFalse(True)

    def assert_particle_configuration(self, data_particle, verify_values = False):
        '''
        Verify a take sample data particle
        @param data_particle:  SamiConfigDataParticle data particle
        @param verify_values:  bool, should we verify parameter values
        '''
        self.assert_data_particle_header(data_particle, DataParticleType.CONFIG_PARSED)
        self.assert_data_particle_parameters(data_particle, self._config_parameters, verify_values)
        
    def assert_particle_device_status(self, data_particle, verify_values = False):
        '''
        Verify a take sample data particle
        @param data_particle:  SamiStatusDataParticle data particle
        @param verify_values:  bool, should we verify parameter values
        '''
        self.assert_data_particle_header(data_particle, DataParticleType.DEVICE_STATUS_PARSED)
        self.assert_data_particle_parameters(data_particle, self._device_status_parameters, verify_values)

    def assert_particle_immediate_status(self, data_particle, verify_values = False):
        '''
        Immediate Read Status SW & BUS response.
        '''
        self.assert_data_particle_header(data_particle, DataParticleType.IMMEDIATE_STATUS_PARSED)
        self.assert_data_particle_parameters(data_particle, self._immediate_status_parameters, verify_values)
        
    def assert_particle_data_record(self, data_particle, verify_values = False):
        '''
        Verify a take sample data particle
        @param data_particle:  SamiDataRecordParticle data particle
        @param verify_values:  bool, should we verify parameter values
        '''
        self.assert_data_particle_header(data_particle, DataParticleType.DATA_RECORD_PARSED)
        self.assert_data_particle_parameters(data_particle, self._data_record_parameters, verify_values)

###############################################################################
#                                UNIT TESTS                                   #
#         Unit tests test the method calls and parameters using Mock.         #
#                                                                             #
#   These tests are especially useful for testing parsers and other data      #
#   handling.  The tests generally focus on small segments of code, like a    #
#   single function call, but more complex code using Mock objects.  However  #
#   if you find yourself mocking too much maybe it is better as an            #
#   integration test.                                                         #
#                                                                             #
#   Unit tests do not start up external processes like the port agent or      #
#   driver process.                                                           #
###############################################################################
@attr('UNIT', group='mi')
class SamiUnitTest(InstrumentDriverUnitTestCase, DataParticleMixin):
    """Unit Test Container"""
    
    ###
    #    This is the callback that would normally publish events 
    #    (streams, state transitions, etc.).
    #    Use this method to test for existence of events and to examine their
    #    attributes for correctness.
    ###
    
    def reset_test_vars(self):    
        self.raw_stream_received = False
        self.parsed_stream_received = False

    def mock_event_callback(self, event):
        event_type = event['type']
        print str(event)
        
        if event_type == DriverAsyncEvent.SAMPLE:
            sample_value = event['value']
            log.debug("event_type == SAMPLE")
            particle_dict = json.loads(sample_value)
            stream_type = particle_dict['stream_name']        
            if stream_type == 'raw':
                log.debug("raw_stream received")
                self.raw_stream_received = True
            elif stream_type == 'parsed':
                log.debug("rstream type == parsed")
                self.parsed_stream_received = True

    def test_driver_enums(self):
        """
        Verify that all driver enumeration has no duplicate values that might cause confusion.  Also
        do a little extra validation for the Capabilites
        """
        self.assert_enum_has_no_duplicates(ScheduledJob())
        self.assert_enum_has_no_duplicates(DataParticleType())
        self.assert_enum_has_no_duplicates(InstrumentCmds())
        self.assert_enum_has_no_duplicates(ProtocolState())
        self.assert_enum_has_no_duplicates(ProtocolEvent())
        self.assert_enum_has_no_duplicates(Parameter())

        # Test capabilites for duplicates, them verify that capabilities is a subset of proto events
        self.assert_enum_has_no_duplicates(Capability())
        self.assert_enum_complete(Capability(), ProtocolEvent())


    def test_chunker(self):
        """
        Test the chunker and verify the particles created.
        """
        chunker = StringChunker(Protocol.sieve_function)

        test_data = SAMPLE_DATA_RECORD_1      
        self.assert_chunker_sample(chunker, test_data)
        self.assert_chunker_sample_with_noise(chunker, test_data)
        self.assert_chunker_fragmented_sample(chunker, test_data)
        self.assert_chunker_combined_sample(chunker, test_data)

        test_data = SAMPLE_CONFIG_DATA_1      
        self.assert_chunker_sample(chunker, test_data)
        self.assert_chunker_sample_with_noise(chunker, test_data)
        self.assert_chunker_fragmented_sample(chunker, test_data)
        self.assert_chunker_combined_sample(chunker, test_data)
        
        test_data = SAMPLE_DEVICE_STATUS_DATA      
        self.assert_chunker_sample(chunker, test_data)
        self.assert_chunker_sample_with_noise(chunker, test_data)
        self.assert_chunker_fragmented_sample(chunker, test_data)
        self.assert_chunker_combined_sample(chunker, test_data)
        
    def test_got_data(self):
        """
        Verify sample data passed through the got data method produces the correct data particles
        """
        # Create and initialize the instrument driver with a mock port agent
        driver = InstrumentDriver(self._got_data_event_callback)
        self.assert_initialize_driver(driver)
        self.assert_raw_particle_published(driver, True)

        # Start validating data particles
        self.assert_particle_published(driver, SAMPLE_DEVICE_STATUS_DATA, self.assert_particle_device_status, True)  # Regular Status
        self.assert_particle_published(driver, SAMPLE_DATA_RECORD_1, self.assert_particle_data_record, True)          # Data Record.
        self.assert_particle_published(driver, SAMPLE_CONFIG_DATA_1, self.assert_particle_configuration, True)
        
        # Note: The Immediate Status Particle is a command response!
        # self.assert_particle_published(driver, SAMPLE_IMMEDIATE_STATUS_DATA, self.assert_particle_immediate_status, True)

    def test_protocol_filter_capabilities(self):
        """
        This tests driver filter_capabilities.
        Iterate through available capabilities, and verify that they can pass successfully through the filter.
        Test silly made up capabilities to verify they are blocked by filter.
        """
        mock_callback = Mock()
        protocol = Protocol(Prompt, NEWLINE, mock_callback)
        driver_capabilities = Capability().list()
        test_capabilities = Capability().list()

        # Add a bogus capability that will be filtered out.
        test_capabilities.append("BOGUS_CAPABILITY")

        # Verify "BOGUS_CAPABILITY was filtered out
        self.assertEquals(sorted(driver_capabilities),
                          sorted(protocol._filter_capabilities(test_capabilities)))
        
    def test_driver_parameters(self):
        """
        Verify the set of parameters known by the driver
        """
        driver = InstrumentDriver(self._got_data_event_callback)
        self.assert_initialize_driver(driver, ProtocolState.COMMAND)

        my_parameters = sorted(driver.get_resource(Parameter.ALL))
        log.debug("my parameters: %s" % my_parameters)

        expected_parameters = sorted(self._driver_parameters.keys())
        reported_parameters = sorted(driver.get_resource(Parameter.ALL))
        
        log.debug("Reported Parameters: %s" % reported_parameters)
        log.debug("Expected Parameters: %s" % expected_parameters)
        self.assertEqual(reported_parameters, expected_parameters)

        # Verify the parameter definitions
        self.assert_driver_parameter_definition(driver, self._driver_parameters)

    def test_capabilities(self):
        """
        Verify the FSM reports capabilities as expected.  All states defined in this dict must
        also be defined in the protocol FSM.
        """    

        capabilities = {
            ProtocolState.UNKNOWN: ['DRIVER_EVENT_DISCOVER'],
            ProtocolState.COMMAND: ['DRIVER_EVENT_GET',
                                    'DRIVER_EVENT_SET',
                                    'DRIVER_EVENT_START_AUTOSAMPLE',
                                    'DRIVER_EVENT_ACQUIRE_SAMPLE',
                                    'DRIVER_EVENT_ACQUIRE_STATUS',
                                    'DRIVER_EVENT_CLOCK_SYNC',
                                    'PROTOCOL_EVENT_ACQUIRE_CONFIGURATION',
                                    'PROTOCOL_EVENT_SCHEDULED_CLOCK_SYNC'],
            ProtocolState.AUTOSAMPLE: ['DRIVER_EVENT_ACQUIRE_STATUS','DRIVER_EVENT_STOP_AUTOSAMPLE','PROTOCOL_EVENT_SCHEDULED_CLOCK_SYNC']
        }

        driver = InstrumentDriver(self._got_data_event_callback)
        self.assert_capabilities(driver, capabilities)
   
    def test_complete_sample(self):
        temp_driver = InstrumentDriver(self._got_data_event_callback)
        self.assert_initialize_driver(temp_driver)
        
        """
        Force the driver into AUTOSAMPLE state so that it will parse and 
        publish samples
        """        
        temp_driver.set_test_mode(True)
#        temp_driver.test_force_state(state = DriverProtocolState.AUTOSAMPLE)
#        current_state = temp_driver.get_resource_state()
#        self.assertEqual(current_state, DriverProtocolState.AUTOSAMPLE)
        
        self.reset_test_vars()
        packet = PortAgentPacket()
        packet.attach_data(SAMPLE_DATA_RECORD_1) 
        temp_driver._protocol.got_data(packet)        
        self.assertFalse(self.raw_stream_received)
        self.assertFalse(self.parsed_stream_received)
        
###############################################################################
#                            INTEGRATION TESTS                                #
#     Integration test test the direct driver / instrument interaction        #
#     but making direct calls via zeromq.                                     #
#     - Common Integration tests test the driver through the instrument agent #
#     and common for all drivers (minimum requirement for ION ingestion)      #
###############################################################################
@attr('INT', group='mi')
class SamiIntegrationTest(InstrumentDriverIntegrationTestCase, DriverTestMixin):
    def setUp(self):
        InstrumentDriverIntegrationTestCase.setUp(self)

    def check_state(self, expected_state):
        state = self.driver_client.cmd_dvr('get_resource_state')
        self.assertEqual(state, expected_state)
        
    ###
    #    Add instrument specific integration tests
    ###

    def assert_param_dict(self, pd, all_params=False):
        """
        Verify all device parameters exist and are correct type.
        """

        # Make it loop through once to warn with debugging of issues, 2nd time can send the exception
        # PARAMS is the master type list

        if all_params:
            log.debug("DICT 1 *********" + str(pd.keys()))
            log.debug("DICT 2 *********" + str(PARAMS.keys()))
            self.assertEqual(set(pd.keys()), set(PARAMS.keys()))

            for (key, type_val) in PARAMS.iteritems():
                self.assertTrue(isinstance(pd[key], type_val))
        else:
            for (key, val) in pd.iteritems():
                self.assertTrue(PARAMS.has_key(key))

                if val is not None: # If its not defined, lets just skip it, only catch wrong type assignments.
                    log.debug("Asserting that " + key +  " is of type " + str(PARAMS[key]))
                    self.assertTrue(isinstance(val, PARAMS[key]))
                else:
                    log.debug("*** Skipping " + key + " Because value is None ***")

    def put_instrument_in_command_mode(self):
        """Wrap the steps and asserts for going into command mode.
           May be used in multiple test cases.
        """
        # Test that the driver is in state unconfigured.
        self.check_state(DriverConnectionState.UNCONFIGURED)

        # Configure driver and transition to disconnected.
        self.driver_client.cmd_dvr('configure', self.port_agent_comm_config())

        # Test that the driver is in state disconnected.
        self.check_state(DriverConnectionState.DISCONNECTED)

        # Setup the protocol state machine and the connection to port agent.
        self.driver_client.cmd_dvr('connect')

        # Test that the driver protocol is in state unknown.
        self.check_state(ProtocolState.UNKNOWN)

        # Discover what state the instrument is in and set the protocol state accordingly.
        self.driver_client.cmd_dvr('discover_state')

        # Test that the driver protocol is in state command.
        self.check_state(ProtocolState.COMMAND)
        
    def test_startup_configuration(self):
        '''
        Test that the startup configuration is applied correctly
        '''
        self.put_instrument_in_command_mode()

        result = self.driver_client.cmd_dvr('apply_startup_params')

        reply = self.driver_client.cmd_dvr('get_resource', [Parameter.PUMP_PULSE])

        self.assertEquals(reply, {Parameter.PUMP_PULSE: 16})

        params = {
            Parameter.PUMP_PULSE : 16
#            Parameter.TXWAVESTATS : False,
#            Parameter.USER_INFO : "KILROY WAZ HERE"
        }
        reply = self.driver_client.cmd_dvr('set_resource', params)
        self.assertEqual(reply, None)
        
    def test_parameters(self):
        """
        Test driver parameters and verify their type.  Startup parameters also verify the parameter
        value.  This test confirms that parameters are being read/converted properly and that
        the startup has been applied.
        """
        self.assert_initialize_driver()
        reply = self.driver_client.cmd_dvr('get_resource', Parameter.ALL)
        # CJC: Cannot find this. self.assert_driver_parameters(reply, True)
    
    def test_set(self):       
        self.put_instrument_in_command_mode()
        
        new_params = {
           Parameter.PUMP_PULSE: 0xEE
        }
       
        reply = self.driver_client.cmd_dvr('set_resource', new_params)
        self.assertEquals(reply, new_params)
                 
        reply = self.driver_client.cmd_dvr('get_resource', new_params, timeout=20)
        self.assertEquals(reply, new_params)
        
        
    def test_set_broken(self):
        """
        Test all set commands. Verify all exception cases.
        """
        self.assert_initialize_driver()   
        self.assert_set(Parameter.PUMP_PULSE, 0x00)
        self.assert_get(Parameter.PUMP_PULSE, 0x16)

    def test_get(self):        
        self.put_instrument_in_command_mode()

        new_params = {
                   Parameter.PUMP_PULSE: 0xFF,
                   Parameter.PUMP_ON_TO_MEASURE: 0xEE
        }
        
        reply = self.driver_client.cmd_dvr('set_resource', new_params)
        self.assertEquals(reply, new_params)

        # Retrieve all of the parameters.
        '''
        reply = self.driver_client.cmd_dvr('get_resource', Parameter.ALL)
        self.assert_param_dict(reply)
        '''
        
        '''
        CJC: DO we need to add these ???
        self.assertRaises(InstrumentCommandException,
                          self.driver_client.cmd_dvr,
                          'bogus', [Parameter.PUMP_PULSE])

        # Assert get fails without a paramet
        self.assertRaises(InstrumentParameterException,
                          self.driver_client.cmd_dvr, 'get_resource')
                    
        # Assert get fails with a bad parameter in a list).
        with self.assertRaises(InstrumentParameterException):
            bogus_params = [
                'a bogus parameter name',
                Parameter.PUMP_PULSE
                ]
            self.driver_client.cmd_dvr('get_resource', bogus_params)
        '''
        
    def test_apply_startup_params(self):
        """
        This test verifies that we can set the startup params
        from autosample mode.  It only verifies one parameter
        change because all parameters are tested above.
        """
        # Apply autosample happens for free when the driver fires up
        self.assert_initialize_driver()

        # Change something
        self.assert_set(Parameter.PUMP_PULSE, 15)

        # Now try to apply params in Streaming
        self.assert_driver_command(ProtocolEvent.START_AUTOSAMPLE, state=ProtocolState.AUTOSAMPLE)
        self.driver_client.cmd_dvr('apply_startup_params')

        # All done.  Verify the startup parameter has been reset
        self.assert_driver_command(ProtocolEvent.STOP_AUTOSAMPLE, state=ProtocolState.COMMAND)
        self.assert_get(Parameter.PUMP_PULSE, 16)
        
###############################################################################
#                            QUALIFICATION TESTS                              #
# Device specific qualification tests are for doing final testing of ion      #
# integration.  The generally aren't used for instrument debugging and should #
# be tackled after all unit and integration tests are complete                #
###############################################################################
@attr('QUAL', group='mi')
class DriverQualificationTest(InstrumentDriverQualificationTestCase):
    def setUp(self):
        InstrumentDriverQualificationTestCase.setUp(self)

    def test_direct_access_telnet_mode(self):
        """
        @brief This test manually tests that the Instrument Driver properly supports direct access to the physical instrument. (telnet mode)
        """
        
 #       self.assert_direct_access_start_telnet()
 #       self.assertTrue(self.tcp_client)

        ###
        #   Add instrument specific code here.
        ###

#       self.assert_direct_access_stop_telnet()
        
#    def test_poll(self):
#        '''
#        No polling for a single sample
#        '''
#       # Poll for a sample and confirm result.
#        sample1 = self.driver_client.cmd_dvr('execute_resource', Capability.ACQUIRE_SAMPLE)
#        log.debug("SAMPLE1 = " + str(sample1[1]))


    def test_autosample(self):
        '''
        start and stop autosample and verify data particle
        '''
        Pass
        
    def test_get_set_parameters(self):
        '''
        verify that all parameters can be get set properly, this includes
        ensuring that read only parameters fail on set.
        '''
        Pass

    def test_get_capabilities(self):
        """
        @brief Walk through all driver protocol states and verify capabilities
        returned by get_current_capabilities
        """
        
    def test_direct_access_telnet_mode(self):
        """
        Test that we can connect to the instrument via direct access.  Also
        verify that direct access parameters are reset on exit.
        """
        self.assert_enter_command_mode()
#       self.assert_set_parameter(Parameter.TXREALTIME, True)

        # go into direct access, and muck up a setting.
        self.assert_direct_access_start_telnet(timeout=600)
        self.assertTrue(self.tcp_client)
        # ask for device status from Sami.
        self.tcp_client.send_data("S0\r\n")
        self.tcp_client.expect(":")

        self.assert_direct_access_stop_telnet()

        # verify the setting got restored.
        self.assert_enter_command_mode()
        self.assert_get_parameter(Parameter.TXREALTIME, True)
    
    def test_execute_clock_sync(self):
        """
        Verify we can syncronize the instrument internal clock
        """
        self.assert_enter_command_mode()

        # wait for a bit so the event can be triggered
        time.sleep(1)

        # Set the clock to something in the past
        time_str = "01-Jan-2001 01:01:01"
        time_sec = convert_timestamp_to_sec(time_str)
        self.assert_set_parameter(Parameter.PROGRAM_DATE_TIME, "01 Jan 2001 01:01:01", verify=False)

        self.assert_execute_resource(ProtocolEvent.CLOCK_SYNC)
        self.assert_execute_resource(ProtocolEvent.ACQUIRE_CONFIGURATION)   # Get Configuration.

        # Now verify that at least the date matches
        params = [Parameter.PROGRAM_DATE_TIME]
        check_new_params = self.instrument_agent_client.get_resource(params)
        lt = time.strftime("%d %b %Y  %H:%M:%S", time.gmtime(time.mktime(time.localtime())))
        log.debug("TIME: %s && %s" % (lt, check_new_params[Parameter.PROGRAM_DATE_TIME]))
        self.assertTrue(lt[:12].upper() in check_new_params[Parameter.PROGRAM_DATE_TIME].upper())

