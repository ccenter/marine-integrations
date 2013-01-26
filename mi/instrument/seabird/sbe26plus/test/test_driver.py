"""
@package mi.instrument.seabird.sbe26plus.test.test_driver
@file marine-integrations/mi/instrument/seabird/sbe26plus/driver.py
@author Roger Unwin
@brief Test cases for ooicore driver

@todo Figure out clock sync off by one issue
@todo figure out the pattern for applying startup config
@todo what to do with startup parameters that don't have a startup value

USAGE:
 Make tests verbose and provide stdout
   * From the IDK
       $ bin/test_driver
       $ bin/test_driver -u
       $ bin/test_driver -i
       $ bin/test_driver -q
"""

__author__ = 'Roger Unwin'
__license__ = 'Apache 2.0'

from gevent import monkey; monkey.patch_all()
import gevent
import time
import re
from mock import Mock

from mi.core.common import BaseEnum
from mi.core.log import get_logger ; log = get_logger()
from mi.core.time import get_timestamp_delayed
from nose.plugins.attrib import attr
from mi.idk.unit_test import DriverTestMixin
from mi.idk.unit_test import ParameterTestConfigKey

from mi.instrument.seabird.test.test_driver import SeaBirdUnitTest
from mi.instrument.seabird.test.test_driver import SeaBirdIntegrationTest
from mi.instrument.seabird.test.test_driver import SeaBirdQualificationTest


from mi.instrument.seabird.sbe26plus.test.sample_data import SAMPLE_TIDE_DATA
from mi.instrument.seabird.sbe26plus.test.sample_data import SAMPLE_DEVICE_STATUS
from mi.instrument.seabird.sbe26plus.test.sample_data import SAMPLE_STATISTICS
from mi.instrument.seabird.sbe26plus.test.sample_data import SAMPLE_WAVE_BURST
from mi.instrument.seabird.sbe26plus.test.sample_data import SAMPLE_DEVICE_CALIBRATION

from ion.agents.instrument.direct_access.direct_access_server import DirectAccessTypes
from mi.instrument.seabird.sbe26plus.driver import DataParticleType
from mi.instrument.seabird.sbe26plus.driver import InstrumentDriver
from mi.instrument.seabird.sbe26plus.driver import ProtocolState
from mi.instrument.seabird.sbe26plus.driver import Parameter
from mi.instrument.seabird.sbe26plus.driver import ProtocolEvent
from mi.instrument.seabird.sbe26plus.driver import Capability
from mi.instrument.seabird.sbe26plus.driver import Prompt
from mi.instrument.seabird.sbe26plus.driver import Protocol
from mi.instrument.seabird.sbe26plus.driver import InstrumentCmds
from mi.instrument.seabird.sbe26plus.driver import NEWLINE
from mi.instrument.seabird.sbe26plus.driver import SBE26plusTideSampleDataParticle
from mi.instrument.seabird.sbe26plus.driver import SBE26plusWaveBurstDataParticle
from mi.instrument.seabird.sbe26plus.driver import SBE26plusStatisticsDataParticle
from mi.instrument.seabird.sbe26plus.driver import SBE26plusDeviceCalibrationDataParticle
from mi.instrument.seabird.sbe26plus.driver import SBE26plusDeviceStatusDataParticle
from mi.instrument.seabird.sbe26plus.driver import SBE26plusTideSampleDataParticleKey
from mi.instrument.seabird.sbe26plus.driver import SBE26plusWaveBurstDataParticleKey
from mi.instrument.seabird.sbe26plus.driver import SBE26plusStatisticsDataParticleKey
from mi.instrument.seabird.sbe26plus.driver import SBE26plusDeviceCalibrationDataParticleKey
from mi.instrument.seabird.sbe26plus.driver import SBE26plusDeviceStatusDataParticleKey
from mi.core.instrument.chunker import StringChunker
from mi.core.instrument.data_particle import DataParticleKey
from mi.core.instrument.data_particle import DataParticleValue
from mi.core.instrument.instrument_driver import DriverParameter, DriverConnectionState, DriverAsyncEvent
from mi.core.instrument.instrument_protocol import DriverProtocolState
from mi.core.exceptions import SampleException, InstrumentParameterException, InstrumentStateException
from mi.core.exceptions import InstrumentProtocolException, InstrumentCommandException

from pyon.core.exception import Conflict
from interface.objects import AgentCommand
from pyon.agent.agent import ResourceAgentState
from pyon.agent.agent import ResourceAgentEvent

# Globals
raw_stream_received = False
parsed_stream_received = False

###
#   Driver parameters for the tests
###

# Create some short names for the parameter test config
TYPE = ParameterTestConfigKey.TYPE
READONLY = ParameterTestConfigKey.READONLY
STARTUP = ParameterTestConfigKey.STARTUP
DA = ParameterTestConfigKey.DIRECT_ACCESS
VALUE = ParameterTestConfigKey.VALUE
REQUIRED = ParameterTestConfigKey.REQUIRED
DEFAULT = ParameterTestConfigKey.DEFAULT

class SeaBird26PlusMixin(DriverTestMixin):
    '''
    Mixin class used for storing data particle constance and common data assertion methods.
    '''
    ###
    #  Parameter and Type Definitions
    ###
    _driver_parameters = {
        # Parameters defined in the IOS
        Parameter.EXTERNAL_TEMPERATURE_SENSOR: {TYPE: bool, READONLY: True, DA: True, STARTUP: True, DEFAULT: False, VALUE: False},
        Parameter.CONDUCTIVITY: {TYPE: bool, READONLY: True, DA: True, STARTUP: True, DEFAULT: False, VALUE: False},
        Parameter.USER_INFO : {TYPE: str, READONLY: False, DA: False, STARTUP: False},
        Parameter.TXREALTIME: {TYPE: bool, READONLY: False, DA: True, STARTUP: True, DEFAULT: True, VALUE: True},
        Parameter.TXWAVEBURST: {TYPE: bool, READONLY: False, DA: True, STARTUP: True, DEFAULT: False, VALUE: False},

        # Set sampling parameters
        Parameter.TIDE_INTERVAL : {TYPE: int, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.TIDE_MEASUREMENT_DURATION : {TYPE: int, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS : {TYPE: float, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.WAVE_SAMPLES_PER_BURST : {TYPE: int, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.WAVE_SAMPLES_SCANS_PER_SECOND : {TYPE: float, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.USE_START_TIME : {TYPE: bool, READONLY: True, DA: False, STARTUP: False, REQUIRED: False, VALUE: False},
        Parameter.USE_STOP_TIME : {TYPE: bool, READONLY: True, DA: False, STARTUP: False, REQUIRED: False, VALUE: False},
        Parameter.TIDE_SAMPLES_PER_DAY : {TYPE: float, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.WAVE_BURSTS_PER_DAY : {TYPE: float, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.MEMORY_ENDURANCE : {TYPE: float, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.NOMINAL_ALKALINE_BATTERY_ENDURANCE : {TYPE: float, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.TOTAL_RECORDED_TIDE_MEASUREMENTS : {TYPE: float, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.TOTAL_RECORDED_WAVE_BURSTS : {TYPE: float, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.TIDE_MEASUREMENTS_SINCE_LAST_START : {TYPE: float, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.WAVE_BURSTS_SINCE_LAST_START : {TYPE: float, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.TXWAVESTATS : {TYPE: bool, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.NUM_WAVE_SAMPLES_PER_BURST_FOR_WAVE_STASTICS : {TYPE: int, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.USE_MEASURED_TEMP_AND_CONDUCTIVITY_FOR_DENSITY_CALC : {TYPE: bool, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.AVERAGE_WATER_TEMPERATURE_ABOVE_PRESSURE_SENSOR : {TYPE: float, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.AVERAGE_SALINITY_ABOVE_PRESSURE_SENSOR : {TYPE: float, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.PRESSURE_SENSOR_HEIGHT_FROM_BOTTOM : {TYPE: float, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND : {TYPE: int, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.MIN_ALLOWABLE_ATTENUATION : {TYPE: float, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM : {TYPE: float, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.MAX_PERIOD_IN_AUTO_SPECTRUM : {TYPE: float, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},
        Parameter.HANNING_WINDOW_CUTOFF : {TYPE: float, READONLY: False, DA: False, STARTUP: False, REQUIRED: False},

        # DS parameters - also includes sampling parameters
        Parameter.DEVICE_VERSION : {TYPE: str, READONLY: True},
        Parameter.SERIAL_NUMBER : {TYPE: str, READONLY: True},
        Parameter.DS_DEVICE_DATE_TIME : {TYPE: str, READONLY: True},
        Parameter.QUARTZ_PRESSURE_SENSOR_SERIAL_NUMBER : {TYPE: float, READONLY: True},
        Parameter.QUARTZ_PRESSURE_SENSOR_RANGE : {TYPE: float, READONLY: True},
        Parameter.IOP_MA : {TYPE: float, READONLY: True},
        Parameter.VMAIN_V : {TYPE: float, READONLY: True},
        Parameter.VLITH_V : {TYPE: float, READONLY: True},
        Parameter.LAST_SAMPLE_P : {TYPE: float, READONLY: True, REQUIRED: False},
        Parameter.LAST_SAMPLE_T : {TYPE: float, READONLY: True, REQUIRED: False},
        Parameter.LAST_SAMPLE_S : {TYPE: float, READONLY: True, REQUIRED: False},
        Parameter.SHOW_PROGRESS_MESSAGES : { TYPE: bool, READONLY: True, REQUIRED: False},
        Parameter.STATUS : { TYPE: str, READONLY: True},
        Parameter.LOGGING : { TYPE: bool, READONLY: True},
        }

    _tide_sample_parameters = {
        SBE26plusTideSampleDataParticleKey.TIMESTAMP: {TYPE: float, VALUE: 3558413454.0 },
        SBE26plusTideSampleDataParticleKey.PRESSURE: {TYPE: float, VALUE: 14.5385 },
        SBE26plusTideSampleDataParticleKey.PRESSURE_TEMP: {TYPE: float, VALUE: 24.228 },
        SBE26plusTideSampleDataParticleKey.TEMPERATURE: {TYPE: float, VALUE: 23.8404 },
        SBE26plusTideSampleDataParticleKey.CONDUCTIVITY: {TYPE: float, REQUIRED: False },
        SBE26plusTideSampleDataParticleKey.SALINITY: {TYPE: float, REQUIRED: False }
    }

    _wave_sample_parameters = {
        SBE26plusWaveBurstDataParticleKey.TIMESTAMP: {TYPE: float, VALUE: 3558413454.0 },
        SBE26plusWaveBurstDataParticleKey.PTFREQ: {TYPE: float, VALUE: 171791.359 },
        SBE26plusWaveBurstDataParticleKey.PTRAW: {TYPE: list }
    }

    _statistics_sample_parameters = {
        SBE26plusStatisticsDataParticleKey.DEPTH: {TYPE: float, VALUE: 0.0 },
        SBE26plusStatisticsDataParticleKey.TEMPERATURE: {TYPE: float, VALUE: 23.840 },
        SBE26plusStatisticsDataParticleKey.SALINITY: {TYPE: float, VALUE: 35.000 },
        SBE26plusStatisticsDataParticleKey.DENSITY: {TYPE: float, VALUE: 1023.690 },
        SBE26plusStatisticsDataParticleKey.N_AGV_BAND: {TYPE: int, VALUE: 5 },
        SBE26plusStatisticsDataParticleKey.TOTAL_VARIANCE: {TYPE: float, VALUE: 1.0896e-05 },
        SBE26plusStatisticsDataParticleKey.TOTAL_ENERGY: {TYPE: float, VALUE: 1.0939e-01 },
        SBE26plusStatisticsDataParticleKey.SIGNIFICANT_PERIOD: {TYPE: float, VALUE: 5.3782e-01 },
        SBE26plusStatisticsDataParticleKey.SIGNIFICANT_WAVE_HEIGHT: {TYPE: float, VALUE: 1.3204e-02 },
        SBE26plusStatisticsDataParticleKey.TSS_WAVE_INTEGRATION_TIME: {TYPE: int, VALUE: 128 },
        SBE26plusStatisticsDataParticleKey.TSS_NUMBER_OF_WAVES: {TYPE: float, VALUE: 0 },
        SBE26plusStatisticsDataParticleKey.TSS_TOTAL_VARIANCE: {TYPE: float, VALUE: 1.1595e-05 },
        SBE26plusStatisticsDataParticleKey.TSS_TOTAL_ENERGY: {TYPE: float, VALUE: 1.1640e-01 },
        SBE26plusStatisticsDataParticleKey.TSS_AVERAGE_WAVE_HEIGHT: {TYPE: float, VALUE: 0.0000e+00 },
        SBE26plusStatisticsDataParticleKey.TSS_AVERAGE_WAVE_PERIOD: {TYPE: float, VALUE: 0.0000e+00 },
        SBE26plusStatisticsDataParticleKey.TSS_MAXIMUM_WAVE_HEIGHT: {TYPE: float, VALUE: 1.0893e-02 },
        SBE26plusStatisticsDataParticleKey.TSS_SIGNIFICANT_WAVE_HEIGHT: {TYPE: float, VALUE: 0.0000e+00 },
        SBE26plusStatisticsDataParticleKey.TSS_SIGNIFICANT_WAVE_PERIOD: {TYPE: float, VALUE: 0.0000e+00 },
        SBE26plusStatisticsDataParticleKey.TSS_H1_10: {TYPE: float, VALUE: 0.0000e+00 },
        SBE26plusStatisticsDataParticleKey.TSS_H1_100: {TYPE: float, VALUE: 0.0000e+00 }
    }

    _calibration_sample_parameters = {
        SBE26plusDeviceCalibrationDataParticleKey.PCALDATE: {TYPE: list, VALUE: [2, 4, 2013] },
        SBE26plusDeviceCalibrationDataParticleKey.PU0: {TYPE: float, VALUE: 5.100000e+00 },
        SBE26plusDeviceCalibrationDataParticleKey.PY1: {TYPE: float, VALUE: -3.910859e+03 },
        SBE26plusDeviceCalibrationDataParticleKey.PY2: {TYPE: float, VALUE: -1.070825e+04 },
        SBE26plusDeviceCalibrationDataParticleKey.PY3: {TYPE: float, VALUE:  0.000000e+00  },
        SBE26plusDeviceCalibrationDataParticleKey.PC1: {TYPE: float, VALUE: 6.072786e+02 },
        SBE26plusDeviceCalibrationDataParticleKey.PC2: {TYPE: float, VALUE: 1.000000e+00 },
        SBE26plusDeviceCalibrationDataParticleKey.PC3: {TYPE: float, VALUE: -1.024374e+03 },
        SBE26plusDeviceCalibrationDataParticleKey.PD1: {TYPE: float, VALUE:  2.928000e-02 },
        SBE26plusDeviceCalibrationDataParticleKey.PD2: {TYPE: float, VALUE: 0.000000e+00 },
        SBE26plusDeviceCalibrationDataParticleKey.PT1: {TYPE: float, VALUE: 2.783369e+01 },
        SBE26plusDeviceCalibrationDataParticleKey.PT2: {TYPE: float, VALUE: 6.072020e-01 },
        SBE26plusDeviceCalibrationDataParticleKey.PT3: {TYPE: float, VALUE: 1.821885e+01 },
        SBE26plusDeviceCalibrationDataParticleKey.PT4: {TYPE: float, VALUE: 2.790597e+01 },
        SBE26plusDeviceCalibrationDataParticleKey.FACTORY_M: {TYPE: float, VALUE: 41943.0 },
        SBE26plusDeviceCalibrationDataParticleKey.FACTORY_B: {TYPE: float, VALUE: 2796.2 },
        SBE26plusDeviceCalibrationDataParticleKey.POFFSET: {TYPE: float, VALUE: -1.374000e-01 },
        SBE26plusDeviceCalibrationDataParticleKey.TCALDATE: {TYPE: list, VALUE: [2, 4, 2013] },
        SBE26plusDeviceCalibrationDataParticleKey.TA0: {TYPE: float, VALUE: 1.200000e-04 },
        SBE26plusDeviceCalibrationDataParticleKey.TA1: {TYPE: float, VALUE: 2.558000e-04 },
        SBE26plusDeviceCalibrationDataParticleKey.TA2: {TYPE: float, VALUE: -2.073449e-06 },
        SBE26plusDeviceCalibrationDataParticleKey.TA3: {TYPE: float, VALUE: 1.640089e-07 },
        SBE26plusDeviceCalibrationDataParticleKey.CCALDATE: {TYPE: list, VALUE: [28, 3, 2012] },
        SBE26plusDeviceCalibrationDataParticleKey.CG: {TYPE: float, VALUE: -1.025348e+01 },
        SBE26plusDeviceCalibrationDataParticleKey.CH: {TYPE: float, VALUE: 1.557569e+00 },
        SBE26plusDeviceCalibrationDataParticleKey.CI: {TYPE: float, VALUE: -1.737200e-03 },
        SBE26plusDeviceCalibrationDataParticleKey.CJ: {TYPE: float, VALUE: 2.268000e-04 },
        SBE26plusDeviceCalibrationDataParticleKey.CTCOR: {TYPE: float, VALUE: 3.250000e-06 },
        SBE26plusDeviceCalibrationDataParticleKey.CPCOR: {TYPE: float, VALUE: -9.570000e-08 },
        SBE26plusDeviceCalibrationDataParticleKey.CSLOPE: {TYPE: float, VALUE: 1.000000e+00 }
    }

    _status_sample_parameters = {
        SBE26plusDeviceStatusDataParticleKey.DEVICE_VERSION: {TYPE: unicode, VALUE: u'6.1e' },
        SBE26plusDeviceStatusDataParticleKey.SERIAL_NUMBER: {TYPE: unicode, VALUE: u'1329' },
        SBE26plusDeviceStatusDataParticleKey.DS_DEVICE_DATE_TIME: {TYPE: unicode, VALUE: u'05 Oct 2012  17:19:27' },
        SBE26plusDeviceStatusDataParticleKey.USER_INFO: {TYPE: unicode, VALUE: u'ooi' },
        SBE26plusDeviceStatusDataParticleKey.QUARTZ_PRESSURE_SENSOR_SERIAL_NUMBER: {TYPE: float, VALUE: 122094 },
        SBE26plusDeviceStatusDataParticleKey.QUARTZ_PRESSURE_SENSOR_RANGE: {TYPE: float, VALUE: 300 },
        SBE26plusDeviceStatusDataParticleKey.EXTERNAL_TEMPERATURE_SENSOR: {TYPE: bool, VALUE: False },
        SBE26plusDeviceStatusDataParticleKey.CONDUCTIVITY: {TYPE: bool, VALUE: False },
        SBE26plusDeviceStatusDataParticleKey.IOP_MA: {TYPE: float, VALUE: 7.4 },
        SBE26plusDeviceStatusDataParticleKey.VMAIN_V: {TYPE: float, VALUE: 16.2 },
        SBE26plusDeviceStatusDataParticleKey.VLITH_V: {TYPE: float, VALUE: 9.0 },
        SBE26plusDeviceStatusDataParticleKey.LAST_SAMPLE_P: {TYPE: float, VALUE: 14.5361 },
        SBE26plusDeviceStatusDataParticleKey.LAST_SAMPLE_T: {TYPE: float, VALUE: 23.8155 },
        SBE26plusDeviceStatusDataParticleKey.LAST_SAMPLE_S: {TYPE: float, VALUE: 0.0 },
        SBE26plusDeviceStatusDataParticleKey.TIDE_INTERVAL: {TYPE: int, VALUE: 3.0 },
        SBE26plusDeviceStatusDataParticleKey.TIDE_MEASUREMENT_DURATION: {TYPE: int, VALUE: 60 },
        SBE26plusDeviceStatusDataParticleKey.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS: {TYPE: int, VALUE: 6 },
        SBE26plusDeviceStatusDataParticleKey.WAVE_SAMPLES_PER_BURST: {TYPE: int, VALUE: 512 },
        SBE26plusDeviceStatusDataParticleKey.WAVE_SAMPLES_SCANS_PER_SECOND: {TYPE: float, VALUE: 4.0 },
        SBE26plusDeviceStatusDataParticleKey.USE_START_TIME: {TYPE: bool, VALUE: False },
        SBE26plusDeviceStatusDataParticleKey.USE_STOP_TIME: {TYPE: bool, VALUE: False },
        SBE26plusDeviceStatusDataParticleKey.TIDE_SAMPLES_PER_DAY: {TYPE: float, VALUE: 480.0 },
        SBE26plusDeviceStatusDataParticleKey.WAVE_BURSTS_PER_DAY: {TYPE: float, VALUE: 80.0 },
        SBE26plusDeviceStatusDataParticleKey.MEMORY_ENDURANCE: {TYPE: float, VALUE: 258.0 },
        SBE26plusDeviceStatusDataParticleKey.NOMINAL_ALKALINE_BATTERY_ENDURANCE: {TYPE: float, VALUE: 272.8 },
        SBE26plusDeviceStatusDataParticleKey.TOTAL_RECORDED_TIDE_MEASUREMENTS: {TYPE: float, VALUE: 5982 },
        SBE26plusDeviceStatusDataParticleKey.TOTAL_RECORDED_WAVE_BURSTS: {TYPE: float, VALUE: 4525 },
        SBE26plusDeviceStatusDataParticleKey.TIDE_MEASUREMENTS_SINCE_LAST_START: {TYPE: float, VALUE: 11 },
        SBE26plusDeviceStatusDataParticleKey.WAVE_BURSTS_SINCE_LAST_START: {TYPE: float, VALUE: 1 },
        SBE26plusDeviceStatusDataParticleKey.WAVE_SAMPLES_DURATION: {TYPE: int, VALUE: 128 },
        SBE26plusDeviceStatusDataParticleKey.TXREALTIME: {TYPE: bool, VALUE: True },
        SBE26plusDeviceStatusDataParticleKey.TXWAVEBURST: {TYPE: bool, VALUE: True },
        SBE26plusDeviceStatusDataParticleKey.TXWAVESTATS: {TYPE: bool, VALUE: True },
        SBE26plusDeviceStatusDataParticleKey.NUM_WAVE_SAMPLES_PER_BURST_FOR_WAVE_STASTICS: {TYPE: int, VALUE: 512 },
        SBE26plusDeviceStatusDataParticleKey.USE_MEASURED_TEMP_AND_CONDUCTIVITY_FOR_DENSITY_CALC: {TYPE: bool, VALUE: False  },
        SBE26plusDeviceStatusDataParticleKey.PRESSURE_SENSOR_HEIGHT_FROM_BOTTOM: {TYPE: float, VALUE: 10.0 },
        SBE26plusDeviceStatusDataParticleKey.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND: {TYPE: int, VALUE: 5 },
        SBE26plusDeviceStatusDataParticleKey.MIN_ALLOWABLE_ATTENUATION: {TYPE: float, VALUE: 0.0025 },
        SBE26plusDeviceStatusDataParticleKey.MIN_PERIOD_IN_AUTO_SPECTRUM: {TYPE: float, VALUE: 0.0e+00 },
        SBE26plusDeviceStatusDataParticleKey.MAX_PERIOD_IN_AUTO_SPECTRUM: {TYPE: float, VALUE: 1.0e+06 },
        SBE26plusDeviceStatusDataParticleKey.HANNING_WINDOW_CUTOFF: {TYPE: float, VALUE: 0.10 },
        SBE26plusDeviceStatusDataParticleKey.SHOW_PROGRESS_MESSAGES: {TYPE: bool, VALUE: True },
        SBE26plusDeviceStatusDataParticleKey.STATUS: {TYPE: unicode, VALUE: u'stopped by user' },
        SBE26plusDeviceStatusDataParticleKey.LOGGING: {TYPE: bool, VALUE: False },
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
    #   Data Particle Parameters Methods
    ###
    def assert_sample_data_particle(self, data_particle):
        '''
        Verify a particle is a know particle to this driver and verify the particle is
        correct
        @param data_particle: Data particle of unkown type produced by the driver
        '''
        if (isinstance(data_particle, SBE26plusTideSampleDataParticle)):
            self.assert_particle_tide_sample(data_particle)
        elif (isinstance(data_particle, SBE26plusWaveBurstDataParticle)):
            self.assert_particle_wave_burst(data_particle)
        elif (isinstance(data_particle, SBE26plusStatisticsDataParticle)):
            self.assert_particle_statistics(data_particle)
        elif (isinstance(data_particle, SBE26plusDeviceCalibrationDataParticle)):
            self.assert_particle_device_calibration(data_particle)
        elif (isinstance(data_particle, SBE26plusDeviceStatusDataParticle)):
            self.assert_particle_device_status(data_particle)
        else:
            log.error("Unknown Particle Detected: %s" % data_particle)
            self.assertFalse(True)

    def assert_particle_tide_sample(self, data_particle, verify_values = False):
        '''
        Verify a take sample data particle
        @param data_particle:  SBE26plusTideSampleDataParticle data particle
        @param verify_values:  bool, should we verify parameter values
        '''
        self.assert_data_particle_header(data_particle, DataParticleType.TIDE_PARSED)
        self.assert_data_particle_parameters(data_particle, self._tide_sample_parameters, verify_values)


    def assert_particle_wave_burst(self, data_particle, verify_values = False):
        '''
        Verify a take sample data particle
        @param data_particle:  SBE26plusWaveBurstDataParticle data particle
        @param verify_values:  bool, should we verify parameter values
        '''
        self.assert_data_particle_header(data_particle, DataParticleType.WAVE_BURST)
        self.assert_data_particle_parameters(data_particle, self._wave_sample_parameters, verify_values)

    def assert_particle_statistics(self, data_particle, verify_values = False):
        '''
        Verify a take sample data particle
        @param data_particle:  SBE26plusStatisticsDataParticle data particle
        @param verify_values:  bool, should we verify parameter values
        '''
        self.assert_data_particle_header(data_particle, DataParticleType.STATISTICS)
        self.assert_data_particle_parameters(data_particle, self._statistics_sample_parameters, verify_values)

    def assert_particle_device_calibration(self, data_particle, verify_values = False):
        '''
        Verify a take sample data particle
        @param data_particle:  SBE26plusDeviceCalibrationDataParticle data particle
        @param verify_values:  bool, should we verify parameter values
        '''
        self.assert_data_particle_header(data_particle, DataParticleType.DEVICE_CALIBRATION)
        self.assert_data_particle_parameters(data_particle, self._calibration_sample_parameters, verify_values)

    def assert_particle_device_status(self, data_particle, verify_values = False):
        '''
        Verify a take sample data particle
        @param data_particle:  SBE26plusDeviceStatusDataParticle data particle
        @param verify_values:  bool, should we verify parameter values
        '''
        self.assert_data_particle_header(data_particle, DataParticleType.DEVICE_STATUS)
        self.assert_data_particle_parameters(data_particle, self._status_sample_parameters, verify_values)


###############################################################################
#                                UNIT TESTS                                   #
#         Unit tests test the method calls and parameters using Mock.         #
# 1. Pick a single method within the class.                                   #
# 2. Create an instance of the class                                          #
# 3. If the method to be tested tries to call out, over-ride the offending    #
#    method with a mock                                                       #
# 4. Using above, try to cover all paths through the functions                #
# 5. Negative testing if at all possible.                                     #
###############################################################################
@attr('UNIT', group='mi')
class SeaBird26PlusUnitTest(SeaBirdUnitTest, SeaBird26PlusMixin):
    def setUp(self):
        SeaBirdUnitTest.setUp(self)

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

        self.assert_chunker_sample(chunker, SAMPLE_TIDE_DATA)
        self.assert_chunker_sample_with_noise(chunker, SAMPLE_TIDE_DATA)
        self.assert_chunker_fragmented_sample(chunker, SAMPLE_TIDE_DATA)
        self.assert_chunker_combined_sample(chunker, SAMPLE_TIDE_DATA)

        self.assert_chunker_sample(chunker, SAMPLE_WAVE_BURST)
        self.assert_chunker_sample_with_noise(chunker, SAMPLE_WAVE_BURST)
        self.assert_chunker_fragmented_sample(chunker, SAMPLE_WAVE_BURST, 1024)
        self.assert_chunker_combined_sample(chunker, SAMPLE_WAVE_BURST)

        self.assert_chunker_sample(chunker, SAMPLE_STATISTICS)
        self.assert_chunker_sample_with_noise(chunker, SAMPLE_STATISTICS)
        self.assert_chunker_fragmented_sample(chunker, SAMPLE_STATISTICS, 512)
        self.assert_chunker_combined_sample(chunker, SAMPLE_STATISTICS)

        self.assert_chunker_sample(chunker, SAMPLE_DEVICE_CALIBRATION)
        self.assert_chunker_sample_with_noise(chunker, SAMPLE_DEVICE_CALIBRATION)
        self.assert_chunker_fragmented_sample(chunker, SAMPLE_DEVICE_CALIBRATION, 512)
        self.assert_chunker_combined_sample(chunker, SAMPLE_DEVICE_CALIBRATION)

        self.assert_chunker_sample(chunker, SAMPLE_DEVICE_STATUS) 
        self.assert_chunker_sample_with_noise(chunker, SAMPLE_DEVICE_STATUS)
        self.assert_chunker_fragmented_sample(chunker, SAMPLE_DEVICE_STATUS, 512)
        self.assert_chunker_combined_sample(chunker, SAMPLE_DEVICE_STATUS)


    def test_got_data(self):
        """
        Verify sample data passed through the got data method produces the correct data particles
        """
        # Create and initialize the instrument driver with a mock port agent
        driver = InstrumentDriver(self._got_data_event_callback)
        self.assert_initialize_driver(driver)

        self.assert_raw_particle_published(driver, True)

        # Start validating data particles
        self.assert_particle_published(driver, SAMPLE_TIDE_DATA, self.assert_particle_tide_sample, True)
        self.assert_particle_published(driver, SAMPLE_WAVE_BURST, self.assert_particle_wave_burst, True)
        self.assert_particle_published(driver, SAMPLE_STATISTICS, self.assert_particle_statistics, True)
        self.assert_particle_published(driver, SAMPLE_DEVICE_CALIBRATION, self.assert_particle_device_calibration, True)
        self.assert_particle_published(driver, SAMPLE_DEVICE_STATUS, self.assert_particle_device_status, True)


    def test_protocol_filter_capabilities(self):
        """
        This tests driver filter_capabilities.
        Iterate through available capabilities, and verify that they can pass successfully through the filter.
        Test silly made up capabilities to verify they are blocked by filter.
        """
        my_event_callback = Mock(spec="UNKNOWN WHAT SHOULD GO HERE FOR evt_callback")
        protocol = Protocol(Prompt, NEWLINE, my_event_callback)
        driver_capabilities = Capability().list()
        test_capabilities = Capability().list()

        # Add a bogus capability that will be filtered out.
        test_capabilities.append("BOGUS_CAPABILITY")

        # Verify "BOGUS_CAPABILITY was filtered out
        self.assertEquals(driver_capabilities, protocol._filter_capabilities(test_capabilities))


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

        # Verify the parameter definitions
        self.assert_driver_parameter_definition(driver, self._driver_parameters)


    def test_capabilities(self):
        """
        Verify the FSM reports capabilities as expected.  All states defined in this dict must
        also be defined in the protocol FSM.
        """
        capabilities = {
            ProtocolState.UNKNOWN: ['DRIVER_EVENT_DISCOVER', 'DRIVER_FORCE_STATE'],
            ProtocolState.COMMAND: ['DRIVER_EVENT_ACQUIRE_SAMPLE',
                                    'DRIVER_EVENT_ACQUIRE_STATUS',
                                    'DRIVER_EVENT_CLOCK_SYNC',
                                    'DRIVER_EVENT_GET',
                                    'DRIVER_EVENT_SET',
                                    'DRIVER_EVENT_START_AUTOSAMPLE',
                                    'DRIVER_EVENT_START_DIRECT',
                                    'PROTOCOL_EVENT_ACQUIRE_CONFIGURATION',
                                    'PROTOCOL_EVENT_INIT_LOGGING',
                                    'PROTOCOL_EVENT_QUIT_SESSION',
                                    'PROTOCOL_EVENT_SEND_LAST_SAMPLE',
                                    'PROTOCOL_EVENT_SEND_LAST_SAMPLE_SLEEP',
                                    'PROTOCOL_EVENT_SETSAMPLING'],
            ProtocolState.AUTOSAMPLE: ['DRIVER_EVENT_GET', 'DRIVER_EVENT_STOP_AUTOSAMPLE'],
            ProtocolState.DIRECT_ACCESS: ['DRIVER_EVENT_STOP_DIRECT', 'EXECUTE_DIRECT']
        }

        driver = InstrumentDriver(self._got_data_event_callback)
        self.assert_capabilities(driver, capabilities)


###############################################################################
#                            INTEGRATION TESTS                                #
#     Integration test test the direct driver / instrument interaction        #
#     but making direct calls via zeromq.                                     #
#     - Common Integration tests test the driver through the instrument agent #
#     and common for all drivers (minimum requirement for ION ingestion)      #
###############################################################################
@attr('INT', group='mi')
class SeaBird26PlusIntegrationTest(SeaBirdIntegrationTest, SeaBird26PlusMixin):
    def setUp(self):
        SeaBirdIntegrationTest.setUp(self)

    ###
    #    Add instrument specific integration tests
    ###

    def test_parameters(self):
        """
        Test driver parameters and verify their type.  Startup parameters also verify the parameter
        value.  This test confirms that parameters are being read/converted properly and that
        the startup has been applied.
        """
        self.assert_initialize_driver()
        reply = self.driver_client.cmd_dvr('get_resource', Parameter.ALL)
        self.assert_driver_parametes(reply, True)

    # PASSES
    def test_set(self):
        """
        Test all set commands. Verify all exception cases.
        """
        self.assert_initialize_driver()

        # The clock in this instrument is a little odd.  It looks like if you wait until the edge of a second
        # to set it, it immediately ticks after the set, making it off by 1.  For now we will accept this
        # behavior, but we need to check this behavior on all SBE instruments.
        # @todo Revisit clock sync across SBE instruments
        set_time = get_timestamp_delayed("%d %b %Y  %H:%M:%S")
        # One second later
        expected_time = get_timestamp_delayed("%d %b %Y  %H:%M:%S")
        self.assert_set(Parameter.DS_DEVICE_DATE_TIME, set_time, no_get=True)
        self.assert_get(Parameter.DS_DEVICE_DATE_TIME, expected_time.upper())

        ###
        #   Instrument Parameteres
        ###
        self.assert_set(Parameter.USER_INFO, 'iontest'.upper())

        ###
        #   Set Sample Parameters
        ###
        # Tested in another method

        ###
        #   Read only parameters
        ###
        self.assert_set_readonly(Parameter.DEVICE_VERSION)
        self.assert_set_readonly(Parameter.SERIAL_NUMBER)
        self.assert_set_readonly(Parameter.QUARTZ_PRESSURE_SENSOR_SERIAL_NUMBER)
        self.assert_set_readonly(Parameter.QUARTZ_PRESSURE_SENSOR_RANGE)
        self.assert_set_readonly(Parameter.EXTERNAL_TEMPERATURE_SENSOR)
        self.assert_set_readonly(Parameter.CONDUCTIVITY)
        self.assert_set_readonly(Parameter.IOP_MA)
        self.assert_set_readonly(Parameter.VMAIN_V)
        self.assert_set_readonly(Parameter.VLITH_V)
        self.assert_set_readonly(Parameter.LAST_SAMPLE_P)
        self.assert_set_readonly(Parameter.LAST_SAMPLE_T)
        self.assert_set_readonly(Parameter.LAST_SAMPLE_S)
        self.assert_set_readonly(Parameter.TXREALTIME)
        self.assert_set_readonly(Parameter.TXWAVEBURST)
        self.assert_set_readonly(Parameter.SHOW_PROGRESS_MESSAGES)
        self.assert_set_readonly(Parameter.STATUS)
        self.assert_set_readonly(Parameter.LOGGING)

    def test_set_sampling(self):
        """
        @brief Test device setsampling.

        setsampling functionality now handled via set.  Below test converted to use set.
        This tests assumes Conductivity is set to false as described in the IOS, we verify
        this, but don't set it because this is a startup parameter.

        Test setting parameters, including bad parameter tests, for all parameters in the set
        sampling when txwavestats is set to false.

        Parameter set:
        * Tide interval (integer minutes)
            - Range 17 - 720
                *NOTE* TIDE INTERVAL WILL BE RESET TO:
                (Number of wave samples per burst) * (wave sample duration) + 10 sec + calculation time
                if not already larger....

        * Tide measurement duration (seconds)
            - Range: 10 - 1020 sec
        * Measure wave burst after every N tide samples
            - Range 1 - 10,000
        * Number of wave samples per burst
            - Range 4 - 60,000
        * wave sample duration
            - Range [0.25, 0.5, 0.75, 1.0]
        * use start time - Not set, driver hard codes to false
            - Range [y, n]
        * use stop time - Not set, driver hard codes to false
            - Range [y, n]
        * TXWAVESTATS (real-time wave statistics)
            - Set to False for this test
        """
        self.assert_initialize_driver()
        self.assert_get(Parameter.CONDUCTIVITY, False)


        #1: TXWAVESTATS = N
        # WORKS
        #self.assert_set_sampling_no_txwavestats()
        #2: TXWAVESTATS = Y, USE_MEASURED_TEMP_AND_CONDUCTIVITY_FOR_DENSITY_CALC=N
        self.assert_set_sampling_txwavestats_dont_use_conductivity()  # issue with preload of USE_MEASURED_TEMP_FOR_DENSITY_CALC instead of USE_MEASURED_TEMP_AND_CONDUCTIVITY_FOR_DENSITY_CALC
        #3: TXWAVESTATS = Y, USE_MEASURED_TEMP_AND_CONDUCTIVITY_FOR_DENSITY_CALC=Y
        #self.assert_set_sampling_txwavestats_use_conductivity()




    def assert_set_sampling_no_txwavestats(self):
        log.debug("setsampling Test 1 - TXWAVESTATS = N.")
        sampling_params = {
            Parameter.TIDE_INTERVAL: 18,
            Parameter.TIDE_MEASUREMENT_DURATION: 60,
            Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS: 6000,
            Parameter.WAVE_SAMPLES_PER_BURST: 1000,
            
            # todo: The get command doesn't work for this paramter since it is
            # set to a derived parameter.
            # Parameter.WAVE_SAMPLES_SCANS_PER_SECOND: 4,
            Parameter.TXWAVESTATS: False,
        }

        # First tests to verify we can set all parameters properly
        self.assert_set_bulk(sampling_params)

        # Tide interval parameter.  Check edges, out of range and invalid data
        #    * Tide interval (integer minutes)
        #        - Range 17 - 720
        sampling_params[Parameter.TIDE_INTERVAL] = 17
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_INTERVAL] = 720
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_INTERVAL] = 16
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_INTERVAL] = 721
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.TIDE_INTERVAL] = "foo"
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.TIDE_INTERVAL] = 18

        # Tide measurement duration.  Check edges, out of range and invalid data
        #    * Tide measurement duration (seconds)
        #        - Range: 10 - 1020 sec
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = 10
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = 1020
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = 9
        self.assert_set_bulk_exception(sampling_params)
        # apparently NOT and edge case...
        #sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = 1021
        #self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = "foo"
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = 60

        # Tide samples between wave bursts.  Check edges, out of range and invalid data
        #   * Measure wave burst after every N tide samples
        #       - Range 1 - 10,000
        sampling_params[Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS] = 1
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS] = 10000
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS] = 0
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS] = 10001
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS] = "foo"
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS] = 6000

        # Test a good value
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 1000
        self.assert_set_bulk(sampling_params)

        # Wave samples per burst.  Check edges, out of range and invalid data
        #   * Number of wave samples per burst
        #       - Range 4 - 60,000 *MUST BE MULTIPLE OF 4*
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 10
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 43200   # If we set this this high
        sampling_params[Parameter.TIDE_INTERVAL] = 181              # ... we need to set
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = 10860# ... we need to set
        self.assert_set_bulk(sampling_params)

        # return them to baseline testing values.
        sampling_params[Parameter.TIDE_INTERVAL] = 17
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = 60

        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 9
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 43201
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = "foo"
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 10
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = -1
        self.assert_set_bulk_exception(sampling_params)

        #    * wave scans per second
        #        - Range [4, 2, 1.33, 1]
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 4
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = 2.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = 1.33
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = 1.0
        self.assert_set_bulk_exception(sampling_params)

        # test bad values
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = 3
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = 0
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = -1
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = 5
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = "foo"
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 4
        self.assert_set_bulk_exception(sampling_params)

    def set_baseline_txwavestats_use_conductivity(self):
        sampling_params = {
            Parameter.TIDE_INTERVAL: 18,
            Parameter.TIDE_MEASUREMENT_DURATION: 60,
            Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS: 8,
            Parameter.WAVE_SAMPLES_PER_BURST: 512,
            Parameter.WAVE_SAMPLES_SCANS_PER_SECOND: 4.0,
            Parameter.TXWAVESTATS: True,
            Parameter.USE_MEASURED_TEMP_AND_CONDUCTIVITY_FOR_DENSITY_CALC: True,
            Parameter.PRESSURE_SENSOR_HEIGHT_FROM_BOTTOM: 10.0,
            Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND: 1,
            Parameter.MIN_ALLOWABLE_ATTENUATION: 1.0000,
            Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM: 0.0,
            Parameter.MAX_PERIOD_IN_AUTO_SPECTRUM: 1.0,
            Parameter.HANNING_WINDOW_CUTOFF: 1.0
        }
        # Set all parameters to a known ground state
        self.assert_set_bulk(sampling_params)
        return sampling_params
        
    def assert_set_sampling_txwavestats_use_conductivity(self):
        log.debug("setsampling Test 3 - TXWAVESTATS = Y. CONDUCTIVITY = Y")
        self.set_baseline_txwavestats_use_conductivity()
        
        """
        use measured temperature for density calculation (y/n) = n, new value = y
        height of pressure sensor from bottom (meters) = 10.0, new value =
        number of spectral estimates for each frequency band = 1, new value =
        minimum allowable attenuation = 1.0000, new value =
        minimum period (seconds) to use in auto-spectrum = 0.0e+00, new value =
        maximum period (seconds) to use in auto-spectrum = 1.0e+00, new value =
        hanning window cutoff = 1.00, new value =
        """
        

        # First tests to verify we can set all parameters properly
        sampling_params = self.set_baseline_txwavestats_use_conductivity()

        # Tide interval parameter.  Check edges, out of range and invalid data
        #    * Tide interval (integer minutes)
        #        - Range 17 - 720
        sampling_params[Parameter.TIDE_INTERVAL] = 17
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_INTERVAL] = 720
        self.assert_set_bulk(sampling_params) #was bombing here timeout
        sampling_params[Parameter.TIDE_INTERVAL] = 16
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_INTERVAL] = 721
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.TIDE_INTERVAL] = "foo"
        self.assert_set_bulk_exception(sampling_params)
        
        # set to known good
        sampling_params = self.set_baseline_txwavestats_use_conductivity()
        
        # Tide measurement duration.  Check edges, out of range and invalid data
        #    * Tide measurement duration (seconds)
        #        - Range: 10 - 1020 sec
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = 10
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = 1020
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = 9
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = 1021
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = "foo"
        self.assert_set_bulk_exception(sampling_params)
        
        # set to known good
        sampling_params = self.set_baseline_txwavestats_use_conductivity()
        
        # Tide samples between wave bursts.  Check edges, out of range and invalid data
        #   * Measure wave burst after every N tide samples
        #       - Range 1 - 10,000
        sampling_params[Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS] = 1
        self.assert_set_bulk(sampling_params) # in wakeup.
        sampling_params[Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS] = 10000
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS] = 0
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS] = 10001
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS] = "foo"
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS] = 6000

        # set to known good
        sampling_params = self.set_baseline_txwavestats_use_conductivity()
        
        # Test a good value
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 1000
        self.assert_set_bulk(sampling_params)

        # Wave samples per burst.  Check edges, out of range and invalid data
        #   * Number of wave samples per burst
        #       - Range 4 - 60,000 *MUST BE MULTIPLE OF 4*
        sampling_params[Parameter.TIDE_INTERVAL] = 720              # required for 60000
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 60000
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 10
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 36000   # If we set this this high
        sampling_params[Parameter.TIDE_INTERVAL] = 720              # ... we need to set <--- was 1001
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = 10860# ... we need to set
        self.assert_set_bulk(sampling_params)

        # set to known good
        sampling_params = self.set_baseline_txwavestats_use_conductivity()

        # 512 - 60,000 in multiple of 4
        
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = -1
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 3
        self.assert_set_bulk_exception(sampling_params)     
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 4      
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 508      
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 511     
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 43201
        self.assert_set_bulk_exception(sampling_params)
        
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 60001
        self.assert_set_bulk_exception(sampling_params)           
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = "bar"
        self.assert_set_bulk_exception(sampling_params)
        
        # set to known good
        sampling_params = self.set_baseline_txwavestats_use_conductivity()

        
        #    * wave scans per second
        #        - Range [4, 2, 1.33, 1]
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = 2.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = 1.33
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = 1.0
        self.assert_set_bulk(sampling_params)
        
        # test bad values
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = 3
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = 0
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = -1
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = 5
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = "foo"
        self.assert_set_bulk_exception(sampling_params)
       
        # set to known good
        sampling_params = self.set_baseline_txwavestats_use_conductivity()
        
        #
        # New Section
        #
        
        sampling_params[Parameter.USE_MEASURED_TEMP_AND_CONDUCTIVITY_FOR_DENSITY_CALC] = False
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.USE_MEASURED_TEMP_AND_CONDUCTIVITY_FOR_DENSITY_CALC] = True
        self.assert_set_bulk(sampling_params)
        # set to known good
        sampling_params = self.set_baseline_txwavestats_use_conductivity()
        
        
        sampling_params[Parameter.PRESSURE_SENSOR_HEIGHT_FROM_BOTTOM] = 0
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.PRESSURE_SENSOR_HEIGHT_FROM_BOTTOM] = 1000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.PRESSURE_SENSOR_HEIGHT_FROM_BOTTOM] = 100000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.PRESSURE_SENSOR_HEIGHT_FROM_BOTTOM] = -1.0
        self.assert_set_bulk_exception(sampling_params)
        
        # set to known good
        sampling_params = self.set_baseline_txwavestats_use_conductivity()
        
        # int.
        sampling_params[Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND] = -1
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND] = 0
        self.assert_set_bulk(sampling_params)
        
        sampling_params[Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND] = 10
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND] = 100000
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND] = 10.0
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND] = "car"
        self.assert_set_bulk_exception(sampling_params)
        
        # set to known good
        sampling_params = self.set_baseline_txwavestats_use_conductivity()
        
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = 0.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = 0.0025
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = 10.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = 100.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = 1000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = 10000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = 100000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = 100
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = "tar"
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = 0.0025
        
        # set to known good
        sampling_params = self.set_baseline_txwavestats_use_conductivity()
        
        
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = -1
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = 0
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = 0.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MAX_PERIOD_IN_AUTO_SPECTRUM] = float(0.0001)
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = 1.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = 10.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = 100.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = 1000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = 10000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MAX_PERIOD_IN_AUTO_SPECTRUM] = 100000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = "far"
        self.assert_set_bulk_exception(sampling_params)
        
        # set to known good
        sampling_params = self.set_baseline_txwavestats_use_conductivity()
        
        
        # The manual only shows 0.10 as a value (assert float)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = 1.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = -1
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = 0
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = 0.0
        self.assert_set_bulk(sampling_params)
        # Rounds to 0.00
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = float(0.0001) 
        self.assert_set_bulk_exception(sampling_params)
        # Rounds to 0.01
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = float(0.006) 
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = 1.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = 10.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = 100.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = 1000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = 10000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = 100000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = "far"
        self.assert_set_bulk_exception(sampling_params)
        
        # set to known good
        sampling_params = self.set_baseline_txwavestats_use_conductivity()
        
    def set_baseline_txwavestats_dont_use_conductivity(self):
        sampling_params = {
            Parameter.TIDE_INTERVAL: 18,
            Parameter.TIDE_MEASUREMENT_DURATION: 60,
            Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS: 8,
            Parameter.WAVE_SAMPLES_PER_BURST: 512,
            Parameter.WAVE_SAMPLES_SCANS_PER_SECOND: 4.0,
            Parameter.TXWAVESTATS: True,
            Parameter.USE_MEASURED_TEMP_AND_CONDUCTIVITY_FOR_DENSITY_CALC: False,
            
            # TODO: enable next 2 params, and balance the set then complete the test.
            # Only 2 params that are different.   ****************************************************************************************************************************************************
            Parameter.AVERAGE_WATER_TEMPERATURE_ABOVE_PRESSURE_SENSOR: 15.0,
            Parameter.AVERAGE_SALINITY_ABOVE_PRESSURE_SENSOR: 35.0,        
            Parameter.NUM_WAVE_SAMPLES_PER_BURST_FOR_WAVE_STASTICS: 512,
            Parameter.PRESSURE_SENSOR_HEIGHT_FROM_BOTTOM: 10.0,
            Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND: 1,
            Parameter.MIN_ALLOWABLE_ATTENUATION: 1.0000,
            Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM: 0.0,
            Parameter.MAX_PERIOD_IN_AUTO_SPECTRUM: 1.0,
            Parameter.HANNING_WINDOW_CUTOFF: 1.0
        }
        # Set all parameters to a known ground state
        self.assert_set_bulk(sampling_params)
        return sampling_params
    
    def assert_set_sampling_txwavestats_dont_use_conductivity(self):
        log.debug("setsampling Test 2 - TXWAVESTATS = Y. CONDUCTIVITY = N")
        
        """
        use measured temperature for density calculation (y/n) = y, new value = n
        average water temperature above the pressure sensor (deg C) = 15.0, new value =
        average salinity above the pressure sensor (PSU) = 37.6, new value =
        height of pressure sensor from bottom (meters) = 10.0, new value =
        number of spectral estimates for each frequency band = 1, new value =
        minimum allowable attenuation = 1.0000, new value =
        minimum period (seconds) to use in auto-spectrum = 0.0e+00, new value =
        maximum period (seconds) to use in auto-spectrum = 1.0e+00, new value =
        hanning window cutoff = 1.00, new value =
        """
        # set to known good
        sampling_params = self.set_baseline_txwavestats_dont_use_conductivity()
            
            
            
            
        sampling_params[Parameter.AVERAGE_WATER_TEMPERATURE_ABOVE_PRESSURE_SENSOR] = -274.0 # -1 Kelvin?
        self.assert_set_bulk(sampling_params)    
        sampling_params[Parameter.AVERAGE_WATER_TEMPERATURE_ABOVE_PRESSURE_SENSOR] = -273.0 # 0 Kelvin?
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.AVERAGE_WATER_TEMPERATURE_ABOVE_PRESSURE_SENSOR] = -100.0 
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.AVERAGE_WATER_TEMPERATURE_ABOVE_PRESSURE_SENSOR] = -30.0 
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.AVERAGE_WATER_TEMPERATURE_ABOVE_PRESSURE_SENSOR] = -1.0 
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.AVERAGE_WATER_TEMPERATURE_ABOVE_PRESSURE_SENSOR] = 0.0 
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.AVERAGE_WATER_TEMPERATURE_ABOVE_PRESSURE_SENSOR] = 30.0 
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.AVERAGE_WATER_TEMPERATURE_ABOVE_PRESSURE_SENSOR] = 100.0 # if it gets hotter than this, we are likely all dead...
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.AVERAGE_WATER_TEMPERATURE_ABOVE_PRESSURE_SENSOR] = 500.0 # 500 C getting warmer
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.AVERAGE_WATER_TEMPERATURE_ABOVE_PRESSURE_SENSOR] = 32767.0 # 32767 C, it's a dry heat
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.AVERAGE_WATER_TEMPERATURE_ABOVE_PRESSURE_SENSOR] = "foo"
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.AVERAGE_WATER_TEMPERATURE_ABOVE_PRESSURE_SENSOR] = True
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.AVERAGE_WATER_TEMPERATURE_ABOVE_PRESSURE_SENSOR] = int(1)
        self.assert_set_bulk_exception(sampling_params)
        # set to known good
        sampling_params = self.set_baseline_txwavestats_dont_use_conductivity()
        
        sampling_params[Parameter.AVERAGE_SALINITY_ABOVE_PRESSURE_SENSOR] = -1000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.AVERAGE_SALINITY_ABOVE_PRESSURE_SENSOR] = -100.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.AVERAGE_SALINITY_ABOVE_PRESSURE_SENSOR] = -10.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.AVERAGE_SALINITY_ABOVE_PRESSURE_SENSOR] = 0.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.AVERAGE_SALINITY_ABOVE_PRESSURE_SENSOR] = 35.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.AVERAGE_SALINITY_ABOVE_PRESSURE_SENSOR] = 100.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.AVERAGE_SALINITY_ABOVE_PRESSURE_SENSOR] = 1000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.AVERAGE_SALINITY_ABOVE_PRESSURE_SENSOR] = "foo"
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.AVERAGE_SALINITY_ABOVE_PRESSURE_SENSOR] = True
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.AVERAGE_SALINITY_ABOVE_PRESSURE_SENSOR] = int(1)
        self.assert_set_bulk_exception(sampling_params)
        # set to known good
        sampling_params = self.set_baseline_txwavestats_dont_use_conductivity()
        
        # Tide interval parameter.  Check edges, out of range and invalid data
        #    * Tide interval (integer minutes)
        #        - Range 17 - 720
        sampling_params[Parameter.TIDE_INTERVAL] = 17
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_INTERVAL] = 720
        self.assert_set_bulk(sampling_params) #was bombing here timeout
        sampling_params[Parameter.TIDE_INTERVAL] = 16
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_INTERVAL] = 721
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.TIDE_INTERVAL] = "foo"
        self.assert_set_bulk_exception(sampling_params)
        
        # set to known good
        sampling_params = self.set_baseline_txwavestats_dont_use_conductivity()
        
        # Tide measurement duration.  Check edges, out of range and invalid data
        #    * Tide measurement duration (seconds)
        #        - Range: 10 - 1020 sec
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = 10 # <--- was 60, should have been 10
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = 1020
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = 9
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = 1021
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = "foo"
        self.assert_set_bulk_exception(sampling_params)
        
        # set to known good
        sampling_params = self.set_baseline_txwavestats_dont_use_conductivity()
        
        # Tide samples between wave bursts.  Check edges, out of range and invalid data
        #   * Measure wave burst after every N tide samples
        #       - Range 1 - 10,000
        sampling_params[Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS] = 1
        self.assert_set_bulk(sampling_params) # in wakeup.
        sampling_params[Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS] = 10000
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS] = 0
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS] = 10001
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS] = "foo"
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS] = 6000

        # set to known good
        sampling_params = self.set_baseline_txwavestats_dont_use_conductivity()
        
        # Test a good value
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 1000
        self.assert_set_bulk(sampling_params)

        # Wave samples per burst.  Check edges, out of range and invalid data
        #   * Number of wave samples per burst
        #       - Range 4 - 60,000 *MUST BE MULTIPLE OF 4*
        sampling_params[Parameter.TIDE_INTERVAL] = 720              # required for 60000
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 60000
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 10
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 36000   # If we set this this high
        sampling_params[Parameter.TIDE_INTERVAL] = 720              # ... we need to set <--- was 1001
        sampling_params[Parameter.TIDE_MEASUREMENT_DURATION] = 10860# ... we need to set
        self.assert_set_bulk(sampling_params)

        # set to known good
        sampling_params = self.set_baseline_txwavestats_dont_use_conductivity()

        # 512 - 60,000 in multiple of 4
        
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = -1
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 3
        self.assert_set_bulk_exception(sampling_params)     
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 4      
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 508      
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 511     
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 43201
        self.assert_set_bulk_exception(sampling_params)
        
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = 60001
        self.assert_set_bulk_exception(sampling_params)           
        sampling_params[Parameter.WAVE_SAMPLES_PER_BURST] = "bar"
        self.assert_set_bulk_exception(sampling_params)
        
        # set to known good
        sampling_params = self.set_baseline_txwavestats_dont_use_conductivity()

        
        # Wave samples per burst.  Check edges, out of range and invalid data
        #    * wave sample duration=
        #        - Range [0.25, 0.5, 0.75, 1.0]
        
        
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = 2.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = 1.33
        self.assert_set_bulk(sampling_params)                           
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = 1.0
        self.assert_set_bulk(sampling_params)
        
        # test bad values
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = 3
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = 0
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = -1
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = 5
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = "foo"
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.WAVE_SAMPLES_SCANS_PER_SECOND] = False
        self.assert_set_bulk_exception(sampling_params)
       
        # set to known good
        sampling_params = self.set_baseline_txwavestats_dont_use_conductivity()
        
        #
        # New Section
        #
        
        sampling_params[Parameter.USE_MEASURED_TEMP_AND_CONDUCTIVITY_FOR_DENSITY_CALC] = False
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.USE_MEASURED_TEMP_AND_CONDUCTIVITY_FOR_DENSITY_CALC] = True
        self.assert_set_bulk(sampling_params)
        
        sampling_params[Parameter.USE_MEASURED_TEMP_AND_CONDUCTIVITY_FOR_DENSITY_CALC] = 1
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.USE_MEASURED_TEMP_AND_CONDUCTIVITY_FOR_DENSITY_CALC] = float(1.0)
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.USE_MEASURED_TEMP_AND_CONDUCTIVITY_FOR_DENSITY_CALC] = "bar"
        self.assert_set_bulk_exception(sampling_params)
        
        
        # set to known good
        sampling_params = self.set_baseline_txwavestats_dont_use_conductivity()
        
        
        sampling_params[Parameter.PRESSURE_SENSOR_HEIGHT_FROM_BOTTOM] = 0
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.PRESSURE_SENSOR_HEIGHT_FROM_BOTTOM] = 1000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.PRESSURE_SENSOR_HEIGHT_FROM_BOTTOM] = 100000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.PRESSURE_SENSOR_HEIGHT_FROM_BOTTOM] = -1.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.PRESSURE_SENSOR_HEIGHT_FROM_BOTTOM] = "foo"
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.PRESSURE_SENSOR_HEIGHT_FROM_BOTTOM] = True
        self.assert_set_bulk_exception(sampling_params)
        
        # set to known good
        sampling_params = self.set_baseline_txwavestats_dont_use_conductivity()
        
        # int.
        sampling_params[Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND] = -1
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND] = 0
        self.assert_set_bulk(sampling_params)
        
        sampling_params[Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND] = 10
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND] = 100000
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND] = 10.0
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND] = "car"
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND] = True
        self.assert_set_bulk_exception(sampling_params)
        
        # set to known good
        sampling_params = self.set_baseline_txwavestats_dont_use_conductivity()
        
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = 0.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = 0.0025
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = 10.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = 100.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = 1000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = 10000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = 100000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = 100
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = "tar"
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.MIN_ALLOWABLE_ATTENUATION] = True
        self.assert_set_bulk_exception(sampling_params)

        
        # set to known good
        sampling_params = self.set_baseline_txwavestats_dont_use_conductivity()
        
        
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = -1
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = 0
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = 0.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MAX_PERIOD_IN_AUTO_SPECTRUM] = float(0.0001)
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = 1.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = 10.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = 100.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = 1000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = 10000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MAX_PERIOD_IN_AUTO_SPECTRUM] = 100000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = "far"
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM] = True
        self.assert_set_bulk_exception(sampling_params)
        
        # set to known good
        sampling_params = self.set_baseline_txwavestats_dont_use_conductivity()
        
        
        # The manual only shows 0.10 as a value (assert float)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = 1.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = -1
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = 0
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = 0.0
        self.assert_set_bulk(sampling_params)
        # Rounds to 0.00
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = float(0.0001) 
        self.assert_set_bulk_exception(sampling_params)
        # Rounds to 0.01
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = float(0.006) 
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = 1.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = 10.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = 100.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = 1000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = 10000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = 100000.0
        self.assert_set_bulk(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = "far"
        self.assert_set_bulk_exception(sampling_params)
        sampling_params[Parameter.HANNING_WINDOW_CUTOFF] = False
        self.assert_set_bulk_exception(sampling_params)
        
        # set to known good
        sampling_params = self.set_baseline_txwavestats_dont_use_conductivity()
        
        
    def leftover_garbage(self):    
        ###
        # Test 2: TXWAVESTATS = Y
        #     Set:
        #         * Tide interval (integer minutes)
        #             - Range 1 - 720
        #         * Tide measurement duration (seconds)
        #             - Range: 10 - 43200 sec
        #         * Measure wave burst after every N tide samples
        #             - Range 1 - 10,000
        #         * Number of wave samples per burst
        #             - Range 4 - 60,000
        #         * wave sample duration
        #             - Range [0.25, 0.5, 0.75, 1.0]
        #             - USE WAVE_SAMPLES_SCANS_PER_SECOND instead
        #               where WAVE_SAMPLES_SCANS_PER_SECOND = 1 / wave_sample_duration
        #         * use start time
        #             - Range [y, n]
        #         * use stop time
        #             - Range [y, n]
        #         * TXWAVESTATS (real-time wave statistics)
        #             - Range [y, n]
        #             OPTIONAL DEPENDING ON TXWAVESTATS
        #             * Show progress messages
        #               - Range [y, n]
        #             * Number of wave samples per burst to use for wave
        #               statistics
        #               - Range > 512, power of 2...
        #             * Use measured temperature and conductivity for
        #               density calculation
        #               - Range [y,n]
        #             * Average water temperature above the pressure sensor
        #               - Degrees C
        #             * Height of pressure sensor from bottom
        #               - Distance Meters
        #             * Number of spectral estimates for each frequency
        #               band
        #               - You may have used Plan Deployment to determine
        #                 desired value
        #             * Minimum allowable attenuation
        #             * Minimum period (seconds) to use in auto-spectrum
        #               Minimum of the two following
        #               - frequency where (measured pressure / pressure at
        #                 surface) < (minimum allowable attenuation / wave
        #                 sample duration).
        #               - (1 / minimum period). Frequencies > fmax are not
        #                 processed.
        #             * Maximum period (seconds) to use in auto-spectrum
        #                - ( 1 / maximum period). Frequencies < fmin are
        #                  not processed.
        #             * Hanning window cutoff
        #                - Hanning window suppresses spectral leakage that
        #                  occurs when time series to be Fourier transformed
        #                  contains periodic signal that does not correspond
        #                  to one of exact frequencies of FFT.
        ###
        
        
        sampling_params = {
            Parameter.TIDE_INTERVAL : 9,
            Parameter.TIDE_MEASUREMENT_DURATION : 540,
            Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS : 1,
            Parameter.WAVE_SAMPLES_PER_BURST : 1024,
            Parameter.WAVE_SAMPLES_SCANS_PER_SECOND : float(4.0),
            Parameter.USE_START_TIME : False,
            Parameter.USE_STOP_TIME : False,
            Parameter.TXWAVESTATS : False,
        }
        #self.assert_set_bulk(sampling_params)

        sampling_params = {
            Parameter.TIDE_INTERVAL : 18, #1,
            Parameter.TIDE_MEASUREMENT_DURATION : 1080,
            Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS : 1,
            Parameter.WAVE_SAMPLES_PER_BURST : 1024,
            Parameter.WAVE_SAMPLES_SCANS_PER_SECOND : float(1.0),
            Parameter.USE_START_TIME : False,
            Parameter.USE_STOP_TIME : False,
            Parameter.TXWAVESTATS : True,
            Parameter.SHOW_PROGRESS_MESSAGES : True,
            Parameter.NUM_WAVE_SAMPLES_PER_BURST_FOR_WAVE_STASTICS : 512,
            Parameter.USE_MEASURED_TEMP_AND_CONDUCTIVITY_FOR_DENSITY_CALC : True,
            Parameter.PRESSURE_SENSOR_HEIGHT_FROM_BOTTOM: 10.0,
            Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND : 1,
            Parameter.MIN_ALLOWABLE_ATTENUATION : 1.0,
            Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM : 1.0,
            Parameter.MAX_PERIOD_IN_AUTO_SPECTRUM : 1.0,
            Parameter.HANNING_WINDOW_CUTOFF : 1.0
        }
        #self.assert_set_bulk(sampling_params)

        """
        Test 3: These 2 prompts appears only if you enter N for using measured T and C for density calculation
                Average water temperature above the pressure sensor (Deg C) = 15.0, new value =
                Average salinity above the pressure sensor (PSU) = 35.0, new value =

        """
        sampling_params = {
            Parameter.TIDE_INTERVAL : 18, #4,
            Parameter.TIDE_MEASUREMENT_DURATION : 1080, #40,
            Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS : 1,
            Parameter.WAVE_SAMPLES_PER_BURST : 1024,
            Parameter.WAVE_SAMPLES_SCANS_PER_SECOND : float(1.0),
            Parameter.USE_START_TIME : False,
            Parameter.USE_STOP_TIME : False,
            Parameter.TXWAVESTATS : True,
            Parameter.SHOW_PROGRESS_MESSAGES : True,
            Parameter.NUM_WAVE_SAMPLES_PER_BURST_FOR_WAVE_STASTICS : 512,
            Parameter.USE_MEASURED_TEMP_AND_CONDUCTIVITY_FOR_DENSITY_CALC : False,
            Parameter.AVERAGE_WATER_TEMPERATURE_ABOVE_PRESSURE_SENSOR : float(15.0),
            Parameter.AVERAGE_SALINITY_ABOVE_PRESSURE_SENSOR : float(37.6),
            Parameter.PRESSURE_SENSOR_HEIGHT_FROM_BOTTOM: 10.0,
            Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND : 1,
            Parameter.MIN_ALLOWABLE_ATTENUATION : 1.0,
            Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM : 1.0,
            Parameter.MAX_PERIOD_IN_AUTO_SPECTRUM : 1.0,
            Parameter.HANNING_WINDOW_CUTOFF : 1.0
        }
        #self.assert_set_bulk(sampling_params)

        """

        Test 1B: TXWAVESTATS = N, NEGATIVE TESTING
            Set:
                * Tide interval (integer minutes)
                    - Range 1 - 720 (SEND OUT OF RANGE HIGH)
                * Tide measurement duration (seconds)
                    - Range: 10 - 43200 sec (SEND OUT OF RANGE LOW)
                * Measure wave burst after every N tide samples
                    - Range 1 - 10,000 (SEND OUT OF RANGE HIGH)
                * Number of wave samples per burst
                    - Range 4 - 60,000 (SEND OUT OF RANGE LOW)
                * wave sample duration
                    - Range [0.25, 0.5, 0.75, 1.0] (SEND OUT OF RANGE HIGH)
                    - USE WAVE_SAMPLES_SCANS_PER_SECOND instead
                      where WAVE_SAMPLES_SCANS_PER_SECOND = 1 / wave_sample_duration
                * use start time
                    - Range [y, n]
                * use stop time
                    - Range [y, n]
                * TXWAVESTATS (real-time wave statistics)
        """
        sampling_params = {
            Parameter.TIDE_INTERVAL : 800,
            Parameter.TIDE_MEASUREMENT_DURATION : 1,
            Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS : 20000,
            Parameter.WAVE_SAMPLES_PER_BURST : 1,
            Parameter.WAVE_SAMPLES_SCANS_PER_SECOND : float(2.0),
            Parameter.USE_START_TIME : False,
            Parameter.USE_STOP_TIME : False,
            Parameter.TXWAVESTATS : False,
        }

        #try:
        #    #reply = self.driver_client.cmd_dvr('execute_resource', ProtocolEvent.SETSAMPLING, sampling_params)
        #    reply = self.driver_client.cmd_dvr('set_resource', sampling_params)
        #except InstrumentParameterException:
        #    exception = True
        #self.assertTrue(exception)

    def test_take_sample(self):
        """
        @brief execute the take_sample (ts) command and verify that a line with at
        least 3 floats is returned, indicating a acceptable sample.
        """
        self.assert_initialize_driver()

        # take a sample.
        sample = self.driver_client.cmd_dvr('execute_resource', ProtocolEvent.ACQUIRE_SAMPLE)
        log.debug("sample = " + repr(sample[1]))
        TS_REGEX = r' +([\-\d.]+) +([\-\d.]+) +([\-\d.]+)'
        TS_REGEX_MATCHER = re.compile(TS_REGEX)
        matches = TS_REGEX_MATCHER.match(sample[1])

        log.debug("COUNT = " + str(len(matches.groups())))
        self.assertEqual(3, len(matches.groups()))

    def test_init_logging(self):
        """
        @brief Test initialize logging command.
        """
        self.assert_initialize_driver()
        reply = self.driver_client.cmd_dvr('execute_resource', ProtocolEvent.INIT_LOGGING)
        self.assertTrue(reply)

        self.driver_client.cmd_dvr('execute_resource', ProtocolEvent.ACQUIRE_STATUS)
        self.assert_get(Parameter.LOGGING, True)

    def test_quit_session(self):
        """
        @brief Test quit session command.
        quit session causes the instrument to enter a timedout state where it uses less power.

        this test wakes it up after placing it in the timedout (quit session) state, then
        verifies it can obtain paramaters to assert the instrument is working.
        """
        self.assert_initialize_driver()

        # Note quit session just sleeps the device, so its safe to remain in COMMAND mode.
        reply = self.driver_client.cmd_dvr('execute_resource', ProtocolEvent.QUIT_SESSION)

        self.assertEqual(reply, None)

        # Must stay in COMMAND state (but sleeping)
        self.assert_current_state(ProtocolState.COMMAND)
        # now can we return to command state?

        self.driver_client.cmd_dvr('execute_resource', ProtocolEvent.ACQUIRE_STATUS)
        self.assert_get(Parameter.LOGGING, False)

    def test_get_resource_capabilities(self):
        """
        Test get resource capabilities.
        """
        # Test the driver is in state unconfigured.
        self.assert_initialize_driver()

        # COMMAND
        (res_cmds, res_params) = self.driver_client.cmd_dvr('get_resource_capabilities')
        for state in ['DRIVER_EVENT_ACQUIRE_STATUS', 'DRIVER_EVENT_ACQUIRE_SAMPLE',
                      'DRIVER_EVENT_START_AUTOSAMPLE', 'DRIVER_EVENT_CLOCK_SYNC']:
            self.assertTrue(state in res_cmds)
        self.assertEqual(len(res_cmds), 4)

        # Verify all paramaters are present in res_params

        # DS
        self.assertTrue(Parameter.DEVICE_VERSION in res_params)
        self.assertTrue(Parameter.SERIAL_NUMBER in res_params)
        self.assertTrue(Parameter.DS_DEVICE_DATE_TIME in res_params)
        self.assertTrue(Parameter.USER_INFO in res_params)
        self.assertTrue(Parameter.QUARTZ_PRESSURE_SENSOR_SERIAL_NUMBER in res_params)
        self.assertTrue(Parameter.QUARTZ_PRESSURE_SENSOR_RANGE in res_params)
        self.assertTrue(Parameter.EXTERNAL_TEMPERATURE_SENSOR in res_params)
        self.assertTrue(Parameter.CONDUCTIVITY in res_params)
        self.assertTrue(Parameter.IOP_MA in res_params)
        self.assertTrue(Parameter.VMAIN_V in res_params)
        self.assertTrue(Parameter.VLITH_V in res_params)
        self.assertTrue(Parameter.LAST_SAMPLE_P in res_params)
        self.assertTrue(Parameter.LAST_SAMPLE_T in res_params)
        self.assertTrue(Parameter.LAST_SAMPLE_S in res_params)

        # DS/SETSAMPLING
        self.assertTrue(Parameter.TIDE_INTERVAL in res_params)
        self.assertTrue(Parameter.TIDE_MEASUREMENT_DURATION in res_params)
        self.assertTrue(Parameter.TIDE_SAMPLES_BETWEEN_WAVE_BURST_MEASUREMENTS in res_params)
        self.assertTrue(Parameter.WAVE_SAMPLES_PER_BURST in res_params)
        self.assertTrue(Parameter.WAVE_SAMPLES_SCANS_PER_SECOND in res_params)
        self.assertTrue(Parameter.USE_START_TIME in res_params)
        #Parameter.START_TIME,
        self.assertTrue(Parameter.USE_STOP_TIME in res_params)
        #Parameter.STOP_TIME,
        self.assertTrue(Parameter.TXWAVESTATS in res_params)
        self.assertTrue(Parameter.TIDE_SAMPLES_PER_DAY in res_params)
        self.assertTrue(Parameter.WAVE_BURSTS_PER_DAY in res_params)
        self.assertTrue(Parameter.MEMORY_ENDURANCE in res_params)
        self.assertTrue(Parameter.NOMINAL_ALKALINE_BATTERY_ENDURANCE in res_params)
        self.assertTrue(Parameter.TOTAL_RECORDED_TIDE_MEASUREMENTS in res_params)
        self.assertTrue(Parameter.TOTAL_RECORDED_WAVE_BURSTS in res_params)
        self.assertTrue(Parameter.TIDE_MEASUREMENTS_SINCE_LAST_START in res_params)
        self.assertTrue(Parameter.WAVE_BURSTS_SINCE_LAST_START in res_params)
        self.assertTrue(Parameter.TXREALTIME in res_params)
        self.assertTrue(Parameter.TXWAVEBURST in res_params)
        self.assertTrue(Parameter.NUM_WAVE_SAMPLES_PER_BURST_FOR_WAVE_STASTICS in res_params)
        self.assertTrue(Parameter.USE_MEASURED_TEMP_AND_CONDUCTIVITY_FOR_DENSITY_CALC in res_params)
        self.assertTrue(Parameter.AVERAGE_WATER_TEMPERATURE_ABOVE_PRESSURE_SENSOR in res_params)
        self.assertTrue(Parameter.AVERAGE_SALINITY_ABOVE_PRESSURE_SENSOR in res_params)
        self.assertTrue(Parameter.PRESSURE_SENSOR_HEIGHT_FROM_BOTTOM in res_params)
        self.assertTrue(Parameter.SPECTRAL_ESTIMATES_FOR_EACH_FREQUENCY_BAND in res_params)
        self.assertTrue(Parameter.MIN_ALLOWABLE_ATTENUATION in res_params)
        self.assertTrue(Parameter.MIN_PERIOD_IN_AUTO_SPECTRUM in res_params)
        self.assertTrue(Parameter.MAX_PERIOD_IN_AUTO_SPECTRUM in res_params)
        self.assertTrue(Parameter.HANNING_WINDOW_CUTOFF in res_params)
        self.assertTrue(Parameter.SHOW_PROGRESS_MESSAGES in res_params)
        self.assertTrue(Parameter.STATUS in res_params)
        self.assertTrue(Parameter.LOGGING in res_params)

        reply = self.driver_client.cmd_dvr('execute_resource', Capability.START_AUTOSAMPLE)

        # Test the driver is in command mode.
        state = self.driver_client.cmd_dvr('get_resource_state')
        self.assertEqual(state, ProtocolState.AUTOSAMPLE)


        (res_cmds, res_params) = self.driver_client.cmd_dvr('get_resource_capabilities')
        for state in ['DRIVER_EVENT_STOP_AUTOSAMPLE']:
            self.assertTrue(state in res_cmds)
        self.assertEqual(len(res_cmds), 1)
        reply = self.driver_client.cmd_dvr('execute_resource', Capability.STOP_AUTOSAMPLE)

        # Test the driver is in command mode.
        state = self.driver_client.cmd_dvr('get_resource_state')
        self.assertEqual(state, ProtocolState.COMMAND)


        (res_cmds, res_params) = self.driver_client.cmd_dvr('get_resource_capabilities')
        for state in ['DRIVER_EVENT_ACQUIRE_STATUS', 'DRIVER_EVENT_ACQUIRE_SAMPLE',
                      'DRIVER_EVENT_START_AUTOSAMPLE', 'DRIVER_EVENT_CLOCK_SYNC']:
            self.assertTrue(state in res_cmds)
        self.assertEqual(len(res_cmds), 4)

    def test_connect_configure_disconnect(self):
        """
        @brief connect and then disconnect, verify state
        """
        self.assert_initialize_driver()

        reply = self.driver_client.cmd_dvr('disconnect')
        self.assertEqual(reply, None)

        self.assert_current_state(DriverConnectionState.DISCONNECTED)

    def test_bad_commands(self):
        """
        @brief test that bad commands are handled with grace and style.
        """

        # Test the driver is in state unconfigured.
        self.check_state(DriverConnectionState.UNCONFIGURED)

        # Test bad commands in UNCONFIGURED state.

        exception_happened = False
        try:
            state = self.driver_client.cmd_dvr('conquer_the_world')
        except InstrumentCommandException as ex:
            exception_happened = True
            log.debug("1 - conquer_the_world - Caught expected exception = " + str(ex.__class__.__name__))
        self.assertTrue(exception_happened)

        # Test the driver is configured for comms.
        reply = self.driver_client.cmd_dvr('configure', self.port_agent_comm_config())

        self.check_state(DriverConnectionState.DISCONNECTED)

        # Test bad commands in DISCONNECTED state.

        exception_happened = False
        try:
            state = self.driver_client.cmd_dvr('test_the_waters')
        except InstrumentCommandException as ex:
            exception_happened = True
            log.debug("2 - test_the_waters - Caught expected exception = " + str(ex.__class__.__name__))
        self.assertTrue(exception_happened)


        # Test the driver is in unknown state.
        reply = self.driver_client.cmd_dvr('connect')
        self.check_state(ProtocolState.UNKNOWN)

        # Test bad commands in UNKNOWN state.

        exception_happened = False
        try:
            state = self.driver_client.cmd_dvr("skip_to_the_loo")
        except InstrumentCommandException as ex:
            exception_happened = True
            log.debug("3 - skip_to_the_loo - Caught expected exception = " + str(ex.__class__.__name__))
        self.assertTrue(exception_happened)



        # Test the driver is in command mode.
        reply = self.driver_client.cmd_dvr('discover_state')

        self.check_state(ProtocolState.COMMAND)


        # Test bad commands in COMMAND state.

        exception_happened = False
        try:
            state = self.driver_client.cmd_dvr("... --- ..., ... --- ...")
        except InstrumentCommandException as ex:
            exception_happened = True
            log.debug("4 - ... --- ..., ... --- ... - Caught expected exception = " + str(ex.__class__.__name__))
        self.assertTrue(exception_happened)

    def test_poll(self):
        """
        @brief Test sample polling commands and events.
        also tests execute_resource
        """
        # Test the driver is in state unconfigured.
        self.put_instrument_in_command_mode()


        # Poll for a sample and confirm result.
        sample1 = self.driver_client.cmd_dvr('execute_resource', Capability.ACQUIRE_SAMPLE)
        log.debug("SAMPLE1 = " + str(sample1[1]))

        # Poll for a sample and confirm result.
        sample2 = self.driver_client.cmd_dvr('execute_resource', Capability.ACQUIRE_SAMPLE)
        log.debug("SAMPLE2 = " + str(sample2[1]))

        # Poll for a sample and confirm result.
        sample3 = self.driver_client.cmd_dvr('execute_resource', Capability.ACQUIRE_SAMPLE)
        log.debug("SAMPLE3 = " + str(sample3[1]))

        TS_REGEX = r' +([\-\d.]+) +([\-\d.]+) +([\-\d.]+)'
        TS_REGEX_MATCHER = re.compile(TS_REGEX)

        matches1 = TS_REGEX_MATCHER.match(sample1[1])
        self.assertEqual(3, len(matches1.groups()))

        matches2 = TS_REGEX_MATCHER.match(sample2[1])
        self.assertEqual(3, len(matches2.groups()))

        matches3 = TS_REGEX_MATCHER.match(sample3[1])
        self.assertEqual(3, len(matches3.groups()))




        # Confirm that 3 samples arrived as published events.
        gevent.sleep(1)
        sample_events = [evt for evt in self.events if evt['type']==DriverAsyncEvent.SAMPLE]

        self.assertEqual(len(sample_events), 12)

        # Disconnect from the port agent.
        reply = self.driver_client.cmd_dvr('disconnect')

        # Test the driver is configured for comms.
        self.check_state(DriverConnectionState.DISCONNECTED)

        # Deconfigure the driver.
        reply = self.driver_client.cmd_dvr('initialize')

        # Test the driver is in state unconfigured.
        self.check_state(DriverConnectionState.UNCONFIGURED)

    def test_connect(self):
        """
        Test configuring and connecting to the device through the port
        agent. Discover device state.
        """
        log.info("test_connect test started")
        self.put_instrument_in_command_mode()

        # Configure driver for comms and transition to disconnected.
        reply = self.driver_client.cmd_dvr('disconnect')

        # Test the driver is configured for comms.
        self.check_state(DriverConnectionState.DISCONNECTED)

        # Initialize the driver and transition to unconfigured.
        reply = self.driver_client.cmd_dvr('initialize')

        # Test the driver is in state unconfigured.
        self.check_state(DriverConnectionState.UNCONFIGURED)

    def test_clock_sync(self):
        self.put_instrument_in_command_mode()
        self.driver_client.cmd_dvr('execute_resource', ProtocolEvent.CLOCK_SYNC)
        self.check_state(ProtocolState.COMMAND)

###############################################################################
#                            QUALIFICATION TESTS                              #
# Device specific qualification tests are for                                 #
# testing device specific capabilities                                        #
###############################################################################
@attr('QUAL', group='mi')
class SeaBird26PlusQualificationTest(SeaBirdQualificationTest, SeaBird26PlusMixin):
    def setUp(self):
        SeaBirdQualificationTest.setUp(self)

    def check_state(self, desired_state):
        current_state = self.instrument_agent_client.get_agent_state()
        self.assertEqual(current_state, desired_state)

    ###
    #    Add instrument specific qualification tests
    ###

    def test_autosample(self):
        """
        @brief Test instrument driver execute interface to start and stop streaming
        mode.
        """

        self.data_subscribers.start_data_subscribers()
        self.addCleanup(self.data_subscribers.stop_data_subscribers)


        self.assert_enter_command_mode()

        params = {
            Parameter.TIDE_INTERVAL : 1,
            Parameter.TXWAVESTATS : False,
            Parameter.USER_INFO : "KILROY WAZ HERE"
        }

        self.instrument_agent_client.set_resource(params)

        #self.data_subscribers.no_samples = 3

        # Begin streaming.
        cmd = AgentCommand(command=ProtocolEvent.START_AUTOSAMPLE)
        retval = self.instrument_agent_client.execute_resource(cmd)

        self.data_subscribers.clear_sample_queue(DataParticleValue.PARSED)

        # wait for 3 samples, then test them!
        samples = self.data_subscribers.get_samples('parsed', 30) # 6 minutes
        self.assertSampleDataParticle(samples.pop())
        self.assertSampleDataParticle(samples.pop())
        self.assertSampleDataParticle(samples.pop())

        # Halt streaming.
        cmd = AgentCommand(command=ProtocolEvent.STOP_AUTOSAMPLE)
        # could be in a tide sample cycle... long timeout
        retval = self.instrument_agent_client.execute_resource(cmd0)

        state = self.instrument_agent_client.get_agent_state()
        self.assertEqual(state, ResourceAgentState.COMMAND)

        cmd = AgentCommand(command=ResourceAgentEvent.RESET)
        retval = self.instrument_agent_client.execute_agent(cmd)

        state = self.instrument_agent_client.get_agent_state()
        self.assertEqual(state, ResourceAgentState.UNINITIALIZED)

    def test_direct_access_telnet_mode(self):
        """
        @brief This test manually tests that the Instrument Driver properly supports direct access to the physical instrument. (telnet mode)
        """
        self.assert_enter_command_mode()
        params = [Parameter.EXTERNAL_TEMPERATURE_SENSOR]
        check_new_params = self.instrument_agent_client.get_resource(params)
        self.assertTrue(check_new_params[Parameter.EXTERNAL_TEMPERATURE_SENSOR])

        # go into direct access, and muck up a setting.
        self.assert_direct_access_start_telnet(timeout=600)
        self.assertTrue(self.tcp_client)
        self.tcp_client.send_data(Parameter.EXTERNAL_TEMPERATURE_SENSOR + "=N\r\n")
        self.tcp_client.expect("S>")

        self.assert_direct_access_stop_telnet()

        # verify the setting got restored.
        self.assert_enter_command_mode()
        params = [Parameter.EXTERNAL_TEMPERATURE_SENSOR]
        check_new_params = self.instrument_agent_client.get_resource(params)
        self.assertTrue(check_new_params[Parameter.EXTERNAL_TEMPERATURE_SENSOR])

    def test_get_capabilities(self):
        """
        @brief Verify that the correct capabilities are returned from get_capabilities
        at various driver/agent states.
        """
        state = self.instrument_agent_client.get_agent_state()
        self.assertEqual(state, ResourceAgentState.UNINITIALIZED)

        agent_capabilities = []
        unknown = []
        driver_capabilities = []
        driver_vars = []
        retval = self.instrument_agent_client.get_capabilities()
        for x in retval:
            if x.cap_type == 1:
                agent_capabilities.append(x.name)
            elif x.cap_type == 2:
                unknown.append(x.name)
            elif x.cap_type == 3:
                driver_capabilities.append(x.name)
            elif x.cap_type == 4:
                driver_vars.append(x.name)
            else:
                log.debug("*UNKNOWN* " + str(repr(x)))

        #--- Verify the following for ResourceAgentState.UNINITIALIZED
        self.assertEqual(agent_capabilities, ['RESOURCE_AGENT_EVENT_INITIALIZE'])
        self.assertEqual(unknown, ['example'])
        self.assertEqual(driver_capabilities, [])
        self.assertEqual(driver_vars, [])

        cmd = AgentCommand(command=ResourceAgentEvent.INITIALIZE)
        retval = self.instrument_agent_client.execute_agent(cmd)
        state = self.instrument_agent_client.get_agent_state()
        self.assertEqual(state, ResourceAgentState.INACTIVE)


        agent_capabilities = []
        unknown = []
        driver_capabilities = []
        driver_vars = []
        retval = self.instrument_agent_client.get_capabilities()

        for x in retval:
            if x.cap_type == 1:
                agent_capabilities.append(x.name)
            elif x.cap_type == 2:
                unknown.append(x.name)
            elif x.cap_type == 3:
                driver_capabilities.append(x.name)
            elif x.cap_type == 4:
                driver_vars.append(x.name)
            else:
                log.debug("*UNKNOWN* " + str(repr(x)))

        #--- Verify the following for ResourceAgentState.INACTIVE
        self.assertEqual(agent_capabilities, ['RESOURCE_AGENT_EVENT_GO_ACTIVE', 'RESOURCE_AGENT_EVENT_RESET'])
        self.assertEqual(unknown, ['example'])
        self.assertEqual(driver_capabilities, [])
        self.assertEqual(driver_vars, [])


        cmd = AgentCommand(command=ResourceAgentEvent.GO_ACTIVE)
        retval = self.instrument_agent_client.execute_agent(cmd)
        state = self.instrument_agent_client.get_agent_state()
        self.assertEqual(state, ResourceAgentState.IDLE)


        agent_capabilities = []
        unknown = []
        driver_capabilities = []
        driver_vars = []
        retval = self.instrument_agent_client.get_capabilities()

        for x in retval:
            if x.cap_type == 1:
                agent_capabilities.append(x.name)
            elif x.cap_type == 2:
                unknown.append(x.name)
            elif x.cap_type == 3:
                driver_capabilities.append(x.name)
            elif x.cap_type == 4:
                driver_vars.append(x.name)
            else:
                log.debug("*UNKNOWN* " + str(repr(x)))

        #--- Verify the following for ResourceAgentState.IDLE
        self.assertEqual(agent_capabilities, ['RESOURCE_AGENT_EVENT_GO_INACTIVE', 'RESOURCE_AGENT_EVENT_RESET',
                                              'RESOURCE_AGENT_EVENT_RUN'])
        self.assertEqual(unknown, ['example'])
        self.assertEqual(driver_capabilities, [])
        self.assertEqual(driver_vars, [])

        cmd = AgentCommand(command=ResourceAgentEvent.RUN)
        retval = self.instrument_agent_client.execute_agent(cmd)
        state = self.instrument_agent_client.get_agent_state()
        self.assertEqual(state, ResourceAgentState.COMMAND)

        agent_capabilities = []
        unknown = []
        driver_capabilities = []
        driver_vars = []
        retval = self.instrument_agent_client.get_capabilities()

        for x in retval:
            if x.cap_type == 1:
                agent_capabilities.append(x.name)
            elif x.cap_type == 2:
                unknown.append(x.name)
            elif x.cap_type == 3:
                driver_capabilities.append(x.name)
            elif x.cap_type == 4:
                driver_vars.append(x.name)
            else:
                log.debug("*UNKNOWN* " + str(repr(x)))

        #--- Verify the following for ResourceAgentState.COMMAND
        self.assertEqual(agent_capabilities, ['RESOURCE_AGENT_EVENT_CLEAR', 'RESOURCE_AGENT_EVENT_RESET',
                                              'RESOURCE_AGENT_EVENT_GO_DIRECT_ACCESS',
                                              'RESOURCE_AGENT_EVENT_GO_INACTIVE',
                                              'RESOURCE_AGENT_EVENT_PAUSE'])
        self.assertEqual(unknown, ['example'])
        self.assertEqual(driver_capabilities, ['DRIVER_EVENT_ACQUIRE_STATUS',
                                               'DRIVER_EVENT_ACQUIRE_SAMPLE',
                                               #'DRIVER_EVENT_SET', 'DRIVER_EVENT_GET',
                                               'DRIVER_EVENT_START_AUTOSAMPLE',
                                               'DRIVER_EVENT_CLOCK_SYNC'])
        # Assert all PARAMS are present.
        for p in PARAMS.keys():
            self.assertTrue(p in driver_vars)


        cmd = AgentCommand(command=ResourceAgentEvent.GO_DIRECT_ACCESS,
            kwargs={'session_type': DirectAccessTypes.telnet,
                    #kwargs={'session_type':DirectAccessTypes.vsp,
                    'session_timeout':600,
                    'inactivity_timeout':600})
        retval = self.instrument_agent_client.execute_agent(cmd)
        state = self.instrument_agent_client.get_agent_state()
        self.assertEqual(state, ResourceAgentState.DIRECT_ACCESS)

        agent_capabilities = []
        unknown = []
        driver_capabilities = []
        driver_vars = []
        retval = self.instrument_agent_client.get_capabilities()

        for x in retval:
            if x.cap_type == 1:
                agent_capabilities.append(x.name)
            elif x.cap_type == 2:
                unknown.append(x.name)
            elif x.cap_type == 3:
                driver_capabilities.append(x.name)
            elif x.cap_type == 4:
                driver_vars.append(x.name)
            else:
                log.debug("*UNKNOWN* " + str(repr(x)))

        #--- Verify the following for ResourceAgentState.COMMAND
        log.debug("HEREHEREHERE" + str(agent_capabilities))
        self.assertEqual(agent_capabilities, [])

    def test_execute_capability_from_invalid_state(self):
        """
        @brief Perform netative testing that capabilitys utilized
        from wrong states are caught and handled gracefully.
        """
        state = self.instrument_agent_client.get_agent_state()
        self.assertEqual(state, ResourceAgentState.UNINITIALIZED)

        # Lets try GO_ACTIVE too early....

        exception_happened = False
        try:
            cmd = AgentCommand(command=ResourceAgentEvent.GO_ACTIVE)
            retval = self.instrument_agent_client.execute_agent(cmd)
        except Conflict as ex:
            exception_happened = True
            log.debug("1 - GO_ACTIVE - Caught expected exception = " + str(ex.__class__.__name__))
        self.assertTrue(exception_happened)
        state = self.instrument_agent_client.get_agent_state()
        self.assertEqual(state, ResourceAgentState.UNINITIALIZED)

        # Lets try RUN too early....

        exception_happened = False
        try:
            cmd = AgentCommand(command=ResourceAgentEvent.RUN)
            retval = self.instrument_agent_client.execute_agent(cmd)
        except Conflict as ex:
            exception_happened = True
            log.debug("2 - RUN - Caught expected exception = " + str(ex.__class__.__name__))
        self.assertTrue(exception_happened)
        state = self.instrument_agent_client.get_agent_state()
        self.assertEqual(state, ResourceAgentState.UNINITIALIZED)

        # Now advance to next state

        cmd = AgentCommand(command=ResourceAgentEvent.INITIALIZE) #*****
        retval = self.instrument_agent_client.execute_agent(cmd)
        self.check_state(ResourceAgentState.INACTIVE)
        #state = self.instrument_agent_client.get_agent_state()
        #self.assertEqual(state, ResourceAgentState.INACTIVE)

        # Lets try RUN too early....

        exception_happened = False
        try:
            cmd = AgentCommand(command=ResourceAgentEvent.RUN)
            retval = self.instrument_agent_client.execute_agent(cmd)
        except Conflict as ex:
            exception_happened = True
            log.debug("3 - RUN - Caught expected exception = " + str(ex.__class__.__name__))
        self.assertTrue(exception_happened)
        state = self.instrument_agent_client.get_agent_state()
        self.assertEqual(state, ResourceAgentState.INACTIVE)

        cmd = AgentCommand(command=ResourceAgentEvent.GO_ACTIVE)
        retval = self.instrument_agent_client.execute_agent(cmd)
        self.check_state(ResourceAgentState.IDLE)
        #state = self.instrument_agent_client.get_agent_state()
        #self.assertEqual(state, ResourceAgentState.IDLE)

        # Lets try INITIALIZE too late....

        exception_happened = False
        try:
            cmd = AgentCommand(command=ResourceAgentEvent.INITIALIZE)
            retval = self.instrument_agent_client.execute_agent(cmd)
        except Conflict as ex:
            exception_happened = True
            log.debug("4 - INITIALIZE - Caught expected exception = " + str(ex.__class__.__name__))
        self.assertTrue(exception_happened)
        state = self.instrument_agent_client.get_agent_state()
        self.assertEqual(state, ResourceAgentState.IDLE)

        cmd = AgentCommand(command=ResourceAgentEvent.RUN) #*****
        retval = self.instrument_agent_client.execute_agent(cmd)
        self.check_state(ResourceAgentState.COMMAND)
        #state = self.instrument_agent_client.get_agent_state()
        #self.assertEqual(state, ResourceAgentState.COMMAND)

        # Lets try RUN too when in COMMAND....

        exception_happened = False
        try:
            cmd = AgentCommand(command=ResourceAgentEvent.RUN)
            retval = self.instrument_agent_client.execute_agent(cmd)
        except Conflict as ex:
            exception_happened = True
            log.debug("5 - RUN - Caught expected exception = " + str(ex.__class__.__name__))
        self.assertTrue(exception_happened)
        self.check_state(ResourceAgentState.COMMAND)
        #state = self.instrument_agent_client.get_agent_state()
        #self.assertEqual(state, ResourceAgentState.COMMAND)

        # Lets try INITIALIZE too late....

        exception_happened = False
        try:
            cmd = AgentCommand(command=ResourceAgentEvent.INITIALIZE)
            retval = self.instrument_agent_client.execute_agent(cmd)
        except Conflict as ex:
            exception_happened = True
            log.debug("6 - INITIALIZE - Caught expected exception = " + str(ex.__class__.__name__))
        self.assertTrue(exception_happened)
        self.check_state(ResourceAgentState.COMMAND)
        #state = self.instrument_agent_client.get_agent_state()
        #self.assertEqual(state, ResourceAgentState.COMMAND)

        # Lets try GO_ACTIVE too late....

        exception_happened = False
        try:
            cmd = AgentCommand(command=ResourceAgentEvent.GO_ACTIVE)
            retval = self.instrument_agent_client.execute_agent(cmd)
        except Conflict as ex:
            exception_happened = True
            log.debug("7 - GO_ACTIVE - Caught expected exception = " + str(ex.__class__.__name__))
        self.assertTrue(exception_happened)

        self.check_state(ResourceAgentState.COMMAND)
        #state = self.instrument_agent_client.get_agent_state()
        #self.assertEqual(state, ResourceAgentState.COMMAND)

    def test_execute_reset(self):
        """
        @brief Walk the driver into command mode and perform a reset
        verifying it goes back to UNINITIALIZED, then walk it back to
        COMMAND to test there are no glitches in RESET
        """
        self.assert_enter_command_mode()

        # Test RESET

        self.assert_reset()

        self.assert_enter_command_mode()

    def test_acquire_sample(self):
        """
        """
        self.assert_sample_polled(self.assertSampleDataParticle, 'parsed')

    def test_connect_disconnect(self):

        self.assert_enter_command_mode()

        cmd = AgentCommand(command=ResourceAgentEvent.RESET)
        retval = self.instrument_agent_client.execute_agent(cmd)

        self.check_state(ResourceAgentState.UNINITIALIZED)

    def test_execute_set_time_parameter(self):
        """
        @brief Set the clock to a bogus date/time, then verify that after
        a discover opoeration it reverts to the system time.
        """

        self.assert_enter_command_mode()

        params = {
            Parameter.DS_DEVICE_DATE_TIME : "01 Jan 2001 01:01:01",
        }

        self.instrument_agent_client.set_resource(params)

        params = [
            Parameter.DS_DEVICE_DATE_TIME,
        ]
        check_new_params = self.instrument_agent_client.get_resource(params)
        log.debug("TESTING TIME = " + repr(check_new_params))

        # assert that we altered the time.
        self.assertTrue('01 JAN 2001  01:' in check_new_params[Parameter.DS_DEVICE_DATE_TIME])

        # now put it back to normal

        params = {
            Parameter.DS_DEVICE_DATE_TIME : time.strftime("%d %b %Y %H:%M:%S", time.gmtime(time.mktime(time.localtime())))
        }

        self.instrument_agent_client.set_resource(params)

        params = [
            Parameter.DS_DEVICE_DATE_TIME,
        ]
        check_new_params = self.instrument_agent_client.get_resource(params)

        # Now verify that at least the date matches
        lt = time.strftime("%d %b %Y %H:%M:%S", time.gmtime(time.mktime(time.localtime())))
        self.assertTrue(lt[:12].upper() in check_new_params[Parameter.DS_DEVICE_DATE_TIME].upper())

    def test_execute_clock_sync(self):
        """
        @brief Test Test EXECUTE_CLOCK_SYNC command.
        """

        self.assert_enter_command_mode()

        self.assert_switch_driver_state(ProtocolEvent.CLOCK_SYNC, ProtocolState.COMMAND)

        # Now verify that at least the date matches
        params = [Parameter.DS_DEVICE_DATE_TIME]
        check_new_params = self.instrument_agent_client.get_resource(params)
        lt = time.strftime("%d %b %Y  %H:%M:%S", time.gmtime(time.mktime(time.localtime())))

        self.assertTrue(lt[:12].upper() in check_new_params[Parameter.DS_DEVICE_DATE_TIME].upper())

