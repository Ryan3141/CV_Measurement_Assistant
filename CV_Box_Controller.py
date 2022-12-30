# Interface for Keysight E4980 outlined in this document: https://literature.cdn.keysight.com/litweb/pdf/E4980-90210.pdf

try:
	import pyvisa as visa
except ImportError:
	from MPL_Shared.Install_If_Necessary import Ask_For_Install
	Ask_For_Install( "PyVisa" )
	import pyvisa as visa
import numpy as np
import time

from rich import print
from PyQt5 import QtCore


class CV_Controller( QtCore.QObject ):
	newSweepStarted_signal = QtCore.pyqtSignal()
	dataPointGotten_signal = QtCore.pyqtSignal(float, float)
	sweepFinished_signal = QtCore.pyqtSignal(np.ndarray, np.ndarray, np.ndarray) # bias_voltage_V, capacitance_F, Q_Data

	Device_Connected = QtCore.pyqtSignal(str,str)
	Device_Disconnected = QtCore.pyqtSignal(str,str)

	Error_signal = QtCore.pyqtSignal( str )

	def __init__( self, parent=None, machine_type="Keysight" ):
		super(CV_Controller, self).__init__(parent)
		self.machine_type = machine_type
		self.gpib_resource = None
		self.debug = 1
		self.Voltage_Sweep_ = self.Voltage_Sweep_Default

	def thread_start( self ):
		self.Initialize_Connection()

	def thread_stop( self ):
		self.Close_Connection()

	def Make_Safe( self ):
		pass

	def Check_Connection_Then_Run( self, func ):
		def newfunc( *args, **kargs ):
			if self.gpib_resource == None:
				self.Error_signal.emit( "CV controller not connected" )
				return
			try:
				# print( f"Check_Connection_Then_Run = {func}" )
				return func( *args, **kargs )
			except Exception as e:
				self.Device_Disconnected.emit( self.machine_type, self.supported_devices[ self.machine_type ][0] )
				self.Error_signal.emit( "CV controller not connected: " + str(e) )
				return

		newfunc.func = func
		return newfunc

	def Initialize_Connection( self ):
		if self.gpib_resource != None:
			self.gpib_resource.close()
			self.gpib_resource = None
		#print( self.resource_manager.list_resources() ) # List available machines to connect to

		self.supported_devices = { "Keysight"     : ( 'GPIB0::17::INSTR',                       (self.Voltage_Sweep_Keysight,) ),
								   "Keithley USB" : ( 'USB0::2391::2313::MY12345678::0::INSTR', (self.Voltage_Sweep_Keysight,) ) }
		try:
			lambda *args, **kargs : self.Check_Connection()
			address = self.supported_devices[ self.machine_type ][0]
			(self.Voltage_Sweep_,) = ( self.Check_Connection_Then_Run(x) for x in self.supported_devices[ self.machine_type ][1] )
			self.resource_manager = visa.ResourceManager()
			self.gpib_resource = self.resource_manager.open_resource(address)
			self.gpib_resource.clear()
			self.Device_Connected.emit( self.machine_type, self.supported_devices[ self.machine_type ][0] )
			self.is_connected = True
			return self.gpib_resource
		except Exception as e:
			print( str(e) )
			self.is_connected = False

		return None


	def Close_Connection( self ):
		# print( f"Closing connection with CV Controller {self.supported_devices[ self.machine_type ][1]}" )
		if self.gpib_resource == None:
			return
		self.gpib_resource.close()
		self.gpib_resource = None

		self.Device_Disconnected.emit( self.machine_type, self.supported_devices[ self.machine_type ][0] )

	def Voltage_Sweep( self, v_start, v_end, v_step, ac_voltage, ac_frequency, step_delay=0.5 ):
		return self.Voltage_Sweep_( v_start, v_end, v_step, ac_voltage, ac_frequency, step_delay )

	def Voltage_Sweep_Default( self, v_start, v_end, v_step, ac_voltage, ac_frequency, step_delay ):
		print( self.Voltage_Sweep )
		# Pretend data to test graphing
		x_values = np.arange( v_start, v_end + v_step, v_step )
		self.newSweepStarted_signal.emit()
		time.sleep( 0.1 )

		for index, x in enumerate(x_values):
			self.dataPointGotten_signal.emit( x, x * 100E-3 * self.debug )
			time.sleep( 0.01 )
		self.sweepFinished_signal.emit( x_values, x_values )
		self.debug += 1


	def Voltage_Sweep_Keysight( self, v_start, v_end, v_step, ac_voltage, ac_frequency, step_delay ):
		M = self.gpib_resource

		empty_data_point = 9E37 # = 9.9E37 or -9.9E37 means np.nan
		self.newSweepStarted_signal.emit()

		x_values = np.arange( v_start, v_end + v_step / 2, v_step )
		bias_list = ','.join([ f'{x:E}' for x in x_values ])
		assert len(x_values) <= 201, "Number of voltage points to sweep must be no more than 201"
		assert ac_voltage <= 20 and ac_voltage >= 0, "ac_voltage must be between 0 and 20 Volts"
		assert ac_frequency <= 2E6 and ac_frequency >= 20, "ac_voltage must be between 20Hz and 2MHz"
		assert step_delay <= 999 and step_delay >= 0, "step_delay must be between 0 and 999 seconds"

		M.write( "*RST;*CLS" ) # Reset everything to known good state (factory defaults)
		M.write( ":DISPLAY:CCLEAR" ) # Clears any lingering error messages
		M.write( ":TRIGGER:SOURCE BUS" ) # Sets trigger source to "GPIB/LAN/USB"
		M.write( ":FORMAT ASCII" ) # Sets the transfer mode to ASCII
		M.write( ":FUNCTION:IMPEDANCE:TYPE CPQ" )
		M.write( f":FREQUENCY {ac_frequency:e}" ) # Sets ac voltage frequency (in Hz) to use during the measurements
		M.write( f":VOLTAGE:LEVEL {ac_voltage:e}" ) # Sets ac voltage frequency (in Hz) to use during the measurements
		M.write( ":AMPLitude:ALC ON" ) # Sets device to 4 point probe mode
		M.write( f":TRIGGER:DELAY {step_delay:e}" ) # Sets delay (in seconds) between successive measurements (not including settling delay)
		#M.write( ":APERTURE LONG,5" ) # Sets the time window to capture a measurement
		#M.write( ":OUTPUT:DC:ISOLATION ON" ) # Enables DC Isolation
		#M.write( ":AMPLITUDE:ALC ON" ) # Turns on automatic leveling control for holding the requested voltage
		#M.write( f':DISPLAY:LINE "{message}"' ) # Displays message on the LCD screen, can be no longer than 30 characters
		#timestr = time.strftime("%Y%m%d-%H%M%S")
		M.write( ":LIST:MODE SEQUENCE" ) # Sets the list sweep mode to sequence mode, when triggered once, the device is measured at all sweep points.
		#bias_list = ','.join([ f'{float(x):E}' for x in np.linspace( 1E-3, 10E-3, 10 )])
		M.write( ":LIST:BIAS:VOLTAGE " + bias_list ) # Sets voltages (in Volts) to sweep through
		#frequency_list = ','.join([ f'{float(x):E}' for x in range(1000, 10000+1, 1000) ])
		#M.write( ":LIST:FREQUENCY " + frequency_list ) # Sets voltages (in Volts) to sweep through
		# ac_voltages_list = ','.join( ['10E-3'] * len(bias_list) )
		# M.write( ":LIST:VOLTAGE " + ac_voltages_list ) # Sets voltages (in Volts) to sweep through
		M.write( ":DISPLAY:PAGE LIST" ) # Sets displayed page to <LIST SWEEP DISPLAY>
		# M.write( ":DISPLAY:PAGE MEASUREMENT" ) # Sets displayed page to <LIST SWEEP DISPLAY>
		# #for i in range( 1, len(bias_list) + 2 ):
		#	M.write( f"LIST:BAND{i} A,1E-4,2E-4" ) # Begins the measurement sweep
		#M.write( f":MEMORY:DIM DBUF, {1}" ) # Clears data buffer memory and sets the data buffer memory's size
		#M.write( f":MEMORY:DIM DBUF, {len(x_values)}" ) # Clears data buffer memory and sets the data buffer memory's size
		#M.write( ":MEMORY:CLEAR DBUF" ) # Clears the data buffer memory and disables it from storing measurement data
		#M.write( ":MEMORY:FILL DBUF" ) # Enables the data buffer memory to store measurement data
		#M.write( ":APERTURE LONG,5" ) # Sets the measurement time mode and the averaging rate
		M.write( ":BIAS:STATE ON" )
		M.write( ":INITIATE:CONTINUOUS ON" ) # Prepares instrument for the measurement sweep
		#M.write( ":INITIATE:IMMEDIATE" ) # Prepares instrument for the measurement sweep
		M.write( ":TRIGGER:IMMEDIATE" ) # Begins the measurement sweep
		#M.write( ":MEMORY:READ? DBUF" ) # Begin reading the data
		#results = []
		#for index, x in enumerate(x_values):
		#	data = M.read()
		#	#print( data )
		#	results.append( float(data) )
		#	self.dataPointGotten_signal.emit( x, float(data) )
		#	if index % 10 == 0:
		#		QtCore.QCoreApplication.processEvents()
		#		if self.stop_measurement_early == True:
		#			self.stop_measurement_early = False
		#			break
		M.write( ":SYSTEM:BEEPER:TONE 1" ) # Makes a beep (1 - 5)
		M.write( ":SYSTEM:BEEPER:IMMEDIATE" ) # Makes a beep (1 - 5)
		M.timeout = 120000 # The measurement may take up to 120 seconds
		results = M.query_ascii_values(":FETCH:IMPEDANCE?", container=np.array)
		M.write( ":BIAS:STATE OFF" )
		#results = M.query_ascii_values(":MEMORY:READ? DBUF", container=np.array)
		by_measurement = np.reshape( results, (len(results)//4,4) )
		Capacitance = [(x[0] if (x[0] < empty_data_point and x[0] > -empty_data_point) else np.nan) for x in by_measurement]
		Q_Data = [(x[1] if (x[1] < empty_data_point and x[1] > -empty_data_point) else np.nan) for x in by_measurement]
		# M.write( ":MEMORY:CLEAR DBUF" ) # Clears the data buffer memory and disables it from storing measurement data
		#results = M.read()
		self.sweepFinished_signal.emit( x_values, np.array(Capacitance), np.array(Q_Data) )
		# return ( x_values, np.array(test) )



if __name__ == "__main__":
	test = CV_Controller()
	test.Run()

	v_start = -1.0
	v_end = 1.0
	v_step = 0.1
	ac_voltage = 1E-6
	ac_frequency = 1E4
	step_delay = 0.5
	test.Voltage_Sweep(v_start, v_end, v_step, ac_voltage, ac_frequency, step_delay)
	#QMetaObject.invokeMethod( test, 'Voltage_Sweep', Qt.AutoConnection,
	#				  Q_RETURN_ARG('int'), Q_ARG(float, v_start), Q_ARG(float, v_end), Q_ARG(float, v_step), Q_ARG(float, ac_voltage), Q_ARG(float, ac_frequency), Q_ARG(float, step_delay) )
