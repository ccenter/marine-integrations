"""
@package mi.instrument.sami.w.cgsn.test.test_driver
@file marine-integrations/mi/instrument/sami/w/cgsn/driver.py
@author Chris Center
@brief Test cases for cgsn driver

USAGE:
 Make tests verbose and provide stdout4
   * From the IDK
       $ bin/test_driver
       $ bin/test_driver -u [-t testname]
       $ bin/test_driver -i [-t testname]
       $ bin/test_driver -q [-t testname]
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
from mi.instrument.sami.pco2w.cgsn.driver import SamiRecordDataParticle
from mi.instrument.sami.pco2w.cgsn.driver import SamiRecordDataParticleKey
from mi.instrument.sami.pco2w.cgsn.driver import SamiStatusDataParticle
from mi.instrument.sami.pco2w.cgsn.driver import SamiStatusDataParticleKey
from mi.instrument.sami.pco2w.cgsn.driver import SamiConfigDataParticle
from mi.instrument.sami.pco2w.cgsn.driver import SamiConfigDataParticleKey
from mi.instrument.sami.pco2w.cgsn.driver import SamiErrorDataParticle
from mi.instrument.sami.pco2w.cgsn.driver import SamiErrorDataParticleKey

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
SAMPLE_IMMEDIATE_STATUS_DATA = "10" + NEWLINE
SAMPLE_ERROR_DATA = "?03" + NEWLINE
SAMPLE_RECORD_DATA = "*5B2704C8EF9FC90FE606400FE8063C0FE30674640B1B1F0FE6065A0FE9067F0FE306A60CDE0FFF3B"  + NEWLINE
# SAMPLE_DEVICE_STATUS_DATA = ":000029ED40"  + NEWLINE
SAMPLE_DEVICE_STATUS_DATA = ":003F91BE00000000" # :003F91BE0000000000000000000000F7" + NEWLINE
SAMPLE_DEVICE_STATUS_DATA_BAD = "000029ED40"  + NEWLINE
# SAMPLE_CONFIG_DATA = "CAB39E84000000F401E13380570007080401000258030A0002580017000258011A003840001C1020FFA8181C010038100101202564000433383335000200010200020000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000" + NEWLINE
# This sample configuration is from the PCO2W_Low_Level_SAMI_Use document.
SAMPLE_CONFIG_DATA_1 = "CAB39E84000000F401E13380570007080401000258030A0002580017000258011A003840001C071020FFA8181C010038100101202564000433383335000200010200000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"  + NEWLINE

#                     :000029ED4000000000000000000000F7" + NEWLINE

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
    ###
    #  Parameter and Type Definitions
    ##
    _driver_parameters = {
        # DS # parameters - contains all setsampling parameters
        Parameter.PUMP_PULSE : { 'type' : int, STARTUP: False, 'value' : 1 },
        Parameter.PUMP_ON_TO_MEASURE : { 'type' : int, STARTUP: False, 'value' : 2 },
        Parameter.NUM_SAMPLES_PER_MEASURE : { 'type' : int, STARTUP: False, 'value' : 3 },
        Parameter.NUM_CYCLES_BETWEEN_BLANKS : { 'type' : int, STARTUP: False, 'value' : 4 },
        Parameter.NUM_REAGENT_CYCLES : { 'type' : int, STARTUP: False, 'value' : 5 },
        Parameter.NUM_BLANK_CYCLES : { 'type' : int, STARTUP: False, 'value' : 6 },
        Parameter.FLUSH_PUMP_INTERVAL_SEC : { 'type' : int, STARTUP: False, 'value' : 7 },
        Parameter.STARTUP_BLANK_FLUSH_ENABLE : { 'type' : bool, STARTUP: False, 'value' : False },
        Parameter.PUMP_PULSE_POST_MEASURE_ENABLE : { 'type' : bool, STARTUP: False, 'value' : False },
        Parameter.NUM_EXTRA_PUMP_CYCLES : { 'type' : int, STARTUP: False, 'value' : 8 }
    }

    # Test results that get decoded from the string sent to the chunker.   
    _data_record_parameters = {   
        SamiRecordDataParticleKey.UNIQUE_ID:      { 'type': int, STARTUP: False, 'value': 91},
        SamiRecordDataParticleKey.RECORD_LENGTH:  { 'type': int, STARTUP: False, 'value': 39},
        SamiRecordDataParticleKey.RECORD_TYPE:    { 'type': int, STARTUP: False, 'value': 4},
        SamiRecordDataParticleKey.RECORD_TIME:    { 'type': int, STARTUP: False, 'value': 51439},
        SamiRecordDataParticleKey.VOLTAGE_BATTERY:{ 'type': int, STARTUP: False, 'value': 205 },
        SamiRecordDataParticleKey.THERMISTER_RAW: { 'type': int, STARTUP: False, 'value': 255 },
        SamiRecordDataParticleKey.CHECKSUM:       { 'type': int, STARTUP: False, 'value': 59 },
        SamiRecordDataParticleKey.LIGHT_MEASUREMENT: { 'type': list, STARTUP: False }
    }
   
    # Test results that get decoded from the string sent to the chunker.
    _device_status_parameters = {
        SamiStatusDataParticleKey.TIME_OFFSET:          { 'type': int,  STARTUP: False, 'value': 0x3F91BE},  # 48 5:14:38
        SamiStatusDataParticleKey.CLOCK_ACTIVE:         { 'type': bool, STARTUP: False, 'value': False},
        SamiStatusDataParticleKey.RECORDING_ACTIVE:     { 'type': bool, STARTUP: False, 'value': False },
        SamiStatusDataParticleKey.RECORD_END_ON_TIME:   { 'type': bool, STARTUP: False, 'value': False },
        SamiStatusDataParticleKey.RECORD_MEMORY_FULL:   { 'type': bool, STARTUP: False, 'value': False },
        SamiStatusDataParticleKey.RECORD_END_ON_ERROR:  { 'type': bool, STARTUP: False, 'value': False },
        SamiStatusDataParticleKey.DATA_DOWNLOAD_OK:     { 'type': bool, STARTUP: False, 'value': False },
        SamiStatusDataParticleKey.FLASH_MEMORY_OPEN:    { 'type': bool, STARTUP: False, 'value': False },
        SamiStatusDataParticleKey.BATTERY_FATAL_ERROR:  { 'type': bool, STARTUP: False, 'value': False },
        SamiStatusDataParticleKey.BATTERY_LOW_MEASUREMENT: { 'type': bool, STARTUP: False, 'value': False },
        SamiStatusDataParticleKey.BATTERY_LOW_BANK:     { 'type': bool, STARTUP: False, 'value': False },
        SamiStatusDataParticleKey.BATTERY_LOW_EXTERNAL: { 'type': bool, STARTUP: False, 'value': False },
        SamiStatusDataParticleKey.EXTERNAL_DEVICE_FAULT:{ 'type': int,  STARTUP: False, 'value': 0x0 },
        SamiStatusDataParticleKey.FLASH_ERASED:         { 'type': bool, STARTUP: False, 'value': False },
        SamiStatusDataParticleKey.POWER_ON_INVALID:     { 'type': bool, STARTUP: False, 'value': False }
    }
    
    # Test for Immediate Status.
    _immediate_status_parameters = {
        SamiImmediateStatusDataParticleKey.PUMP_ON:          { 'type': bool, STARTUP: False, 'value': True  },
        SamiImmediateStatusDataParticleKey.VALVE_ON:         { 'type': bool, STARTUP: False, 'value': False },      
        SamiImmediateStatusDataParticleKey.EXTERNAL_POWER_ON:{ 'type': bool, STARTUP: False, 'value': False },
        SamiImmediateStatusDataParticleKey.DEBUG_LED_ON:     { 'type': bool, STARTUP: False, 'value': False },
        SamiImmediateStatusDataParticleKey.DEBUG_ECHO_ON:    { 'type': bool, STARTUP: False, 'value': False }
    }
    
    # Test Error Information
    _error_parameters = {
        SamiErrorDataParticleKey.ERROR_MESSAGE:{ 'type': unicode, STARTUP: False, 'value': u'Command Buffer Overflow' }
    }
    
    # Test Results that get decoded from the Configuration
    _config_parameters = {
        SamiConfigDataParticleKey.PROGRAM_DATE_TIME:{ 'type': int, STARTUP: False, 'value': 0xCAB39E84}, # 3400769156 = 0xCAB39E84
        SamiConfigDataParticleKey.START_TIME_OFFSET:{ 'type': int, STARTUP: False, 'value': 244},
        SamiConfigDataParticleKey.RECORDING_TIME:   { 'type': int, STARTUP: False, 'value': 31536000},
        
        SamiConfigDataParticleKey.PMI_SAMPLE_SCHEDULE         : { 'type': bool, STARTUP: False, 'value': True },
        SamiConfigDataParticleKey.SAMI_SAMPLE_SCHEDULE        : { 'type': bool, STARTUP: False, 'value': True },
        SamiConfigDataParticleKey.SLOT1_FOLLOWS_SAMI_SCHEDULE : { 'type': bool, STARTUP: False, 'value': True },
        SamiConfigDataParticleKey.SLOT1_INDEPENDENT_SCHEDULE  : { 'type': bool, STARTUP: False, 'value': False },
        SamiConfigDataParticleKey.SLOT2_FOLLOWS_SAMI_SCHEDULE : { 'type': bool, STARTUP: False, 'value': True },
        SamiConfigDataParticleKey.SLOT2_INDEPENDENT_SCHEDULE  : { 'type': bool, STARTUP: False, 'value': False },
        SamiConfigDataParticleKey.SLOT3_FOLLOWS_SAMI_SCHEDULE : { 'type': bool, STARTUP: False, 'value': True },
        SamiConfigDataParticleKey.SLOT3_INDEPENDENT_SCHEDULE  : { 'type': bool, STARTUP: False, 'value': False },

        SamiConfigDataParticleKey.TIMER_INTERVAL_SAMI:{ 'type': int, STARTUP: False, 'value': 1800 },
        SamiConfigDataParticleKey.DRIVER_ID_SAMI:     { 'type': int, STARTUP: False, 'value': 4 },
        SamiConfigDataParticleKey.PARAM_PTR_SAMI:     { 'type': int, STARTUP: False, 'value': 1 },
        SamiConfigDataParticleKey.TIMER_INTERVAL_1:   { 'type': int, STARTUP: False, 'value': 600 },
        SamiConfigDataParticleKey.DRIVER_ID_1:        { 'type': int, STARTUP: False, 'value': 3 },
        SamiConfigDataParticleKey.PARAM_PTR_1:        { 'type': int, STARTUP: False, 'value': 10 },
        SamiConfigDataParticleKey.TIMER_INTERVAL_2:   { 'type': int, STARTUP: False, 'value': 600 },
        SamiConfigDataParticleKey.DRIVER_ID_2:        { 'type': int, STARTUP: False, 'value': 0 },
        SamiConfigDataParticleKey.PARAM_PTR_2:        { 'type': int, STARTUP: False, 'value': 23 },    
        SamiConfigDataParticleKey.TIMER_INTERVAL_3:   { 'type': int, STARTUP: False, 'value': 600 },
        SamiConfigDataParticleKey.DRIVER_ID_3:        { 'type': int, STARTUP: False, 'value': 1 },
        SamiConfigDataParticleKey.PARAM_PTR_3:        { 'type': int, STARTUP: False, 'value': 26 },
        SamiConfigDataParticleKey.TIMER_INTERVAL_PRESTART: { 'type': int, STARTUP: False, 'value': 14400 },
        SamiConfigDataParticleKey.DRIVER_ID_PRESTART: { 'type': int, STARTUP: False, 'value': 0 },
        SamiConfigDataParticleKey.PARAM_PTR_PRESTART: { 'type': int, STARTUP: False, 'value': 28 },
        
        SamiConfigDataParticleKey.USE_BAUD_RATE_57600:    { 'type': bool, STARTUP: False, 'value': True },
        SamiConfigDataParticleKey.SEND_RECORD_TYPE_EARLY: { 'type': bool, STARTUP: False, 'value': True },
        SamiConfigDataParticleKey.SEND_LIVE_RECORDS:      { 'type': bool, STARTUP: False, 'value': True },
        
        SamiConfigDataParticleKey.PUMP_PULSE:             { 'type': int, STARTUP: False, 'value': 0x10 },
        SamiConfigDataParticleKey.PUMP_ON_TO_MEAURSURE:   { 'type': int, STARTUP: False, 'value': 0x20 },
        SamiConfigDataParticleKey.SAMPLES_PER_MEASURE:    { 'type': int, STARTUP: False, 'value': 0xFF },
        SamiConfigDataParticleKey.CYCLES_BETWEEN_BLANKS:  { 'type': int, STARTUP: False, 'value': 0xA8 },
        SamiConfigDataParticleKey.NUM_REAGENT_CYCLES:     { 'type': int, STARTUP: False, 'value': 0x18 },
        SamiConfigDataParticleKey.NUM_BLANK_CYCLES:       { 'type': int, STARTUP: False, 'value': 0x1C },
        SamiConfigDataParticleKey.FLUSH_PUMP_INTERVAL:    { 'type': int, STARTUP: False, 'value': 0x1 },
        SamiConfigDataParticleKey.BLANK_FLUSH_ON_START_ENABLE:   { 'type': bool, STARTUP: False, 'value': True },
        SamiConfigDataParticleKey.PUMP_PULSE_POST_MEASURE:{ 'type': bool, STARTUP: False, 'value': False },
        SamiConfigDataParticleKey.CYCLE_DATA:             { 'type': int,  STARTUP: False, 'value': 0x38 },                         
        SamiConfigDataParticleKey.SERIAL_SETTINGS:        { 'type': unicode, STARTUP: False, 'value': u'10010120256400043338333500' }
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
        if (isinstance(data_particle, SamiRecordDataParticle)):
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
        
    def assert_particle_record_data(self, data_particle, verify_values = False):
        '''
        Verify a take sample data particle
        @param data_particle:  SamiRecordDataParticle data particle
        @param verify_values:  bool, should we verify parameter values
        '''
        self.assert_data_particle_header(data_particle, DataParticleType.RECORD_PARSED)
        self.assert_data_particle_parameters(data_particle, self._data_record_parameters, verify_values)

    def assert_particle_error(self, data_particle, verify_values = False):
        '''
        Error response.
        '''
        self.assert_data_particle_header(data_particle, DataParticleType.ERROR_PARSED)
        self.assert_data_particle_parameters(data_particle, self._error_parameters, verify_values)

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
    
    def setUp(self):
        InstrumentDriverUnitTestCase.setUp(self)

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

        test_data = SAMPLE_RECORD_DATA      
        self.assert_chunker_sample(chunker, test_data)
        self.assert_chunker_sample_with_noise(chunker, test_data)
        self.assert_chunker_fragmented_sample(chunker, test_data)
        self.assert_chunker_combined_sample(chunker, test_data)

        test_data = SAMPLE_DEVICE_STATUS_DATA      
        self.assert_chunker_sample(chunker, test_data)
        self.assert_chunker_sample_with_noise(chunker, test_data)
        self.assert_chunker_fragmented_sample(chunker, test_data)
        self.assert_chunker_combined_sample(chunker, test_data)
        '''        
        # This is test data and should be handled elsewhere.
        test_data = SAMPLE_ERROR_DATA      
        self.assert_chunker_sample(chunker, test_data)
        self.assert_chunker_sample_with_noise(chunker, test_data)
        self.assert_chunker_fragmented_sample(chunker, test_data)
        self.assert_chunker_combined_sample(chunker, test_data)
        '''

    def test_got_data(self):
        """
        Verify sample data passed through the got data method produces the correct data particles
        """
        # Create and initialize the instrument driver with a mock port agent
        driver = InstrumentDriver(self._got_data_event_callback)
        self.assert_initialize_driver(driver)
        self.assert_raw_particle_published(driver, True)

        # Start validating data particles
        self.assert_particle_published(driver, SAMPLE_DEVICE_STATUS_DATA, self.assert_particle_device_status, True)
        self.assert_particle_published(driver, SAMPLE_RECORD_DATA, self.assert_particle_record_data, True)
        self.assert_particle_published(driver, SAMPLE_CONFIG_DATA_1, self.assert_particle_configuration, True)
#??        self.assert_particle_published(driver, SAMPLE_ERROR_DATA, self.assert_particle_error, True)
        # Sami Immediate status is a command.
        # self.assert_particle_published(driver, SAMPLE_IMMEDIATE_STATUS_DATA, self.assert_particle_immediate_status, True)

    def test_cjc(self):
        """
        Custom testing
        """
        driver = InstrumentDriver(self._got_data_event_callback)
        self.assert_initialize_driver(driver, ProtocolState.COMMAND)
        
        set_time_sec = get_timestamp_delayed_sec()
        expected_time_sec = get_timestamp_delayed_sec()
 
        self.reset_test_vars()
        packet = PortAgentPacket()
        packet.attach_data(SAMPLE_CONFIG_DATA_1) 
        driver._protocol.got_data(packet)     
        
        my_parameters = sorted(driver.get_resource(Parameter.ALL))
        log.debug("my parameters: %s" % my_parameters)

# Not Available.   
#        self.assert_set_parameter(Parameter.PROGRAM_DATE_TIME, set_time_sec)
#        self.assert_get_parameter(Parameter.PROGRAM_DATE_TIME, expected_time_sec)

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
        log.debug("got here tdp")
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

    def _mock_me(self):
        """
        Create a mock port agent
        """
        mock_port_agent = Mock( spec=LoggerClient)
        
        """
        Instantiate the driver class directly (no driver client, no driver
        client, no zmq driver process, no driver process; just own the driver)
        """       
        temp_driver = InstrumentDriver(self.mock_event_callback)       
        current_state = temp_driver.get_resource_state()
        self.assertEqual(current_state, DriverConnectionState.UNCONFIGURED)
        
        """
        Now configure the driver with the mock_port_agent, verifying
        that the driver transitions to the DISCONNECTED state
        """
        config = {'mock_port_agent' : mock_port_agent}
        temp_driver.configure(config = config)
        current_state = temp_driver.get_resource_state()
        self.assertEqual(current_state, DriverConnectionState.DISCONNECTED)
        
        """
        Invoke the connect method of the driver: should connect to mock
        port agent.  Verify that the connection FSM transitions to CONNECTED,
        (which means that the FSM should now be reporting the ProtocolState).
        """
        temp_driver.connect()
        current_state = temp_driver.get_resource_state()
        self.assertEqual(current_state, DriverProtocolState.UNKNOWN)
        log.debug("mock_me success")
        return( temp_driver )
    
    def test_complete_sample(self):
        temp_driver = self._mock_me()
        
        """
        Force the driver into AUTOSAMPLE state so that it will parse and 
        publish samples
        """        
        temp_driver.set_test_mode(True)
        temp_driver.test_force_state(state = DriverProtocolState.AUTOSAMPLE)
        current_state = temp_driver.get_resource_state()
        self.assertEqual(current_state, DriverProtocolState.AUTOSAMPLE)
        
        self.reset_test_vars()
        packet = PortAgentPacket()
        packet.attach_data(SAMPLE_RECORD_DATA) 
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
class SamiIntegrationTest(InstrumentDriverIntegrationTestCase):
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
                log.debug("CJC: Test " + key +  " is of type " + str(PARAMS[key]))
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
        log.debug("**************** COMMAND ***************")
        
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

    def test_set(self):
        """
        Test all set commands. Verify all exception cases.
        """
        self.assert_initialize_driver()   
        self.assert_set(Parameter.PUMP_PULSE, 0x00, no_get=True)
        self.assert_get(Parameter.PUMP_PULSE, 0x16)

    def test_get(self):        
        self.put_instrument_in_command_mode()

        params = {
                   Parameter.PUMP_PULSE: 16,
                   Parameter.PUMP_ON_TO_MEASURE: 32
        }

        log.debug("<<<<<<<<<<<<<<< get/set Test 1 - Pump Stuff >>>>>>>>>>>>>>>>>>>>>.")
        
        reply = self.driver_client.cmd_dvr('set_resource', params)
        log.debug("got here___________________________ 1")
        self.assertEqual(reply, None)
        log.debug("got here___________________________ 2")

        reply = self.driver_client.cmd_dvr('get_resource', Parameter.ALL)
        log.debug("got here___________________________ 3")
        self.assert_param_dict(reply)
        log.debug("<<<<<<<<<<<<<<< Done >>>>>>>>>>>>>>>>>>>>>.")
        """        
        reply = self.driver_client.cmd_dvr('get_resource',
                                           params.keys(),
                                           timeout=20)
        
        self.assertEquals(reply, params)
        
        log.debug("past assertEquals()")
        
        self.assertRaises(InstrumentCommandException,
                          self.driver_client.cmd_dvr,
                          'bogus', [Parameter.PUMP_PULSE])

        # Assert get fails without a paramet
        self.assertRaises(InstrumentParameterException,
                          self.driver_client.cmd_dvr, 'get_resource')
            
        # Assert get fails with a bad parameter (not ALL or a list).
        with self.assertRaises(InstrumentParameterException):
            bogus_params = 'I am a bogus param list.'
            self.driver_client.cmd_dvr('get_resource', bogus_params)
            
        # Assert get fails with a bad parameter in a list).
        with self.assertRaises(InstrumentParameterException):
            bogus_params = [
                'a bogus parameter name',
                Parameter.PUMP_PULSE
                ]
            self.driver_client.cmd_dvr('get_resource', bogus_params)
        """
        
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

