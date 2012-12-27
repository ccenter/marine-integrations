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

from nose.plugins.attrib import attr
from mock import Mock

from gevent import monkey; monkey.patch_all()
import gevent
import time
import re
from mock import Mock

from mi.core.common import BaseEnum
from mi.core.log import get_logger ; log = get_logger()
from nose.plugins.attrib import attr

# MI imports.
from mi.idk.unit_test import InstrumentDriverTestCase
from mi.idk.unit_test import InstrumentDriverUnitTestCase
from mi.idk.unit_test import InstrumentDriverIntegrationTestCase
from mi.idk.unit_test import InstrumentDriverQualificationTestCase
from mi.idk.unit_test import DriverTestMixin

from interface.objects import AgentCommand

from mi.core.instrument.logger_client import LoggerClient

from mi.core.instrument.instrument_driver import DriverAsyncEvent
from mi.core.instrument.instrument_driver import DriverConnectionState
from mi.core.instrument.instrument_driver import DriverProtocolState

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
# Data Particles
from mi.instrument.sami.pco2w.cgsn.driver import SamiRecordDataParticle
from mi.instrument.sami.pco2w.cgsn.driver import SamiRecordDataParticleKey
from mi.instrument.sami.pco2w.cgsn.driver import SamiStatusDataParticle
from mi.instrument.sami.pco2w.cgsn.driver import SamiStatusDataParticleKey
from mi.instrument.sami.pco2w.cgsn.driver import SamiConfigDataParticle
from mi.instrument.sami.pco2w.cgsn.driver import SamiConfigDataParticleKey
from mi.core.instrument.chunker import StringChunker
from mi.core.instrument.data_particle import DataParticleKey, DataParticleValue

###
#   Driver parameters for the tests
###
STATUS_SW_BUS = "90"
SAMPLE_ERR_DATA = "?03" + NEWLINE
SAMPLE_RECORD_DATA = "*5B2704C8EF9FC90FE606400FE8063C0FE30674640B1B1F0FE6065A0FE9067F0FE306A60CDE0FFF3B" + NEWLINE
SAMPLE_STATUS_DATA = ":000029ED40" + NEWLINE
SAMPLE_STATUS_DATA_BAD = "000029ED40" + NEWLINE
SAMPLE_CONFIG_DATA = "CAB39E84000000F401E13380570007080401000258030A0002580017000258011A003840001C1020FFA8181C010038100101202564000433383335000200010200020000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000" + NEWLINE
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
        Parameter.DEVICE_VERSION : str
    }

    # Test results that get decoded from the string sent to the chunker.   
    _data_record_parameters = {   
        SamiRecordDataParticleKey.UNIQUE_ID:      { 'type': int, 'value': 91},
        SamiRecordDataParticleKey.RECORD_LENGTH:  { 'type': int, 'value': 39},
        SamiRecordDataParticleKey.RECORD_TYPE:    { 'type': int, 'value': 4},
        SamiRecordDataParticleKey.RECORD_TIME:    { 'type': int, 'value': 51439},
        SamiRecordDataParticleKey.VOLTAGE_BATTERY:{ 'type': int, 'value': 205 },
        SamiRecordDataParticleKey.THERMISTER_RAW: { 'type': int, 'value': 255 },
        SamiRecordDataParticleKey.CHECKSUM:       { 'type': int, 'value': 59 },
        SamiRecordDataParticleKey.LIGHT_MEASUREMENT: { 'type': list}
    }
   
    # Test results that get decoded from the string sent to the chunker.
    _status_parameters = {
        SamiStatusDataParticleKey.TIME_OFFSET:          { 'type': int, 'value': 2},
        SamiStatusDataParticleKey.CLOCK_ACTIVE:         { 'type': bool, 'value': False},
        SamiStatusDataParticleKey.RECORDING_ACTIVE:     { 'type': bool, 'value': False },
        SamiStatusDataParticleKey.RECORD_END_ON_TIME:   { 'type': bool, 'value': True },
        SamiStatusDataParticleKey.RECORD_MEMORY_FULL:   { 'type': bool, 'value': False },
        SamiStatusDataParticleKey.RECORD_END_ON_ERROR:  { 'type': bool, 'value': True },
        SamiStatusDataParticleKey.DATA_DOWNLOAD_OK:     { 'type': bool, 'value': False },
        SamiStatusDataParticleKey.FLASH_MEMORY_OPEN:    { 'type': bool, 'value': True },
        SamiStatusDataParticleKey.BATTERY_FATAL_ERROR:  { 'type': bool, 'value': True },
        SamiStatusDataParticleKey.BATTERY_LOW_MEASUREMENT: { 'type': bool, 'value': False },
        SamiStatusDataParticleKey.BATTERY_LOW_BANK:     { 'type': bool, 'value': True },
        SamiStatusDataParticleKey.BATTERY_LOW_EXTERNAL: { 'type': bool, 'value': True },
        SamiStatusDataParticleKey.EXTERNAL_DEVICE_FAULT:{ 'type': int,  'value': 0x3 },
        SamiStatusDataParticleKey.FLASH_ERASED:         { 'type': bool, 'value': False },
        SamiStatusDataParticleKey.POWER_ON_INVALID:     { 'type': bool, 'value': True }
    }
    
    # Test Results that get decoded from the Configuration
    _config_parameters = {
        SamiConfigDataParticleKey.CFG_PROGRAM_DATE:     { 'type': int, 'value': 3400769156},
        SamiConfigDataParticleKey.CFG_START_TIME_OFFSET:{ 'type': int, 'value': 244},
        SamiConfigDataParticleKey.CFG_RECORDING_TIME:   { 'type': int, 'value': 31536000},
        SamiConfigDataParticleKey.CFG_MODE:             { 'type': int, 'value': 87 },        
        SamiConfigDataParticleKey.CFG_TIMER_INTERVAL_0: { 'type': int, 'value': 1800 },
        SamiConfigDataParticleKey.CFG_DRIVER_ID_0:      { 'type': int, 'value': 4 },
        SamiConfigDataParticleKey.CFG_PARAM_PTR_0:      { 'type': int, 'value': 1 },
        SamiConfigDataParticleKey.CFG_TIMER_INTERVAL_1: { 'type': int, 'value': 600 },
        SamiConfigDataParticleKey.CFG_DRIVER_ID_1:      { 'type': int, 'value': 3 },
        SamiConfigDataParticleKey.CFG_PARAM_PTR_1:      { 'type': int, 'value': 10 },
        SamiConfigDataParticleKey.CFG_TIMER_INTERVAL_2: { 'type': int, 'value': 600 },
        SamiConfigDataParticleKey.CFG_DRIVER_ID_2:      { 'type': int, 'value': 0 },
        SamiConfigDataParticleKey.CFG_PARAM_PTR_2:      { 'type': int, 'value': 23 },    
        SamiConfigDataParticleKey.CFG_TIMER_INTERVAL_3: { 'type': int, 'value': 600 },
        SamiConfigDataParticleKey.CFG_DRIVER_ID_3:      { 'type': int, 'value': 1 },
        SamiConfigDataParticleKey.CFG_PARAM_PTR_3:      { 'type': int, 'value': 26 },
        SamiConfigDataParticleKey.CFG_TIMER_INTERVAL_4: { 'type': int, 'value': 14400 },
        SamiConfigDataParticleKey.CFG_DRIVER_ID_4:      { 'type': int, 'value': 0 },
        SamiConfigDataParticleKey.CFG_PARAM_PTR_4:      { 'type': int, 'value': 28 },
        SamiConfigDataParticleKey.CFG_CO2_SETTINGS:     { 'type': unicode, 'value': u'1020FFA8181C010038' },
        SamiConfigDataParticleKey.CFG_SERIAL_SETTINGS:  { 'type': unicode, 'value': u'10010120256400043338333500' }
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

    def assert_driver_parameters(self, current_parameters, verify_values = False):
        """
        Verify that all driver parameters are correct and potentially verify values.
        @param current_parameters: driver parameters read from the driver instance
        @param verify_values: should we verify values against definition?
        """
        self.assert_parameters(current_parameters, self._driver_parameters, verify_values)

    def assert_particle_configuration(self, data_particle, verify_values = False):
        '''
        Verify a take sample data particle
        @param data_particle:  SamiConfigDataParticle data particle
        @param verify_values:  bool, should we verify parameter values
        '''
        log.debug("in assert_particle_configuration")
        self.assert_data_particle_header(data_particle, DataParticleType.CONFIG_PARSED)
        self.assert_data_particle_parameters(data_particle, self._config_parameters, verify_values)
        
    def assert_particle_device_status(self, data_particle, verify_values = False):
        '''
        Verify a take sample data particle
        @param data_particle:  SamiStatusDataParticle data particle
        @param verify_values:  bool, should we verify parameter values
        '''
        log.debug("in assert_particle_status")
        self.assert_data_particle_header(data_particle, DataParticleType.STATUS_PARSED)
        self.assert_data_particle_parameters(data_particle, self._status_parameters, verify_values)

    def assert_particle_record_data(self, data_particle, verify_values = False):
        '''
        Verify a take sample data particle
        @param data_particle:  SamiRecordDataParticle data particle
        @param verify_values:  bool, should we verify parameter values
        '''
        log.debug("in assert_particle_record_data")
        self.assert_data_particle_header(data_particle, DataParticleType.RECORD_PARSED)
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
    
    def setUp(self):
        InstrumentDriverUnitTestCase.setUp(self)

    def test_driver_enums(self):
        """
        Verify that all driver enumeration has no duplicate values that might cause confusion.  Also
        do a little extra validation for the Capabilites
        """
        self.assert_enum_has_no_duplicates(DataParticleType())
#       self.assert_enum_has_no_duplicates(InstrumentCmds())
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
        log.debug("Testing Chunker: %s" % "Got Here")

        chunker = StringChunker(Protocol.sieve_function)

        test_data = SAMPLE_STATUS_DATA      
        self.assert_chunker_sample(chunker, test_data)
        self.assert_chunker_sample_with_noise(chunker, test_data)
        self.assert_chunker_fragmented_sample(chunker, test_data)
        self.assert_chunker_combined_sample(chunker, test_data)

        test_data = SAMPLE_ERR_DATA
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
        self.assert_particle_published(driver, SAMPLE_RECORD_DATA, self.assert_particle_record_data, True)
        self.assert_particle_published(driver, SAMPLE_STATUS_DATA, self.assert_particle_device_status, True)

        self.assert_particle_published(driver, SAMPLE_CONFIG_DATA, self.assert_particle_configuration, True)

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

        expected_parameters = sorted(self._driver_parameters.keys())
        reported_parameters = sorted(driver.get_resource(Parameter.ALL))

        log.debug("Reported Parameters: %s" % reported_parameters)
        log.debug("Expected Parameters: %s" % expected_parameters)

        self.assertEqual(reported_parameters, expected_parameters)

    def test_capabilities(self):
        """
        Verify the FSM reports capabilities as expected.  All states defined in this dict must
        also be defined in the protocol FSM.
        """
#        capabilities = {
#            ProtocolState.UNKNOWN: ['DRIVER_EVENT_DISCOVER', 'DRIVER_FORCE_STATE'],
#            ProtocolState.COMMAND: ['DRIVER_EVENT_ACQUIRE_SAMPLE',
#                                    'DRIVER_EVENT_ACQUIRE_STATUS',
#                                    'DRIVER_EVENT_CLOCK_SYNC',
#                                    'DRIVER_EVENT_GET',
#                                    'DRIVER_EVENT_SET',
#                                    'DRIVER_EVENT_START_AUTOSAMPLE',
#                                    'DRIVER_EVENT_START_DIRECT',
#                                    'PROTOCOL_EVENT_INIT_LOGGING',
#                                    'PROTOCOL_EVENT_QUIT_SESSION',
#                                    'PROTOCOL_EVENT_SETSAMPLING'],
#            ProtocolState.AUTOSAMPLE: ['DRIVER_EVENT_GET', 'DRIVER_EVENT_STOP_AUTOSAMPLE'],
#            ProtocolState.DIRECT_ACCESS: ['DRIVER_EVENT_STOP_DIRECT', 'EXECUTE_DIRECT']
#       }
#
#        driver = InstrumentDriver(self._got_data_event_callback)
#        self.assert_capabilities(driver, capabilities)

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


    def test_parameters(self):
        """
        Test driver parameters and verify their type.  Startup parameters also verify the parameter
        value.  This test confirms that parameters are being read/converted properly and that
        the startup has been applied.
        """
        self.assert_initialize_driver()
        reply = self.driver_client.cmd_dvr('get_resource', Parameter.ALL)

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
        log.debug("CJC: All Good ")
        
 #       self.assert_direct_access_start_telnet()
 #       self.assertTrue(self.tcp_client)

        ###
        #   Add instrument specific code here.
        ###

#       self.assert_direct_access_stop_telnet()
        
    def test_poll(self):
        '''
        No polling for a single sample
        '''


    def test_autosample(self):
        '''
        start and stop autosample and verify data particle
        '''


    def test_get_set_parameters(self):
        '''
        verify that all parameters can be get set properly, this includes
        ensuring that read only parameters fail on set.
        '''
        self.assert_enter_command_mode()


    def test_get_capabilities(self):
        """
        @brief Walk through all driver protocol states and verify capabilities
        returned by get_current_capabilities
        """
        self.assert_enter_command_mode()
